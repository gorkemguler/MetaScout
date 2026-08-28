from __future__ import annotations

import os
import webbrowser
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, request

from .config import DEFAULT_CONTENT_CATEGORIES, DEFAULT_FILETYPES, ScanConfig
from .metadata import exiftool_available
from .pipeline import run_scan
from .report import render_html_report, render_json_report

_STRINGS = {
    "en": {
        "tagline": "Document discovery &amp; metadata reconnaissance — local web UI",
        "targets_label": "Targets (one per line, domain or URL)",
        "targets_hint": "Scan several domains belonging to one organization at once and merge "
                         "them into a single report. Leave this empty if you filled in the manual "
                         "URL list below — the target is derived automatically.",
        "manual_toggle": "+ Add a manual URL list (optional)",
        "manual_label": "One full document URL per line",
        "manual_hint": "Paste links here if an engine didn't work for you, or you gathered them by "
                        "hand — discovery is skipped for these, they're downloaded, analyzed, and "
                        "added to the report directly. A URL already found by discovery won't be "
                        "added twice.",
        "filetypes_label": "File extensions",
        "engines_label": "Discovery engines",
        "engines_hint": "google/serper/brave need their matching API key set via environment "
                         "variable or .env; the checkbox is checked automatically once a key is "
                         "found. Google is discontinuing its Custom Search API on 2027-01-01 and "
                         "already rejects new Google Cloud projects — try "
                         '<a href="https://serper.dev" target="_blank" rel="noopener">serper.dev</a> '
                         "instead if you run into that (free credit included, check the site for "
                         "the current amount), or set the DDGS backend below to <code>google</code> "
                         "for a keyless option.",
        "ddgs_hint": "'ddgs' needs no key at all — it scrapes DuckDuckGo (and, with 'auto', falls "
                     "back across other engines) directly, so it's the most fragile option here and "
                     "can get rate-limited under heavy use. On by default since it's reliable in "
                     "practice; uncheck it if you'd rather not depend on a scraper.",
        "ddgs_backend_label": "DDGS backend",
        "ddgs_backend_hint": "Which engine(s) 'ddgs' scrapes. Default 'auto' falls back across "
                              "several; set a specific one like <code>google</code>, "
                              "<code>duckduckgo</code>, or <code>bing</code>, or a comma-separated "
                              "list to try in order.",
        "subdomains_label": "Subdomain enumeration (crt.sh)",
        "content_scan_label": "Scan document content for personal/critical data (PII)",
        "content_scan_hint": "Off by default. Goes beyond metadata tags and reads each document's "
                              "actual body text for national ID numbers, emails/phones, IBANs/card "
                              "numbers, address/DOB hints, and signature hints. Heuristic — every hit "
                              "needs manual verification, not a confirmed leak. Requires the optional "
                              "extra on the machine running the scan: "
                              "<code>pip install 'metascout[content-scan]'</code>.",
        "content_categories_label": "Categories",
        "cat_tc_kimlik": "TR national ID no. (checksum-verified)",
        "cat_email_phone": "Emails / phone numbers",
        "cat_iban_card": "IBAN / credit card no. (checksum-verified)",
        "cat_address_dob": "Address / date-of-birth hints (weak signal)",
        "cat_signature": "Signature hints (keyword + PDF digital signature)",
        "report_lang_label": "Report language",
        "max_docs_label": "Maximum documents",
        "max_crawl_pages_label": "Max pages per host",
        "limits_hint": 'For "scan everything," set both high (e.g. 50000) — but large sites can '
                        "take a long time and the page must stay open until scanning finishes. For "
                        "a genuinely large/thorough scan, running <code>metascout scan</code> from "
                        "a terminal is more reliable than the browser (see the README).",
        "submit_label": "Start scan",
        "submit_loading_label": "Scanning…",
        "scanning_hint": "The scan is running, don't close this tab — you can follow progress from "
                          "the terminal where you ran <code>metascout web</code>.",
        "footer_hint": "This can take a few minutes (hours for large scans) depending on the number "
                        "of targets and documents; the page will wait until scanning finishes.",
        "error_no_target": "Provide at least one target or a valid manual URL.",
        "error_invalid_numbers": "Numeric fields are invalid.",
        "exiftool_warning": "exiftool not found — install it before scanning. See the README "
                             "installation steps.",
    },
    "tr": {
        "tagline": "Belge keşfi &amp; metadata sızıntı analizi — yerel web arayüzü",
        "targets_label": "Hedefler (her satıra bir tane, domain veya URL)",
        "targets_hint": "Bir kuruma ait birden fazla domaini aynı anda tarayıp tek raporda "
                         "birleştirebilirsiniz. Aşağıya manuel URL listesi girdiyseniz burayı boş "
                         "bırakabilirsiniz — hedef otomatik çıkarılır.",
        "manual_toggle": "+ Manuel URL listesi ekle (opsiyonel)",
        "manual_label": "Her satıra bir tam belge URL'i",
        "manual_hint": "Bir motor çalışmadıysa ya da elle topladığınız linkleriniz varsa buraya "
                        "yapıştırın — keşif motorlarını atlayıp bu URL'ler doğrudan indirilip "
                        "analiz edilir ve rapora eklenir. Keşifle bulunan bir belgeyle aynı URL "
                        "ise tekrar eklenmez.",
        "filetypes_label": "Dosya uzantıları",
        "engines_label": "Keşif motorları",
        "engines_hint": "google/serper/brave için ilgili API anahtarları ortam değişkeni ya da "
                         ".env üzerinden tanımlı olmalı; anahtar bulunduğunda kutucuk otomatik "
                         "işaretlenir. Google, Custom Search API'yi 1 Ocak 2027'de kapatıyor ve "
                         "yeni Google Cloud projelerini şimdiden reddediyor — sorun yaşarsanız "
                         '<a href="https://serper.dev" target="_blank" rel="noopener">serper.dev</a>'
                         "'i deneyin (ücretsiz kredi var, güncel miktarı sitede kontrol edin), ya da "
                         "anahtarsız bir seçenek için aşağıdaki DDGS motorunu <code>google</code> "
                         "olarak ayarlayın.",
        "ddgs_hint": "'ddgs' hiçbir anahtar gerektirmez — doğrudan DuckDuckGo'yu (ve 'auto' modunda "
                     "yedek olarak diğer motorları) kazır, bu yüzden buradaki en kırılgan seçenektir "
                     "ve yoğun kullanımda hız sınırına takılabilir. Pratikte güvenilir olduğu için "
                     "varsayılan açık; bir kazıyıcıya bağımlı olmak istemiyorsanız işaretini kaldırın.",
        "ddgs_backend_label": "DDGS motoru",
        "ddgs_backend_hint": "'ddgs'in hangi motor(lar)ı kazıyacağı. Varsayılan 'auto' birkaç "
                              "motor arasında yedeklemeli dener; <code>google</code>, "
                              "<code>duckduckgo</code>, <code>bing</code> gibi belirli birini ya "
                              "da sırayla denenecek virgülle ayrılmış bir liste girebilirsiniz.",
        "subdomains_label": "Subdomain keşfi (crt.sh)",
        "content_scan_label": "Belge içeriğinde kişisel/kritik veri taraması (PII)",
        "content_scan_hint": "Varsayılan kapalı. Metadata etiketlerinin ötesine geçip her belgenin "
                              "gövde metnini TC kimlik no, e-posta/telefon, IBAN/kredi kartı no, "
                              "adres/doğum tarihi ipuçları ve imza ipuçları için tarar. Sezgisel bir "
                              "taramadır — her bulgu kesin bir sızıntı değil, elle doğrulanmalıdır. "
                              "Taramayı çalıştıran makinede opsiyonel ek paket gerektirir: "
                              "<code>pip install 'metascout[content-scan]'</code>.",
        "content_categories_label": "Kategoriler",
        "cat_tc_kimlik": "TC Kimlik No (checksum doğrulamalı)",
        "cat_email_phone": "E-posta / telefon numaraları",
        "cat_iban_card": "IBAN / kredi kartı no (checksum doğrulamalı)",
        "cat_address_dob": "Adres / doğum tarihi ipuçları (zayıf sinyal)",
        "cat_signature": "İmza ipuçları (anahtar kelime + PDF dijital imza)",
        "report_lang_label": "Rapor dili",
        "max_docs_label": "Azami belge sayısı",
        "max_crawl_pages_label": "Host başına azami sayfa",
        "limits_hint": '"Her şeyi tara" istiyorsanız ikisini de yüksek tutun (ör. 50000) — ama '
                        "büyük sitelerde tarama çok uzun sürebilir ve sayfa taramayı bitirene kadar "
                        "açık kalmalıdır. Gerçekten büyük/kapsamlı bir tarama için tarayıcı yerine "
                        "terminalden <code>metascout scan</code> kullanmak daha güvenlidir (bkz. "
                        "README).",
        "submit_label": "Taramayı başlat",
        "submit_loading_label": "Taranıyor…",
        "scanning_hint": "Tarama çalışıyor, bu sekmeyi kapatmayın — ilerlemeyi "
                          "<code>metascout web</code> komutunu çalıştırdığınız terminalden takip "
                          "edebilirsiniz.",
        "footer_hint": "Bu işlem hedef sayısına ve belge miktarına göre birkaç dakika (büyük "
                        "taramalarda saatler) sürebilir; sayfa tarama bitene kadar bekleyecektir.",
        "error_no_target": "En az bir hedef ya da geçerli bir manuel URL girin.",
        "error_invalid_numbers": "Sayısal alanlar geçersiz.",
        "exiftool_warning": "exiftool bulunamadı — kurmadan tarama çalışmaz. README'deki kurulum "
                             "adımlarına bakın.",
    },
}


