from __future__ import annotations

import io
import os
import zipfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from .. import __version__
from ..config import ScanConfig, default_engines, hosts_of
from ..models import ScanFindings
from ..pipeline import run_local_document_scan, run_scan
from .jobs import Job, JobQueueFull, JobStore
from .schemas import HealthResponse, JobCreated, JobLogResponse, JobStatusResponse, JobSummary, LocalScanRequest, ScanRequest


def _summary_of(findings: ScanFindings) -> JobSummary:
    findings_total = (
        len(findings.usernames) + len(findings.emails) + len(findings.software)
        + len(findings.operating_systems) + len(findings.internal_paths)
        + len(findings.servers_and_printers) + len(findings.geolocation)
    )
    return JobSummary(
        documents_discovered=len(findings.documents),
        documents_with_metadata=findings.documents_with_metadata,
        findings_total=findings_total,
        content_findings=len(findings.content_findings),
        critical_files=len(findings.critical_files),
    )


def _job_links(request: Request, job_id: str) -> dict[str, str]:
    return {
        "self": str(request.url_for("get_job", job_id=job_id)),
        "log": str(request.url_for("get_job_log", job_id=job_id)),
        "report_json": str(request.url_for("get_job_report_json", job_id=job_id)),
        "report_html": str(request.url_for("get_job_report_html", job_id=job_id)),
        "download": str(request.url_for("get_job_download", job_id=job_id)),
    }


def _job_status_response(job: Job, request: Request) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id, kind=job.kind, status=job.status, run_id=job.run_id,
        targets=job.targets, created_at=job.created_at, started_at=job.started_at,
        finished_at=job.finished_at, error=job.error,
        summary=_summary_of(job.findings) if job.findings is not None else None,
        links=_job_links(request, job.job_id),
    )


def _require_job(store: JobStore, job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id!r}. Jobs are in-memory and do not survive a server restart.")
    return job


def _require_done_job(store: JobStore, job_id: str) -> Job:
    job = _require_job(store, job_id)
    if job.status != "done":
        raise HTTPException(
            status_code=409,
            detail={"job_id": job.job_id, "status": job.status, "error": job.error, "message": "Report not available yet — poll GET /v1/scans/{job_id} until status is 'done'."},
        )
    return job


