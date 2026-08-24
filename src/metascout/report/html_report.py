from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import ScanFindings

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SUPPORTED_LANGS = {"en", "tr"}


def render_html_report(findings: ScanFindings, lang: str = "en") -> str:
    if lang not in _SUPPORTED_LANGS:
        raise ValueError(f"Unsupported report language '{lang}', expected one of {sorted(_SUPPORTED_LANGS)}")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(f"report_{lang}.html.jinja")
    return template.render(findings=findings)