def _t(ui_lang: str, key: str) -> str:
    return _STRINGS.get(ui_lang, _STRINGS["en"])[key]


_PAGE_HEAD = """<!DOCTYPE html>
<html lang="{ui_lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MetaScout</title>
<style>
  :root {{
    --bg: #0f1117; --panel: #161925; --border: #2a2f42; --text: #e6e8f0;
    --muted: #9aa1b4; --accent: #6ea8fe; --warn: #f2a65a; --bad: #f26d6d;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, Segoe UI, Roboto, sans-serif; }}
  header {{ padding: 28px 40px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }}
  header h1 {{ margin: 0 0 4px; font-size: 20px; }}
  header .meta {{ color: var(--muted); font-size: 13px; }}
  .lang-switch {{ display: flex; gap: 8px; font-size: 12px; font-weight: 700; flex-shrink: 0; }}
  .lang-switch a {{ color: var(--muted); text-decoration: none; padding: 4px 10px; border: 1px solid var(--border); border-radius: 999px; }}
  .lang-switch a.active {{ color: var(--bg); background: var(--accent); border-color: var(--accent); }}
  .lang-switch a:hover:not(.active) {{ color: var(--text); border-color: var(--muted); }}
  main {{ padding: 24px 40px 60px; max-width: 760px; margin: 0 auto; }}
  .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 24px; margin-bottom: 20px; }}
  label {{ display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; margin-top: 16px; }}
  label:first-of-type {{ margin-top: 0; }}
  textarea, input[type=text], input[type=number] {{
    width: 100%; background: #0f1117; border: 1px solid var(--border); border-radius: 8px;
    color: var(--text); padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px;
  }}
  textarea {{ resize: vertical; min-height: 90px; }}
  .row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .row > div {{ flex: 1; min-width: 160px; }}
  .checks {{ display: flex; gap: 18px; flex-wrap: wrap; margin-top: 8px; }}
  .checks label {{ display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; color: var(--text); }}
  .hint {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
  details.manual-urls {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; }}
  details.manual-urls[open] {{ padding-bottom: 16px; }}
  details.manual-urls summary {{
    cursor: pointer; font-size: 13px; color: var(--accent); font-weight: 600;
    list-style: none; user-select: none;
  }}
  details.manual-urls summary::-webkit-details-marker {{ display: none; }}
  details.manual-urls[open] summary {{ margin-bottom: 4px; }}
  button {{ background: var(--accent); color: #0f1117; border: none; border-radius: 8px; padding: 12px 20px;
    font-size: 14px; font-weight: 700; cursor: pointer; margin-top: 24px; }}
  button:hover {{ opacity: 0.9; }}
  button:disabled {{ opacity: 0.6; cursor: wait; }}
  .scanning {{ display: none; align-items: center; gap: 10px; margin-top: 16px; color: var(--accent); font-size: 13px; }}
  .scanning.active {{ display: flex; }}
  .spinner {{ width: 16px; height: 16px; border: 2px solid rgba(110,168,254,0.25); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.8s linear infinite; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .banner {{ color: #8bb4ff; font-weight: 800; font-size: 22px; }}
  .error {{ background: rgba(242,109,109,0.1); border: 1px solid var(--bad); color: var(--bad);
    border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; }}
  .warn {{ background: rgba(242,166,90,0.1); border: 1px solid var(--warn); color: var(--warn);
    border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <div>
    <div class="banner">MetaScout</div>
    <div class="meta">{tagline}</div>
  </div>
  <div class="lang-switch">
    <a href="/?lang=en" class="{en_active}">EN</a>
    <a href="/?lang=tr" class="{tr_active}">TR</a>
  </div>
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
<form class="card" method="post" action="/scan" onsubmit="document.getElementById('submit-btn').disabled=true;document.getElementById('submit-btn').textContent='{submit_loading_label}';document.getElementById('scanning').className='scanning active';">
  <input type="hidden" name="ui_lang" value="{ui_lang}">
  <label for="targets">{targets_label}</label>
  <textarea id="targets" name="targets" placeholder="example.com&#10;example.org&#10;another-example.net">{targets_value}</textarea>
  <div class="hint">{targets_hint}</div>

  <details class="manual-urls"{manual_urls_open}>
    <summary>{manual_toggle}</summary>
    <label for="manual_urls">{manual_label}</label>
    <textarea id="manual_urls" name="manual_urls" placeholder="https://example.com/reports/2023.pdf&#10;https://example.com/files/notes.docx">{manual_urls_value}</textarea>
    <div class="hint">{manual_hint}</div>
  </details>

  <label for="filetypes">{filetypes_label}</label>
  <input type="text" id="filetypes" name="filetypes" value="{filetypes_value}">

  <label>{engines_label}</label>
  <div class="checks">
    <label><input type="checkbox" name="engines" value="crawl" checked> crawl</label>
    <label><input type="checkbox" name="engines" value="sitemap" checked> sitemap</label>
    <label><input type="checkbox" name="engines" value="wayback" checked> wayback</label>
    <label><input type="checkbox" name="engines" value="google" {google_checked}> google{google_hint}</label>
    <label><input type="checkbox" name="engines" value="serper" {serper_checked}> serper{serper_hint}</label>
    <label><input type="checkbox" name="engines" value="brave" {brave_checked}> brave{brave_hint}</label>
    <label><input type="checkbox" name="engines" value="ddgs" checked> ddgs</label>
  </div>
  <div class="hint">{engines_hint}</div>
  <div class="hint">{ddgs_hint}</div>

  <label for="ddgs_backend">{ddgs_backend_label}</label>
  <input type="text" id="ddgs_backend" name="ddgs_backend" value="{ddgs_backend_value}" placeholder="auto">
  <div class="hint">{ddgs_backend_hint}</div>

  <label><input type="checkbox" name="subdomains"> {subdomains_label}</label>

  <label><input type="checkbox" name="scan_content" id="scan_content"> {content_scan_label}</label>
  <div class="hint">{content_scan_hint}</div>
  <label>{content_categories_label}</label>
  <div class="checks">
    <label><input type="checkbox" name="content_categories" value="tc_kimlik" checked> {cat_tc_kimlik}</label>
    <label><input type="checkbox" name="content_categories" value="email_phone" checked> {cat_email_phone}</label>
    <label><input type="checkbox" name="content_categories" value="iban_card" checked> {cat_iban_card}</label>
    <label><input type="checkbox" name="content_categories" value="address_dob" checked> {cat_address_dob}</label>
    <label><input type="checkbox" name="content_categories" value="signature" checked> {cat_signature}</label>
  </div>

  <label>{report_lang_label}</label>
  <div class="checks">
    <label><input type="radio" name="report_lang" value="en" {report_lang_en_checked}> English</label>
    <label><input type="radio" name="report_lang" value="tr" {report_lang_tr_checked}> Türkçe</label>
  </div>

  <div class="row">
    <div>
      <label for="max_docs">{max_docs_label}</label>
      <input type="number" id="max_docs" name="max_docs" value="30" min="1" max="100000">
    </div>
    <div>
      <label for="max_crawl_pages">{max_crawl_pages_label}</label>
      <input type="number" id="max_crawl_pages" name="max_crawl_pages" value="100" min="1" max="100000">
    </div>
  </div>
  <div class="hint">{limits_hint}</div>

  <button type="submit" id="submit-btn">{submit_label}</button>
  <div class="scanning" id="scanning"><div class="spinner"></div> {scanning_hint}</div>
  <div class="hint">{footer_hint}</div>
</form>
"""


