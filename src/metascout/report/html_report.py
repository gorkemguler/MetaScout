from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import ScanFindings

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SUPPORTED_LANGS = {"en", "tr"}


def render_html_report(findings: ScanFindings, lang: str = "en", download_url: str | None = None) -> str:
    """Renders the HTML report. `download_url`, when given, adds a "Download
    results (.zip)" button in the header pointing at it — used by the web UI
    to offer the whole run directory (report.html/report.json/downloads/) as
    one zip; left unset (the CLI's usage) since there's no separate download
    step when you already have the output directory on disk.
    """
    if lang not in _SUPPORTED_LANGS:
        raise ValueError(f"Unsupported report language '{lang}', expected one of {sorted(_SUPPORTED_LANGS)}")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(f"report_{lang}.html.jinja")
    return template.render(findings=findings, download_url=download_url)
