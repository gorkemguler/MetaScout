from __future__ import annotations

import os
import sys

import click
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.table import Table

from .config import DEFAULT_FILETYPES, ScanConfig
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


def _default_engines() -> str:
    """crawl+sitemap always; auto-add google/serper/brave when their API keys
    are already configured (env var or .env), so setting up a key is enough
    to use it without also remembering to pass --engines.
    """
    engines = ["crawl", "sitemap"]
    if os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"):
        engines.append("google")
    if os.environ.get("SERPER_API_KEY"):
        engines.append("serper")
    if os.environ.get("BRAVE_API_KEY"):
        engines.append("brave")
    return ",".join(engines)


def _collect_targets(targets: tuple[str, ...], targets_file: str | None) -> list[str]:
    all_targets = list(targets)
    if targets_file:
        with open(targets_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    all_targets.append(line)
    return list(dict.fromkeys(t.strip() for t in all_targets if t.strip()))


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
@click.option("--filetypes", default=",".join(DEFAULT_FILETYPES), show_default=True, help="Comma-separated list of file extensions.")
@click.option("--engines", default=_default_engines, help="Comma-separated: crawl,sitemap,google,serper,brave. Defaults to crawl,sitemap plus google/serper/brave automatically if their API keys are set.")
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
def scan(
    targets: tuple[str, ...], targets_file: str | None, filetypes: str, engines: str, max_docs: int,
    max_crawl_pages: int, max_crawl_depth: int, concurrency: int, timeout: int, max_download_mb: int,
    output_dir: str, ignore_robots: bool, subdomains: bool, max_subdomains: int,
    google_api_key: str | None, google_cse_id: str | None, serper_api_key: str | None,
    brave_api_key: str | None, json_report: bool, html_report: bool,
) -> None:
    """Discover documents across one or more TARGETS and extract/analyze their metadata.

    TARGETS are one or more domains or base URLs, e.g.:

        metascout scan example.com example.org another-example.net

    Or read from a file (one per line) with --targets-file. All targets are
    scanned and merged into a single report.

    Only run this against sites you are authorized to test.
    """
    all_targets = _collect_targets(targets, targets_file)
    if not all_targets:
        raise click.UsageError("Provide at least one TARGET or --targets-file.")

    cfg = ScanConfig(
        targets=all_targets,
        filetypes=[f.strip().lower().lstrip(".") for f in filetypes.split(",") if f.strip()],
        engines=[e.strip().lower() for e in engines.split(",") if e.strip()],
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
    )

    _print_banner()
    console.print(f"[bold]MetaScout[/bold] scanning [bold]{', '.join(cfg.targets)}[/bold]")
    console.print("[dim]Only run against targets you are authorized to test.[/dim]\n")

    try:
        findings = run_scan(cfg, log=_cli_log)
    except RuntimeError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        sys.exit(1)

    if not findings.documents:
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
            fh.write(render_html_report(findings))
        console.print(f"[green]HTML report:[/green] {html_path}")


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


if __name__ == "__main__":
    main()
