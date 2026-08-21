from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import ScanFindings

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_html_report(findings: ScanFindings) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.jinja")
    return template.render(findings=findings)
