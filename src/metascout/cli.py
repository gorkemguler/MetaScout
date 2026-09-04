from __future__ import annotations

import json
import os
import sys
import click
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.table import Table

from .config import DEFAULT_CONTENT_CATEGORIES, DEFAULT_CRITICAL_FILETYPES, DEFAULT_FILETYPES, ScanConfig, default_engines, hosts_of
from .pipeline import run_scan
from .report import render_html_report, render_json_report

console = Console()

_ASCII_BANNER = r"""
 __  __      _        ____                 _
|  \/  | ___| |_ __ _/ ___|  ___ ___  _   _| |_
| |\/| |/ _ \ __/ _` \___ \ / __/ _ \| | | | __|
| |  | |  __/ || (_| |___) | (_| (_) | |_| | |_
|_|  |_|\___|\__\__,_|____/ \___\___/ \__,_|\__|
"""


def _print_banner() -> None:
    console.print(f"[bold #8bb4ff]{_ASCII_BANNER}[/bold #8bb4ff]")
    console.print("[dim]Document discovery & metadata reconnaissance — open-source alternative to FOCA[/dim]\n")


def _cli_log(message: str) -> None:
    if message.startswith("!"):
        console.print(f"[yellow]{message}[/yellow]")
    else:
        console.print(f"[bold cyan]›[/bold cyan] {message}")


def _print_summary(findings) -> None:
    table = Table(title="MetaScout findings summary")
    table.add_column("Category")
    table.add_column("Unique values", justify="right")
    for label, bucket in [
        ("Usernames", findings.usernames),
        ("Emails", findings.emails),
        ("Software", findings.software),
        ("Operating systems", findings.operating_systems),
        ("Internal paths", findings.internal_paths),
        ("Servers / printers", findings.servers_and_printers),
        ("Geolocation (GPS)", findings.geolocation),
        ("Critical files (opt-in)", findings.critical_files),
    ]:
        table.add_row(label, str(len(bucket)))
    console.print(table)

    if len(findings.targets) > 1:
        by_target = Table(title="Documents per target")
        by_target.add_column("Target")
        by_target.add_column("Documents", justify="right")
        for t, count in findings.documents_by_target.items():
            by_target.add_row(t, str(count))
        console.print(by_target)

    if findings.content_findings:
        content_table = Table(title="Content scan hits (heuristic — verify manually)")
        content_table.add_column("Category")
        content_table.add_column("Hits", justify="right")
        for category, hits in sorted(findings.content_findings_by_category.items()):
            content_table.add_row(category, str(len(hits)))
        console.print(content_table)

    if findings.critical_files:
        critical_table = Table(title="Critical / sensitive files found (opt-in — review manually)")
        critical_table.add_column("URL")
        critical_table.add_column("Type")
        critical_table.add_column("Status")
        for c in findings.critical_files:
            status = f"[red]error: {c.error}[/red]" if c.error else "[green]ok[/green]"
            critical_table.add_row(c.url, c.filetype, status)
        console.print(critical_table)


def _default_engines_csv() -> str:
    """Click needs a comma-joined string default for --engines (parsed back
    into a list in scan()'s body); config.default_engines() returns the list
    directly, shared with the REST API. See that function for the actual
    auto-detection logic.
    """
    return ",".join(default_engines())