def _submit_or_429(store: JobStore, **kwargs) -> Job:
    try:
        return store.submit(**kwargs)
    except JobQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def create_app(*, output_dir: str = "./metascout_output", max_workers: int = 2, max_pending: int = 50) -> FastAPI:
    """Builds the MetaScout REST API — a separate, job-based HTTP service
    wrapping the same discover -> download -> extract -> analyze pipeline as
    the CLI and the local web UI, for programmatic/enterprise integration
    from anywhere (start a scan, poll its status, pull the JSON/HTML report
    or a zip once it's done — see the README's API section).

    No built-in authentication — same posture as `metascout web`: fine on a
    trusted machine/network as-is, but put it behind something that actually
    authenticates callers (reverse proxy with an API key/mTLS, a
    Tailscale/WireGuard-only network, an API gateway) before exposing it to
    anyone else. Unlike `metascout web`, every job here runs in a background
    thread pool (`max_workers`) so a request returns immediately instead of
    blocking for the scan's full duration; `max_pending` bounds how many jobs
    can be queued/running at once (POST returns 429 past that), so an
    unauthenticated caller can't grow the in-memory job registry without limit.
    """
    os.makedirs(output_dir, exist_ok=True)
    store = JobStore(output_dir=output_dir, max_workers=max_workers, max_pending=max_pending)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        store.shutdown()

    app = FastAPI(
        title="MetaScout API",
        version=__version__,
        description=(
            "Job-based REST API for MetaScout's document discovery and metadata-leak "
            "scanning — start a scan, poll its status, then fetch the JSON/HTML report "
            "or a zip of the full run. No built-in authentication; see the README before "
            "exposing this beyond a trusted machine/network."
        ),
        lifespan=lifespan,
    )

    @app.get("/v1/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        active = sum(1 for j in store.list() if j.status in ("queued", "running"))
        return HealthResponse(status="ok", version=__version__, active_jobs=active)

    @app.post("/v1/scans", response_model=JobCreated, status_code=202, tags=["scans"])
    def create_scan(body: ScanRequest, request: Request) -> JobCreated:
        targets = list(body.targets) or hosts_of(body.manual_urls)
        if not targets:
            raise HTTPException(status_code=422, detail="Could not derive any target from 'manual_urls' — provide 'targets' explicitly.")

        cfg = ScanConfig(
            targets=targets,
            manual_urls=list(body.manual_urls),
            filetypes=[f.strip().lower().lstrip(".") for f in body.filetypes if f.strip()],
            engines=[e.strip().lower() for e in body.engines] if body.engines is not None else default_engines(),
            ddgs_backend=body.ddgs_backend,
            max_docs=body.max_docs,
            max_crawl_pages=body.max_crawl_pages,
            max_crawl_depth=body.max_crawl_depth,
            concurrency=body.concurrency,
            request_timeout=body.timeout,
            max_download_bytes=body.max_download_mb * 1024 * 1024,
            output_dir=output_dir,
            respect_robots=not body.ignore_robots,
            include_subdomains=body.subdomains,
            max_subdomains=body.max_subdomains,
            google_api_key=os.environ.get("GOOGLE_API_KEY"),
            google_cse_id=os.environ.get("GOOGLE_CSE_ID"),
            serper_api_key=os.environ.get("SERPER_API_KEY"),
            brave_api_key=os.environ.get("BRAVE_API_KEY"),
            scan_content=body.scan_content,
            content_categories=[c.strip().lower() for c in body.content_categories if c.strip()],
            visual_signature=body.visual_signature,
            critical_files=body.critical_files,
            critical_file_types=[f.strip().lower().lstrip(".") for f in body.critical_file_types if f.strip()],
        )

        def work(log, run_path):
            # Each job gets its own run_id/output subdirectory (run_path,
            # assigned by JobStore before this runs), so two concurrent jobs
            # never write into the same downloads/ folder.
            cfg.output_dir = run_path
            return run_scan(cfg, log=log)

        job = _submit_or_429(store, kind="scan", targets=targets, report_lang=body.report_lang, work=work)
        return JobCreated(job_id=job.job_id, status="queued", run_id=job.run_id, created_at=job.created_at, links=_job_links(request, job.job_id))

    @app.post("/v1/local-scans", response_model=JobCreated, status_code=202, tags=["scans"])
    def create_local_scan(body: LocalScanRequest, request: Request) -> JobCreated:
        filetypes = [f.strip().lower().lstrip(".") for f in body.filetypes if f.strip()]
        critical_ft = [f.strip().lower().lstrip(".") for f in body.critical_file_types if f.strip()]

        if body.directory:
            if not os.path.isdir(body.directory):
                raise HTTPException(status_code=422, detail=f"Directory {body.directory!r} does not exist or isn't readable from this server.")
            targets = [body.directory]

            def work(log, run_path):
                return run_local_document_scan(
                    body.directory, filetypes=filetypes, scan_content=body.scan_content,
                    content_categories=body.content_categories, visual_signature=body.visual_signature,
                    critical_files=body.critical_files, critical_file_types=critical_ft, log=log,
                )
        else:
            targets = hosts_of(body.urls)

            def work(log, run_path):
                cfg = ScanConfig(
                    targets=targets, manual_urls=list(body.urls), filetypes=filetypes, engines=[],
                    output_dir=run_path, scan_content=body.scan_content,
                    content_categories=body.content_categories, visual_signature=body.visual_signature,
                    critical_files=body.critical_files, critical_file_types=critical_ft,
                )
                return run_scan(cfg, log=log)

        job = _submit_or_429(store, kind="local-scan", targets=targets, report_lang=body.report_lang, work=work)
        return JobCreated(job_id=job.job_id, status="queued", run_id=job.run_id, created_at=job.created_at, links=_job_links(request, job.job_id))

    @app.get("/v1/scans", response_model=list[JobStatusResponse], tags=["scans"])
    def list_jobs(request: Request) -> list[JobStatusResponse]:
        return [_job_status_response(j, request) for j in store.list()]

    @app.get("/v1/scans/{job_id}", response_model=JobStatusResponse, tags=["scans"], name="get_job")
    def get_job(job_id: str, request: Request) -> JobStatusResponse:
        return _job_status_response(_require_job(store, job_id), request)

    @app.get("/v1/scans/{job_id}/log", response_model=JobLogResponse, tags=["scans"], name="get_job_log")
    def get_job_log(job_id: str) -> JobLogResponse:
        job = _require_job(store, job_id)
        return JobLogResponse(job_id=job.job_id, status=job.status, lines=list(job.log_lines))

    @app.get("/v1/scans/{job_id}/report.json", tags=["scans"], name="get_job_report_json")
    def get_job_report_json(job_id: str) -> Response:
        job = _require_done_job(store, job_id)
        path = os.path.join(job.run_path, "report.json")
        with open(path, encoding="utf-8") as fh:
            return Response(content=fh.read(), media_type="application/json")

    @app.get("/v1/scans/{job_id}/report.html", response_class=HTMLResponse, tags=["scans"], name="get_job_report_html")
    def get_job_report_html(job_id: str) -> str:
        job = _require_done_job(store, job_id)
        with open(os.path.join(job.run_path, "report.html"), encoding="utf-8") as fh:
            return fh.read()

    @app.get("/v1/scans/{job_id}/download", tags=["scans"], name="get_job_download")
    def get_job_download(job_id: str) -> StreamingResponse:
        job = _require_done_job(store, job_id)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(job.run_path):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, arcname=os.path.join(job.run_id, os.path.relpath(full, job.run_path)))
        buffer.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="metascout-{job.run_id}.zip"'}
        return StreamingResponse(buffer, media_type="application/zip", headers=headers)

    return app