def _render_form(
    ui_lang: str = "en",
    error: str | None = None,
    targets_value: str = "",
    manual_urls_value: str = "",
    filetypes_value: str | None = None,
    ddgs_backend_value: str = "",
) -> str:
    if ui_lang not in _STRINGS:
        ui_lang = "en"

    error_block = f'<div class="error">{error}</div>' if error else ""
    exiftool_block = (
        ""
        if exiftool_available()
        else f'<div class="warn">{_t(ui_lang, "exiftool_warning")}</div>'
    )
    google_ready = bool(os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"))
    serper_ready = bool(os.environ.get("SERPER_API_KEY"))
    brave_ready = bool(os.environ.get("BRAVE_API_KEY"))
    key_found_hint = " (anahtar bulundu)" if ui_lang == "tr" else " (key found)"

    page_head = _PAGE_HEAD.format(
        ui_lang=ui_lang,
        tagline=_t(ui_lang, "tagline"),
        en_active="active" if ui_lang == "en" else "",
        tr_active="active" if ui_lang == "tr" else "",
    )
    body = _FORM_BODY.format(
        error_block=error_block,
        exiftool_block=exiftool_block,
        ui_lang=ui_lang,
        targets_label=_t(ui_lang, "targets_label"),
        targets_hint=_t(ui_lang, "targets_hint"),
        manual_toggle=_t(ui_lang, "manual_toggle"),
        manual_label=_t(ui_lang, "manual_label"),
        manual_hint=_t(ui_lang, "manual_hint"),
        filetypes_label=_t(ui_lang, "filetypes_label"),
        engines_label=_t(ui_lang, "engines_label"),
        engines_hint=_t(ui_lang, "engines_hint"),
        ddgs_hint=_t(ui_lang, "ddgs_hint"),
        ddgs_backend_label=_t(ui_lang, "ddgs_backend_label"),
        ddgs_backend_hint=_t(ui_lang, "ddgs_backend_hint"),
        ddgs_backend_value=ddgs_backend_value,
        subdomains_label=_t(ui_lang, "subdomains_label"),
        content_scan_label=_t(ui_lang, "content_scan_label"),
        content_scan_hint=_t(ui_lang, "content_scan_hint"),
        content_categories_label=_t(ui_lang, "content_categories_label"),
        cat_tc_kimlik=_t(ui_lang, "cat_tc_kimlik"),
        cat_email_phone=_t(ui_lang, "cat_email_phone"),
        cat_iban_card=_t(ui_lang, "cat_iban_card"),
        cat_address_dob=_t(ui_lang, "cat_address_dob"),
        cat_signature=_t(ui_lang, "cat_signature"),
        report_lang_label=_t(ui_lang, "report_lang_label"),
        report_lang_en_checked="checked" if ui_lang != "tr" else "",
        report_lang_tr_checked="checked" if ui_lang == "tr" else "",
        max_docs_label=_t(ui_lang, "max_docs_label"),
        max_crawl_pages_label=_t(ui_lang, "max_crawl_pages_label"),
        limits_hint=_t(ui_lang, "limits_hint"),
        submit_label=_t(ui_lang, "submit_label"),
        submit_loading_label=_t(ui_lang, "submit_loading_label"),
        scanning_hint=_t(ui_lang, "scanning_hint"),
        footer_hint=_t(ui_lang, "footer_hint"),
        targets_value=targets_value,
        manual_urls_value=manual_urls_value,
        manual_urls_open=" open" if manual_urls_value.strip() else "",
        filetypes_value=filetypes_value or ",".join(DEFAULT_FILETYPES),
        google_checked="checked" if google_ready else "",
        serper_checked="checked" if serper_ready else "",
        brave_checked="checked" if brave_ready else "",
        google_hint=key_found_hint if google_ready else "",
        serper_hint=key_found_hint if serper_ready else "",
        brave_hint=key_found_hint if brave_ready else "",
    )
    return page_head + body + _PAGE_TAIL


def _clean_ui_lang(value: str | None) -> str:
    return value if value in _STRINGS else "en"


def create_app(output_dir: str = "./metascout_output") -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        ui_lang = _clean_ui_lang(request.args.get("lang"))
        return _render_form(ui_lang=ui_lang)

    @app.post("/scan")
    def scan():
        ui_lang = _clean_ui_lang(request.form.get("ui_lang"))

        raw_targets = request.form.get("targets", "")
        targets = [t.strip() for t in raw_targets.replace(",", "\n").splitlines() if t.strip()]

        raw_manual_urls = request.form.get("manual_urls", "")
        manual_urls = list(dict.fromkeys(u.strip() for u in raw_manual_urls.splitlines() if u.strip()))

        if not targets:
            targets = sorted({urlparse(u).netloc for u in manual_urls if urlparse(u).netloc})
        raw_ddgs_backend = request.form.get("ddgs_backend", "")
        ddgs_backend = raw_ddgs_backend.strip() or "auto"

        if not targets:
            return _render_form(
                ui_lang=ui_lang, error=_t(ui_lang, "error_no_target"),
                targets_value=raw_targets, manual_urls_value=raw_manual_urls,
                ddgs_backend_value=raw_ddgs_backend,
            ), 400

        filetypes_value = request.form.get("filetypes", ",".join(DEFAULT_FILETYPES))
        filetypes = [f.strip().lower().lstrip(".") for f in filetypes_value.split(",") if f.strip()]
        engines = request.form.getlist("engines") or ["crawl", "sitemap", "wayback", "ddgs"]
        subdomains = request.form.get("subdomains") == "on"
        scan_content = request.form.get("scan_content") == "on"
        content_categories = request.form.getlist("content_categories") or list(DEFAULT_CONTENT_CATEGORIES)
        report_lang = request.form.get("report_lang", "en")
        if report_lang not in ("en", "tr"):
            report_lang = "en"
        try:
            max_docs = max(1, int(request.form.get("max_docs") or 30))
            max_crawl_pages = max(1, int(request.form.get("max_crawl_pages") or 100))
        except ValueError:
            return _render_form(
                ui_lang=ui_lang, error=_t(ui_lang, "error_invalid_numbers"), targets_value=raw_targets,
                manual_urls_value=raw_manual_urls, filetypes_value=filetypes_value,
                ddgs_backend_value=raw_ddgs_backend,
            ), 400

        run_dir = os.path.join(output_dir, "web-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        cfg = ScanConfig(
            targets=targets,
            manual_urls=manual_urls,
            filetypes=filetypes,
            engines=engines,
            max_docs=max_docs,
            max_crawl_pages=max_crawl_pages,
            output_dir=run_dir,
            include_subdomains=subdomains,
            ddgs_backend=ddgs_backend,
            scan_content=scan_content,
            content_categories=content_categories,
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
            return _render_form(
                ui_lang=ui_lang, error=str(exc), targets_value=raw_targets,
                manual_urls_value=raw_manual_urls, filetypes_value=filetypes_value,
                ddgs_backend_value=raw_ddgs_backend,
            ), 500

        os.makedirs(run_dir, exist_ok=True)
        html = render_html_report(findings, lang=report_lang)
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