def _collect_targets(targets: tuple[str, ...], targets_file: str | None) -> list[str]:
    all_targets = list(targets)
    if targets_file:
        with open(targets_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    all_targets.append(line)
    return list(dict.fromkeys(t.strip() for t in all_targets if t.strip()))


def _collect_urls(urls_file: str | None) -> list[str]:
    if not urls_file:
        return []
    urls: list[str] = []
    with open(urls_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return list(dict.fromkeys(urls))


@click.group()
def main() -> None:
    """MetaScout — document discovery and metadata reconnaissance tool."""
    # load_dotenv() alone searches upward from this installed module's file
    # location, not the user's current directory — usecwd=True makes it find
    # a .env in whatever directory `metascout` is actually run from.
    load_dotenv(find_dotenv(usecwd=True))


@main.command()
@click.argument("targets", nargs=-1)
@click.option("--targets-file", type=click.Path(exists=True, dir_okay=False), default=None, help="Text file with one target domain/URL per line (# comments allowed).")
@click.option("--urls-file", type=click.Path(exists=True, dir_okay=False), default=None, help="Text file with one full document URL per line to scan directly (# comments allowed) — e.g. links you gathered by hand when an engine didn't work. Skips discovery for those URLs; still downloaded, analyzed, and included in the report like any other result.")
@click.option("--filetypes", default=",".join(DEFAULT_FILETYPES), show_default=True, help="Comma-separated list of file extensions.")
@click.option("--engines", default=_default_engines_csv, help="Comma-separated: crawl,sitemap,wayback,ddgs,google,serper,brave. Defaults to crawl,sitemap,wayback,ddgs plus google/serper/brave automatically if their API keys are set.")
@click.option("--ddgs-backend", default="auto", show_default=True, help="Backend(s) for the 'ddgs' engine, e.g. duckduckgo, google, bing, brave, or 'auto' to fall back across several.")
@click.option("--max-docs", default=50, show_default=True, help="Maximum documents to download and analyze (across all targets).")
@click.option("--max-crawl-pages", default=200, show_default=True)
@click.option("--max-crawl-depth", default=3, show_default=True)
@click.option("--concurrency", default=8, show_default=True)
@click.option("--timeout", default=15, show_default=True, help="Per-request timeout in seconds.")
@click.option("--max-download-mb", default=50, show_default=True)
@click.option("--output-dir", default="./metascout_output", show_default=True, type=click.Path())
@click.option("--ignore-robots", is_flag=True, default=False, help="Ignore robots.txt during crawling (use only with explicit authorization).")
@click.option("--subdomains/--no-subdomains", default=False, help="Enumerate subdomains via crt.sh (Certificate Transparency logs) and scan each one too.")
@click.option("--max-subdomains", default=20, show_default=True, help="Maximum subdomains to scan per target when --subdomains is set.")
@click.option("--google-api-key", envvar="GOOGLE_API_KEY", default=None, help="One key, or comma-separated keys to rotate through when one runs out of quota.")
@click.option("--google-cse-id", envvar="GOOGLE_CSE_ID", default=None)
@click.option("--serper-api-key", envvar="SERPER_API_KEY", default=None, help="Serper.dev API key — a third-party Google SERP API, useful now that Google's own Custom Search API is being discontinued.")
@click.option("--brave-api-key", envvar="BRAVE_API_KEY", default=None)
@click.option("--json-report/--no-json-report", default=True)
@click.option("--html-report/--no-html-report", default=True)
@click.option("--report-lang", type=click.Choice(["en", "tr"]), default="en", show_default=True, help="Language for the HTML report.")
@click.option(
    "--scan-content/--no-scan-content", default=False,
    help="Also scan each downloaded document's body text (not just metadata) for personal/critical data: "
    "national ID numbers, emails/phones, IBANs/card numbers, address/DOB hints, signature hints, "
    "leaked credentials (AWS/GitHub/Slack/Stripe keys, private key blocks, DB connection strings, JWTs), "
    "and leaked infrastructure info (cloud storage/file-share links, internal hostnames/private IPs). "
    "Off by default — heuristic, and requires the optional extra: pip install 'metascout[content-scan]'.",
)
@click.option(
    "--content-categories", default=",".join(DEFAULT_CONTENT_CATEGORIES), show_default=True,
    help="Comma-separated subset of: tc_kimlik,email_phone,iban_card,address_dob,signature,secrets,infra. Only used with --scan-content.",
)
@click.option(
    "--visual-signature/--no-visual-signature", default=False,
    help="EXPERIMENTAL, independent of --scan-content: also look for handwritten-signature-shaped "
    "ink in rasterized page images (catches a wet signature with no text layer at all). Off by "
    "default — heuristic with a real false-positive rate, unmaintained upstream, slow (well over a "
    "minute per document on some real PDFs), and needs pip install 'metascout[visual-signature]' "
    "PLUS ImageMagick and Ghostscript installed system-wide. To run this later instead of inline, "
    "see `metascout visual-signature-scan`.",
)
@click.option(
    "--critical-files/--no-critical-files", default=False,
    help="Also run a second, independent discovery pass looking for plaintext/config-style "
    "'critical' files (see --critical-file-types) — an exposed .env, a debug .log, a forgotten "
    ".sql/.bak dump. Listed in their own report section: being publicly indexed is itself the "
    "finding. Combine with --scan-content to also run the secrets/PII scan on whatever text they "
    "contain, the same as any other document. Off by default.",
)
@click.option(
    "--critical-file-types", default=",".join(DEFAULT_CRITICAL_FILETYPES), show_default=True,
    help="Comma-separated file extensions for --critical-files.",
)
def scan(
    targets: tuple[str, ...], targets_file: str | None, urls_file: str | None, filetypes: str, engines: str, ddgs_backend: str, max_docs: int,
    max_crawl_pages: int, max_crawl_depth: int, concurrency: int, timeout: int, max_download_mb: int,
    output_dir: str, ignore_robots: bool, subdomains: bool, max_subdomains: int,
    google_api_key: str | None, google_cse_id: str | None, serper_api_key: str | None,
    brave_api_key: str | None, json_report: bool, html_report: bool, report_lang: str,
    scan_content: bool, content_categories: str, visual_signature: bool,
    critical_files: bool, critical_file_types: str,
) -> None:
    """Discover documents across one or more TARGETS and extract/analyze their metadata.

    TARGETS are one or more domains or base URLs, e.g.:

        metascout scan example.com example.org another-example.net

    Or read from a file (one per line) with --targets-file. All targets are
    scanned and merged into a single report.

    TARGETS/--targets-file can be omitted if --urls-file is given instead —
    the hostnames of those URLs are then used as the targets automatically.

    Only run this against sites you are authorized to test.
    """
    all_targets = _collect_targets(targets, targets_file)
    manual_urls = _collect_urls(urls_file)
    if not all_targets:
        all_targets = hosts_of(manual_urls)
    if not all_targets:
        raise click.UsageError("Provide at least one TARGET, --targets-file, or --urls-file with valid URLs.")

    cfg = ScanConfig(
        targets=all_targets,
        manual_urls=manual_urls,
        filetypes=[f.strip().lower().lstrip(".") for f in filetypes.split(",") if f.strip()],
        engines=[e.strip().lower() for e in engines.split(",") if e.strip()],
        ddgs_backend=ddgs_backend,
        max_docs=max_docs,
        max_crawl_pages=max_crawl_pages,
        max_crawl_depth=max_crawl_depth,
        concurrency=concurrency,
        request_timeout=timeout,
        max_download_bytes=max_download_mb * 1024 * 1024,
        output_dir=output_dir,
        respect_robots=not ignore_robots,
        include_subdomains=subdomains,
        max_subdomains=max_subdomains,
        google_api_key=google_api_key,
        google_cse_id=google_cse_id,
        serper_api_key=serper_api_key,
        brave_api_key=brave_api_key,
        scan_content=scan_content,
        content_categories=[c.strip().lower() for c in content_categories.split(",") if c.strip()],
        visual_signature=visual_signature,
        critical_files=critical_files,
        critical_file_types=[f.strip().lower().lstrip(".") for f in critical_file_types.split(",") if f.strip()],
    )

    _print_banner()
    console.print(f"[bold]MetaScout[/bold] scanning [bold]{', '.join(cfg.targets)}[/bold]")
    console.print("[dim]Only run against targets you are authorized to test.[/dim]\n")

    try:
        findings = run_scan(cfg, log=_cli_log)
    except RuntimeError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        sys.exit(1)

    if not findings.documents and not findings.critical_files:
        console.print("[yellow]No documents discovered. Nothing to analyze.[/yellow]")
        sys.exit(0)

    console.print()
    _print_summary(findings)

    if json_report:
        json_path = os.path.join(cfg.output_dir, "report.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            fh.write(render_json_report(findings))
        console.print(f"\n[green]JSON report:[/green] {json_path}")

    if html_report:
        html_path = os.path.join(cfg.output_dir, "report.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(render_html_report(findings, lang=report_lang))
        console.print(f"[green]HTML report:[/green] {html_path}")


@main.command("visual-signature-scan")
@click.argument("report_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--json-out", type=click.Path(), default=None, help="Where to write the results JSON. Defaults to REPORT_DIR/visual_signature_report.json.")
def visual_signature_scan(report_dir: str, json_out: str | None) -> None:
    """Run the slow, EXPERIMENTAL, image-based (wet) signature check against
    documents from a previous `metascout scan` run, without re-discovering
    or re-downloading anything.

    REPORT_DIR is a scan's output directory (the one containing
    report.json) — e.g. `./metascout_output` or a specific
    `web-YYYYMMDD-HHMMSS` run folder from the web UI.

    This is the same check `metascout scan --visual-signature` runs inline,
    split out on its own because it's genuinely slow (live-tested: anywhere
    from under a second to over two minutes per document, dominated by
    Ghostscript PDF rasterization) — most people won't want that blocking a
    regular scan. Run a normal scan first, then come back and run this
    separately, later, only on the documents you actually want checked.

    Requires: `pip install 'metascout[visual-signature]'` plus ImageMagick
    and Ghostscript installed system-wide (not just the pip package).
    """
    from .content_scan import missing_dependencies
    from .models import DocumentMetadata
    from .pipeline import scan_visual_signatures

    report_path = os.path.join(report_dir, "report.json")
    if not os.path.isfile(report_path):
        raise click.UsageError(f"No report.json found in {report_dir!r} — point this at a `metascout scan` output directory.")

    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)

    doc_metadata = [
        DocumentMetadata(url=d["url"], local_path=d.get("local_path") or "", filetype=d["filetype"], error=d.get("error"))
        for d in report.get("documents", [])
    ]
    doc_metadata = [d for d in doc_metadata if not d.error and d.local_path and os.path.isfile(d.local_path)]

    _print_banner()
    console.print("[bold yellow]EXPERIMENTAL:[/bold yellow] heuristic image analysis with a real false-positive rate — verify every hit manually.")
    console.print("[dim]This can take from under a second to well over a minute PER document.[/dim]\n")

    if missing_dependencies(set(), visual_signature=True):
        console.print(
            "[bold red]signature-detect is not installed[/bold red] — run "
            "[bold]pip install 'metascout[visual-signature]'[/bold] (plus ImageMagick and Ghostscript) first."
        )
        sys.exit(1)

    if not doc_metadata:
        console.print("[yellow]No downloaded, error-free documents with a local file found in this report. Nothing to scan.[/yellow]")
        sys.exit(0)

    console.print(f"[bold]{len(doc_metadata)}[/bold] document(s) to check ...\n")
    hits = scan_visual_signatures(doc_metadata, log=_cli_log)

    table = Table(title="Visual signature scan results (experimental)")
    table.add_column("Document")
    table.add_column("Visual signature?", justify="center")
    hit_urls = {h.document_url for h in hits}
    for doc in doc_metadata:
        table.add_row(doc.url, "[bold red]yes[/bold red]" if doc.url in hit_urls else "no")
    console.print(table)

    out_path = json_out or os.path.join(report_dir, "visual_signature_report.json")
    payload = [
        {"url": doc.url, "filetype": doc.filetype, "visual_signature_detected": doc.url in hit_urls}
        for doc in doc_metadata
    ]
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    console.print(f"\n[green]Results:[/green] {out_path}")


@main.command("local-scan")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--filetypes", default=",".join(DEFAULT_FILETYPES), show_default=True, help="Comma-separated list of file extensions to look for in DIRECTORY.")
@click.option("--scan-content/--no-scan-content", default=False, help="Also scan document body text for PII (see --content-categories). Requires pip install 'metascout[content-scan]'.")
@click.option("--content-categories", default=",".join(DEFAULT_CONTENT_CATEGORIES), show_default=True, help="Comma-separated subset of: tc_kimlik,email_phone,iban_card,address_dob,signature,secrets,infra. Only used with --scan-content.")
@click.option("--visual-signature/--no-visual-signature", default=False, help="EXPERIMENTAL: also run the slow, heuristic, image-based signature check. Requires pip install 'metascout[visual-signature]' plus ImageMagick and Ghostscript installed system-wide.")
@click.option("--critical-files/--no-critical-files", default=False, help="Also separately list plaintext/config-style 'critical' files found in DIRECTORY (see --critical-file-types) in their own report section. Combine with --scan-content to also run the secrets/PII scan on them.")
@click.option("--critical-file-types", default=",".join(DEFAULT_CRITICAL_FILETYPES), show_default=True, help="Comma-separated file extensions for --critical-files.")
@click.option("--json-report/--no-json-report", default=True)
@click.option("--html-report/--no-html-report", default=True)
@click.option("--report-lang", type=click.Choice(["en", "tr"]), default="en", show_default=True)
@click.option("--output-dir", default="./metascout_output", show_default=True, type=click.Path())
def local_scan(
    directory: str, filetypes: str, scan_content: bool, content_categories: str,
    visual_signature: bool, critical_files: bool, critical_file_types: str,
    json_report: bool, html_report: bool, report_lang: str, output_dir: str,
) -> None:
    """Analyze documents already sitting in DIRECTORY — no discovery, no
    download, just metadata extraction plus whichever optional checks you
    ask for (--scan-content, --visual-signature).

    For a folder of documents you already have (your own files, or ones
    gathered by some other means) that you just want run through
    MetaScout's analysis, without pointing it at a live target.
    """
    from .pipeline import run_local_document_scan

    cfg_categories = [c.strip().lower() for c in content_categories.split(",") if c.strip()]
    ft_list = [f.strip().lower().lstrip(".") for f in filetypes.split(",") if f.strip()]
    critical_ft_list = [f.strip().lower().lstrip(".") for f in critical_file_types.split(",") if f.strip()]

    _print_banner()
    console.print(f"[bold]MetaScout[/bold] analyzing documents in [bold]{directory}[/bold]")

    try:
        findings = run_local_document_scan(
            directory, filetypes=ft_list, scan_content=scan_content,
            content_categories=cfg_categories, visual_signature=visual_signature,
            critical_files=critical_files, critical_file_types=critical_ft_list, log=_cli_log,
        )
    except RuntimeError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        sys.exit(1)

    if not findings.documents and not findings.critical_files:
        console.print("[yellow]No matching documents found. Nothing to analyze.[/yellow]")
        sys.exit(0)

    console.print()
    _print_summary(findings)

    os.makedirs(output_dir, exist_ok=True)
    if json_report:
        json_path = os.path.join(output_dir, "report.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            fh.write(render_json_report(findings))
        console.print(f"\n[green]JSON report:[/green] {json_path}")

    if html_report:
        html_path = os.path.join(output_dir, "report.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(render_html_report(findings, lang=report_lang))
        console.print(f"[green]HTML report:[/green] {html_path}")


@main.command()
@click.argument("run_a", type=click.Path(exists=True, file_okay=False))
@click.argument("run_b", type=click.Path(exists=True, file_okay=False))
@click.option("--json-out", type=click.Path(), default=None, help="Also write the full diff as JSON to this path.")
def diff(run_a: str, run_b: str, json_out: str | None) -> None:
    """Compares two scan output directories (each containing a report.json)
    and shows what changed between them: new/removed documents, new/removed
    metadata findings, new/removed content-scan hits, new/removed critical files.

    RUN_A is treated as the earlier scan, RUN_B the later one — "new" means
    "in RUN_B but not RUN_A". For tracking a target over time: run
    `metascout scan` (or `local-scan`) periodically into timestamped
    output directories, then diff any two of them.

        metascout diff metascout_output/web-20260101-100000 metascout_output/web-20260201-100000
    """
    from .diff import FINDING_CATEGORIES, diff_reports, has_changes

    def _load(run_dir: str) -> dict:
        path = os.path.join(run_dir, "report.json")
        if not os.path.isfile(path):
            raise click.UsageError(f"No report.json found in {run_dir!r} — point this at a scan's output directory.")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    report_a = _load(run_a)
    report_b = _load(run_b)
    result = diff_reports(report_a, report_b)

    _print_banner()
    console.print(f"[bold]Comparing[/bold] {run_a} [dim]->[/dim] {run_b}\n")

    if not has_changes(result):
        console.print("[green]No changes — the two reports are identical.[/green]")
    else:
        summary = Table(title="Diff summary")
        summary.add_column("Category")
        summary.add_column("New", justify="right")
        summary.add_column("Removed", justify="right")
        summary.add_row("Documents", str(len(result["documents"]["new"])), str(len(result["documents"]["removed"])))
        for cat in FINDING_CATEGORIES:
            r = result["findings"][cat]
            if r["new"] or r["removed"]:
                summary.add_row(cat.replace("_", " ").title(), str(len(r["new"])), str(len(r["removed"])))
        summary.add_row(
            "Content scan hits",
            str(len(result["content_findings"]["new"])),
            str(len(result["content_findings"]["removed"])),
        )
        summary.add_row(
            "Critical files",
            str(len(result["critical_files"]["new"])),
            str(len(result["critical_files"]["removed"])),
        )
        console.print(summary)

        if result["documents"]["new"]:
            console.print("\n[bold green]New documents:[/bold green]")
            for url in result["documents"]["new"]:
                console.print(f"  + {url}")

        if result["critical_files"]["new"]:
            console.print("\n[bold green]New critical files:[/bold green]")
            for url in result["critical_files"]["new"]:
                console.print(f"  + {url}")

        for cat in FINDING_CATEGORIES:
            r = result["findings"][cat]
            if r["new"]:
                console.print(f"\n[bold green]New {cat.replace('_', ' ')}:[/bold green]")
                for value in r["new"]:
                    console.print(f"  + {value}")

        if result["content_findings"]["new"]:
            console.print("\n[bold green]New content-scan hits (verify manually):[/bold green]")
            for f in result["content_findings"]["new"]:
                console.print(f"  + [{f.get('category')}] {f.get('masked_value')} — {f.get('document_url')}")

    if json_out:
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
        console.print(f"\n[green]Diff JSON:[/green] {json_out}")


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True)
@click.option("--output-dir", default="./metascout_output", show_default=True, type=click.Path())
@click.option("--open-browser/--no-open-browser", default=True, help="Automatically open the UI in your default browser.")
def web(host: str, port: int, output_dir: str, open_browser: bool) -> None:
    """Launch the local MetaScout web UI (scan form + report viewer)."""
    from .web import run_server

    _print_banner()
    console.print(f"[bold]MetaScout web UI[/bold] starting on [bold]http://{host}:{port}/[/bold]")
    console.print("[dim]Local only — do not expose this to the internet.[/dim]\n")
    run_server(host=host, port=port, output_dir=output_dir, open_browser=open_browser)


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Use 0.0.0.0 to accept connections from other machines — see the warning below first.")
@click.option("--port", default=8000, show_default=True)
@click.option("--output-dir", default="./metascout_output", show_default=True, type=click.Path(), help="Where each job's report.json/report.html/downloads get saved.")
@click.option("--max-workers", default=2, show_default=True, help="Maximum scans running at the same time; extra jobs queue and wait.")
@click.option("--max-pending", default=50, show_default=True, help="Maximum scans queued or running at once; POST /v1/scans returns 429 past this. Bounds memory use against an unauthenticated caller submitting jobs in a loop.")
def api(host: str, port: int, output_dir: str, max_workers: int, max_pending: int) -> None:
    """Launch the MetaScout REST API — a separate, job-based HTTP service
    for programmatic/enterprise integration: POST a scan, poll its status,
    then pull the JSON/HTML report or a zip once it's done. Interactive
    docs at http://HOST:PORT/docs once running.

    Requires the optional [api] extra: pip install 'metascout[api]'.
    """
    try:
        import uvicorn

        from .api import create_app
    except ImportError:
        console.print("[bold red]Missing dependency.[/bold red] Install the API extra first:")
        console.print("  pip install 'metascout[api]'")
        sys.exit(1)

    _print_banner()
    console.print(f"[bold]MetaScout API[/bold] starting on [bold]http://{host}:{port}/[/bold]  (docs: http://{host}:{port}/docs)")
    console.print("[dim]No built-in authentication — see the README before exposing this beyond a trusted machine/network.[/dim]\n")
    app = create_app(output_dir=output_dir, max_workers=max_workers, max_pending=max_pending)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
