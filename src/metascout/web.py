from __future__ import annotations

import os
import webbrowser
from datetime import datetime

from flask import Flask, request

from .config import DEFAULT_FILETYPES, ScanConfig
from .metadata import exiftool_available
from .pipeline import run_scan
from .report import render_html_report, render_json_report

_PAGE_HEAD = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MetaScout</title>
<style>
  :root {
    --bg: #0f1117; --panel: #161925; --border: #2a2f42; --text: #e6e8f0;
    --muted: #9aa1b4; --accent: #6ea8fe; --warn: #f2a65a; --bad: #f26d6d;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, Segoe UI, Roboto, sans-serif; }
  header { padding: 28px 40px; border-bottom: 1px solid var(--border); }
  header h1 { margin: 0 0 4px; font-size: 20px; }
  header .meta { color: var(--muted); font-size: 13px; }
  main { padding: 24px 40px 60px; max-width: 760px; margin: 0 auto; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 24px; margin-bottom: 20px; }
  label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; margin-top: 16px; }
  label:first-of-type { margin-top: 0; }
  textarea, input[type=text], input[type=number] {
    width: 100%; background: #0f1117; border: 1px solid var(--border); border-radius: 8px;
    color: var(--text); padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px;
  }
  textarea { resize: vertical; min-height: 90px; }
  .row { display: flex; gap: 16px; flex-wrap: wrap; }
  .row > div { flex: 1; min-width: 160px; }
  .checks { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 8px; }
  .checks label { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; color: var(--text); }
  .hint { color: var(--muted); font-size: 12px; margin-top: 6px; }
  button { background: var(--accent); color: #0f1117; border: none; border-radius: 8px; padding: 12px 20px;
    font-size: 14px; font-weight: 700; cursor: pointer; margin-top: 24px; }
  button:hover { opacity: 0.9; }
  button:disabled { opacity: 0.6; cursor: wait; }
  .scanning { display: none; align-items: center; gap: 10px; margin-top: 16px; color: var(--accent); font-size: 13px; }
  .scanning.active { display: flex; }
  .spinner { width: 16px; height: 16px; border: 2px solid rgba(110,168,254,0.25); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .banner { color: #8bb4ff; font-weight: 800; font-size: 22px; }
  .error { background: rgba(242,109,109,0.1); border: 1px solid var(--bad); color: var(--bad);
    border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; }
  .warn { background: rgba(242,166,90,0.1); border: 1px solid var(--warn); color: var(--warn);
    border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; }
  a { color: var(--accent); }
</style>
</head>
<body>
<header>
  <div class="banner">MetaScout</div>
  <div class="meta">Document discovery &amp; metadata reconnaissance — local web UI</div>
</header>
<main>
"""

_PAGE_TAIL = """
</main>
</body>
</html>
"""

_FORM_BODY = """
{error_block}
{exiftool_block}
<form class="card" method="post" action="/scan" onsubmit="document.getElementById('submit-btn').disabled=true;document.getElementById('submit-btn').textContent='Taranıyor…';document.getElementById('scanning').className='scanning active';">
  <label for="targets">Hedefler (her satıra bir tane, domain veya URL)</label>
  <textarea id="targets" name="targets" placeholder="example.com&#10;example.org&#10;another-example.net" required>{targets_value}</textarea>
  <div class="hint">Bir kuruma ait birden fazla domaini aynı anda tarayıp tek raporda birleştirebilirsiniz.</div>

  <label for="filetypes">Dosya uzantıları</label>
  <input type="text" id="filetypes" name="filetypes" value="{filetypes_value}">

  <label>Keşif motorları</label>
  <div class="checks">
    <label><input type="checkbox" name="engines" value="crawl" checked> crawl</label>
    <label><input type="checkbox" name="engines" value="sitemap" checked> sitemap</label>
    <label><input type="checkbox" name="engines" value="google" {google_checked}> google{google_hint}</label>
    <label><input type="checkbox" name="engines" value="serper" {serper_checked}> serper{serper_hint}</label>
    <label><input type="checkbox" name="engines" value="brave" {brave_checked}> brave{brave_hint}</label>
  </div>
  <div class="hint">google/serper/brave için ilgili API anahtarları ortam değişkeni ya da .env üzerinden tanımlı olmalı; anahtar bulunduğunda kutucuk otomatik işaretlenir.
  Google, Custom Search API'yi 1 Ocak 2027'de kapatıyor ve yeni Google Cloud projelerini şimdiden reddediyor —
  sorun yaşarsanız <a href="https://serper.dev" target="_blank" rel="noopener">serper.dev</a>'i deneyin (ücretsiz kredi var, güncel miktarı sitede kontrol edin).</div>

  <label><input type="checkbox" name="subdomains"> Subdomain keşfi (crt.sh)</label>

  <div class="row">
    <div>
      <label for="max_docs">Azami belge sayısı</label>
      <input type="number" id="max_docs" name="max_docs" value="30" min="1" max="100000">
    </div>
    <div>
      <label for="max_crawl_pages">Host başına azami sayfa</label>
      <input type="number" id="max_crawl_pages" name="max_crawl_pages" value="100" min="1" max="100000">
    </div>
  </div>
  <div class="hint">"Her şeyi tara" istiyorsanız ikisini de yüksek tutun (ör. 50000) — ama büyük
  sitelerde tarama çok uzun sürebilir ve sayfa taramayı bitirene kadar açık kalmalıdır.
  Gerçekten büyük/kapsamlı bir tarama için tarayıcı yerine terminalden <code>metascout scan</code>
  kullanmak daha güvenlidir (bkz. README).</div>

  <button type="submit" id="submit-btn">Taramayı başlat</button>
  <div class="scanning" id="scanning"><div class="spinner"></div> Tarama çalışıyor, bu sekmeyi kapatmayın — ilerlemeyi <code>metascout web</code> komutunu çalıştırdığınız terminalden takip edebilirsiniz.</div>
  <div class="hint">Bu işlem hedef sayısına ve belge miktarına göre birkaç dakika (büyük taramalarda
  saatler) sürebilir; sayfa tarama bitene kadar bekleyecektir.</div>
</form>
"""


def _render_form(error: str | None = None, targets_value: str = "", filetypes_value: str | None = None) -> str:
    error_block = f'<div class="error">{error}</div>' if error else ""
    exiftool_block = (
        ""
        if exiftool_available()
        else '<div class="warn">exiftool bulunamadı — kurmadan tarama çalışmaz. README\'deki kurulum adımlarına bakın.</div>'
    )
    google_ready = bool(os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"))
    serper_ready = bool(os.environ.get("SERPER_API_KEY"))
    brave_ready = bool(os.environ.get("BRAVE_API_KEY"))
    body = _FORM_BODY.format(
        error_block=error_block,
        exiftool_block=exiftool_block,
        targets_value=targets_value,
        filetypes_value=filetypes_value or ",".join(DEFAULT_FILETYPES),
        google_checked="checked" if google_ready else "",
        serper_checked="checked" if serper_ready else "",
        brave_checked="checked" if brave_ready else "",
        google_hint=" (anahtar bulundu)" if google_ready else "",
        serper_hint=" (anahtar bulundu)" if serper_ready else "",
        brave_hint=" (anahtar bulundu)" if brave_ready else "",
    )
    return _PAGE_HEAD + body + _PAGE_TAIL


def create_app(output_dir: str = "./metascout_output") -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return _render_form()

    @app.post("/scan")
    def scan():
        raw_targets = request.form.get("targets", "")
        targets = [t.strip() for t in raw_targets.replace(",", "\n").splitlines() if t.strip()]
        if not targets:
            return _render_form(error="En az bir hedef girin."), 400

        filetypes_value = request.form.get("filetypes", ",".join(DEFAULT_FILETYPES))
        filetypes = [f.strip().lower().lstrip(".") for f in filetypes_value.split(",") if f.strip()]
        engines = request.form.getlist("engines") or ["crawl", "sitemap"]
        subdomains = request.form.get("subdomains") == "on"
        try:
            max_docs = max(1, int(request.form.get("max_docs") or 30))
            max_crawl_pages = max(1, int(request.form.get("max_crawl_pages") or 100))
        except ValueError:
            return _render_form(error="Sayısal alanlar geçersiz.", targets_value=raw_targets, filetypes_value=filetypes_value), 400

        run_dir = os.path.join(output_dir, "web-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        cfg = ScanConfig(
            targets=targets,
            filetypes=filetypes,
            engines=engines,
            max_docs=max_docs,
            max_crawl_pages=max_crawl_pages,
            output_dir=run_dir,
            include_subdomains=subdomains,
            google_api_key=os.environ.get("GOOGLE_API_KEY"),
            google_cse_id=os.environ.get("GOOGLE_CSE_ID"),
            serper_api_key=os.environ.get("SERPER_API_KEY"),
            brave_api_key=os.environ.get("BRAVE_API_KEY"),
        )

        def _log(message: str) -> None:
            print(f"[metascout web] {message}", flush=True)

        _log(f"scan started: targets={targets} engines={engines} max_docs={max_docs} max_crawl_pages={max_crawl_pages}")
        try:
            findings = run_scan(cfg, log=_log)
        except RuntimeError as exc:
            return _render_form(error=str(exc), targets_value=raw_targets, filetypes_value=filetypes_value), 500

        os.makedirs(run_dir, exist_ok=True)
        html = render_html_report(findings)
        with open(os.path.join(run_dir, "report.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
            fh.write(render_json_report(findings))

        _log(f"scan finished: {len(findings.documents)} document(s), report saved to {run_dir}")
        return html

    return app


def run_server(host: str = "127.0.0.1", port: int = 8765, output_dir: str = "./metascout_output", open_browser: bool = True) -> None:
    app = create_app(output_dir=output_dir)
    url = f"http://{host}:{port}/"
    if open_browser:
        webbrowser.open(url)
    app.run(host=host, port=port, debug=False, threaded=True)
