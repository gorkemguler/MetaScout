from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal

from ..models import ScanFindings
from ..report import render_html_report, render_json_report

JobKind = Literal["scan", "local-scan"]
JobStatusName = Literal["queued", "running", "done", "error"]


class JobQueueFull(RuntimeError):
    """Raised by JobStore.submit() when max_pending jobs are already queued
    or running. There's no built-in authentication on this service (see
    api/app.py), so without this cap an unauthenticated caller could submit
    an unbounded number of scan jobs in a loop and grow the in-memory job
    registry (and the executor's own internal work queue) without limit —
    this turns that into a clear, bounded 429 instead.
    """

# Work function signature: given a log callback (message: str) -> None and
# the job's own run directory (assigned before the job starts running, so a
# scan job can point its downloads/ subfolder at it), actually runs the scan
# (calling pipeline.run_scan/run_local_document_scan) and returns the
# resulting ScanFindings, or raises on failure. Takes run_path as an
# explicit argument (rather than a route handler closing over a `job`
# variable it assigns only after JobStore.submit() returns) so there's no
# race between the background thread starting and that assignment landing.
JobWork = Callable[[Callable[[str], None], str], ScanFindings]


@dataclass
class Job:
    job_id: str
    kind: JobKind
    run_id: str
    output_dir: str
    report_lang: str
    targets: list[str] = field(default_factory=list)
    status: JobStatusName = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    log_lines: list[str] = field(default_factory=list)
    findings: ScanFindings | None = None

    @property
    def run_path(self) -> str:
        return os.path.join(self.output_dir, self.run_id)


class JobStore:
    """In-memory job registry backed by a bounded thread pool that actually
    runs each scan in the background, so `POST /v1/scans` can return
    immediately (job_id + status=queued) instead of blocking for the scan's
    full duration — unlike the local, single-user web UI (see web.py, whose
    POST /scan blocks synchronously), this is meant to be called by another
    program over a network, where a request blocking for minutes-to-hours
    isn't workable at all (HTTP client/proxy timeouts, no way to show
    progress to a human).

    In-memory only, by design: job status and log history don't survive a
    process restart — this is a lightweight service, not a durable job
    queue with its own database. Completed reports are still safely
    persisted to disk under output_dir/<run_id>/ (report.json/report.html),
    exactly like the CLI and web UI write them, so a restart only loses
    *live* job-tracking state (queued/running, in-progress log lines), never
    a finished result already on disk.
    """

    _LOG_LIMIT = 1000  # log lines kept per job before the oldest are dropped

    def __init__(self, *, output_dir: str, max_workers: int = 2, max_jobs_kept: int = 200, max_pending: int = 50) -> None:
        self.output_dir = output_dir
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="metascout-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs_kept = max_jobs_kept
        self._max_pending = max_pending

    def submit(self, *, kind: JobKind, targets: list[str], report_lang: str, work: JobWork) -> Job:
        with self._lock:
            pending = sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))
            if pending >= self._max_pending:
                raise JobQueueFull(
                    f"{pending} job(s) already queued or running (limit {self._max_pending}) — "
                    "wait for some to finish, or raise --max-pending, before submitting more."
                )
            job_id = uuid.uuid4().hex[:12]
            run_id = f"api-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{job_id[:8]}"
            job = Job(job_id=job_id, kind=kind, run_id=run_id, output_dir=self.output_dir, report_lang=report_lang, targets=targets)
            self._jobs[job_id] = job
            self._evict_finished_past_cap_locked()
        self._executor.submit(self._run, job, work)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _evict_finished_past_cap_locked(self) -> None:
        # Only ever evicts already-finished jobs (done/error), oldest first —
        # a queued/running job is never dropped out from under itself. Caps
        # memory growth for a long-lived process without needing a real
        # job-history database.
        if len(self._jobs) <= self._max_jobs_kept:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status in ("done", "error")),
            key=lambda j: j.created_at,
        )
        for j in finished:
            if len(self._jobs) <= self._max_jobs_kept:
                break
            self._jobs.pop(j.job_id, None)

    def _push_log(self, job: Job, message: str) -> None:
        with self._lock:
            job.log_lines.append(message)
            if len(job.log_lines) > self._LOG_LIMIT:
                job.log_lines = job.log_lines[-self._LOG_LIMIT:]

    def _run(self, job: Job, work: JobWork) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        try:
            findings = work(lambda msg: self._push_log(job, msg), job.run_path)
            job.findings = findings
            os.makedirs(job.run_path, exist_ok=True)
            with open(os.path.join(job.run_path, "report.json"), "w", encoding="utf-8") as fh:
                fh.write(render_json_report(findings))
            with open(os.path.join(job.run_path, "report.html"), "w", encoding="utf-8") as fh:
                fh.write(render_html_report(findings, lang=job.report_lang))
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 - any failure is reported via job.error, never crashes the worker thread
            job.error = str(exc)
            job.status = "error"
            self._push_log(job, f"! job failed: {exc}")
        finally:
            job.finished_at = datetime.now(timezone.utc)
