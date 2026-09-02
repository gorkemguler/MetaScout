from __future__ import annotations

import io
import json
import os
import threading
import time
import webbrowser
import zipfile
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, Response, abort, request, send_file, stream_with_context

from .config import DEFAULT_CONTENT_CATEGORIES, DEFAULT_FILETYPES, ScanConfig
from .metadata import exiftool_available
from .pipeline import run_local_document_scan, run_scan
from .report import render_html_report, render_json_report

# In-memory registry of live log lines per in-flight scan, so the browser can
# stream them (via SSE, see /scan-log/<scan_id>) while the form's POST is
# still synchronously running. Capped and lock-guarded — this is a local,
# single-user dev tool, not a service, so a simple in-process dict is enough;
# no need for a real job queue or persistent storage.
_SCAN_LOG_LIMIT = 20
_scan_logs: dict[str, list[str]] = {}
_scan_logs_lock = threading.Lock()


def _register_scan_log(scan_id: str) -> None:
    if not scan_id:
        return
    with _scan_logs_lock:
        _scan_logs[scan_id] = []
        while len(_scan_logs) > _SCAN_LOG_LIMIT:
            _scan_logs.pop(next(iter(_scan_logs)))


def _push_scan_log(scan_id: str, message: str) -> None:
    if not scan_id:
        return
    with _scan_logs_lock:
        if scan_id in _scan_logs:
            _scan_logs[scan_id].append(message)


def _make_log_fn(scan_id: str):
    def log(message: str) -> None:
        print(f"[metascout web] {message}", flush=True)
        _push_scan_log(scan_id, message)
    return log

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
                              "numbers, address/DOB hints, signature hints, leaked credentials "
                              "(API keys, private keys, DB connection strings, JWTs), and leaked "
                              "infrastructure info (cloud storage links, internal hostnames/IPs). "
                              "Heuristic — every hit needs manual verification, not a confirmed leak. "
                              "Requires the optional extra on the machine running the scan: "
                              "<code>pip install 'metascout[content-scan]'</code>.",
        "content_categories_label": "Categories",
        "cat_tc_kimlik": "TR national ID no. (checksum-verified)",
        "cat_email_phone": "Emails / phone numbers",
        "cat_iban_card": "IBAN / credit card no. (checksum-verified)",
        "cat_address_dob": "Address / date-of-birth hints (weak signal)",
        "cat_signature": "Signature hints (keyword + PDF digital signature)",
        "cat_secrets": "Leaked credentials (AWS/GitHub/Slack/Stripe keys, private keys, DB strings, JWTs)",
        "cat_infra": "Leaked infrastructure info (cloud storage/file-share links, internal hostnames/private IPs)",
        "visual_signature_label": "EXPERIMENTAL: also try visual (wet) signature detection",
        "visual_signature_hint": "Independent of content scanning above — works with or without it. "
                                  "Looks for a handwritten-signature-shaped ink blob in the actual page "
                                  "image, catching a scanned signature with no text layer or /Sig field "
                                  "at all. Off by default — heuristic with a real false-positive rate "
                                  "(confirmed live: both correct detections and false positives on real "
                                  "insurance-form PDFs), upstream unmaintained since 2022, often takes "
                                  "well over a minute per document, and needs "
                                  "<code>pip install 'metascout[visual-signature]'</code> "
                                  "<strong>plus ImageMagick and Ghostscript installed system-wide</strong> "
                                  "(not just the pip package). For a large batch, running "
                                  "<code>metascout visual-signature-scan</code> from a terminal against "
                                  "this scan's output afterward is more practical than waiting here.",
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
        "nav_scan_label": "Discover & Scan a Target",
        "nav_local_label": "Scan Existing Documents",
        "local_intro": "Already have a folder of documents (your own files, or ones gathered some "
                        "other way)? Analyze them directly — no target, no discovery, no download.",
        "local_dir_label": "Directory path (on this machine)",
        "local_dir_hint": "An absolute path readable by the account running <code>metascout web</code>, "
                           "e.g. <code>/Users/you/Downloads/reports</code>. Every file inside it "
                           "(searched recursively) matching the extensions below is analyzed.",
        "local_or": "— or —",
        "local_urls_label": "URL list (one full document URL per line)",
        "local_urls_hint": "Downloads and analyzes these directly, no discovery. Fill in exactly one "
                            "of directory-path-above or URL-list-here, not both.",
        "local_error_no_source": "Provide either a directory path or a URL list.",
        "local_error_both_sources": "Provide only one of directory path or URL list, not both.",
        "local_error_dir_not_found": "That directory doesn't exist or isn't readable from this machine.",
        "local_submit_label": "Analyze documents",
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
                              "adres/doğum tarihi ipuçları, imza ipuçları, sızmış kimlik bilgileri "
                              "(API anahtarları, private key, DB bağlantı string'i, JWT) ve sızmış "
                              "altyapı bilgisi (cloud storage linkleri, iç hostname/IP) için tarar. "
                              "Sezgisel bir taramadır — her bulgu kesin bir sızıntı değil, elle doğrulanmalıdır. "
                              "Taramayı çalıştıran makinede opsiyonel ek paket gerektirir: "
                              "<code>pip install 'metascout[content-scan]'</code>.",
        "content_categories_label": "Kategoriler",
        "cat_tc_kimlik": "TC Kimlik No (checksum doğrulamalı)",
        "cat_email_phone": "E-posta / telefon numaraları",
        "cat_iban_card": "IBAN / kredi kartı no (checksum doğrulamalı)",
        "cat_address_dob": "Adres / doğum tarihi ipuçları (zayıf sinyal)",
        "cat_signature": "İmza ipuçları (anahtar kelime + PDF dijital imza)",
        "cat_secrets": "Sızmış kimlik bilgileri (AWS/GitHub/Slack/Stripe anahtarları, private key, DB bağlantı string'i, JWT)",
        "cat_infra": "Sızmış altyapı bilgisi (cloud storage/paylaşım linkleri, iç hostname/özel IP)",
        "visual_signature_label": "DENEYSEL: görsel (ıslak) imza tespitini de dene",
        "visual_signature_hint": "Yukarıdaki içerik taramasından bağımsız — onunla ya da onsuz çalışır. "
                                  "Sayfa görüntüsünde el yazısı imza şeklinde bir mürekkep lekesi arar, "
                                  "hiç metin katmanı ya da /Sig alanı olmayan taranmış bir imzayı bile "
                                  "yakalar. Varsayılan kapalı — gerçek bir yanlış-pozitif oranı var "
                                  "(canlı doğrulandı: gerçek sigorta formu PDF'lerinde hem doğru tespit "
                                  "hem yanlış pozitif çıktı), üst kaynak proje 2022'den beri bakımsız, "
                                  "genelde belge başına bir dakikadan fazla sürüyor, ve "
                                  "<code>pip install 'metascout[visual-signature]'</code> "
                                  "<strong>üstüne sistemde kurulu ImageMagick ve Ghostscript</strong> "
                                  "gerektirir (sadece pip paketi yetmez). Büyük bir belge grubu için, "
                                  "burada beklemek yerine bu taramanın sonuçları üzerinde terminalden "
                                  "<code>metascout visual-signature-scan</code> çalıştırmak daha pratik.",
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
        "nav_scan_label": "Hedef Keşfet & Tara",
        "nav_local_label": "Mevcut Belgeleri Tara",
        "local_intro": "Zaten bir belge klasörünüz mü var (kendi dosyalarınız ya da başka bir "
                        "şekilde topladıklarınız)? Doğrudan analiz edin — hedef yok, keşif yok, "
                        "indirme yok.",
        "local_dir_label": "Dizin yolu (bu makinede)",
        "local_dir_hint": "<code>metascout web</code>'i çalıştıran hesabın okuyabildiği mutlak bir "
                           "yol, ör. <code>/Users/siz/Downloads/raporlar</code>. İçindeki (özyinelemeli "
                           "aranan) aşağıdaki uzantılarla eşleşen her dosya analiz edilir.",
        "local_or": "— ya da —",
        "local_urls_label": "URL listesi (her satıra bir tam belge URL'i)",
        "local_urls_hint": "Bunları doğrudan indirip analiz eder, keşif yok. Yukarıdaki dizin yolu "
                            "ya da buradaki URL listesinden tam olarak birini doldurun, ikisini "
                            "birden değil.",
        "local_error_no_source": "Bir dizin yolu ya da URL listesi girin.",
        "local_error_both_sources": "Dizin yolu ya da URL listesinden yalnızca birini girin, ikisini birden değil.",
        "local_error_dir_not_found": "Bu dizin yok ya da bu makineden okunamıyor.",
        "local_submit_label": "Belgeleri analiz et",
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
  .page-nav {{ display: flex; gap: 18px; margin-top: 10px; }}
  .page-nav a {{ color: var(--muted); text-decoration: none; font-size: 12.5px; font-weight: 600;
    padding-bottom: 2px; border-bottom: 2px solid transparent; }}
  .page-nav a.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
  .page-nav a:hover:not(.active) {{ color: var(--text); }}
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
  .scanning {{ display: none; margin-top: 16px; }}
  .scanning.active {{ display: block; }}
  .scanning-row {{ display: flex; align-items: center; gap: 10px; color: var(--accent); font-size: 13px; }}
  .spinner {{ width: 16px; height: 16px; border: 2px solid rgba(110,168,254,0.25); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.8s linear infinite; flex-shrink: 0; }}
  .log-box {{ margin: 10px 0 0; max-height: 220px; overflow-y: auto; background: #0a0c11;
    border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px;
    color: var(--muted); white-space: pre-wrap; word-break: break-word; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .banner {{ color: #8bb4ff; font-weight: 800; font-size: 22px; }}
  .error {{ background: rgba(242,109,109,0.1); border: 1px solid var(--bad); color: var(--bad);
    border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; }}
  .warn {{ background: rgba(242,166,90,0.1); border: 1px solid var(--warn); color: var(--warn);
    border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; }}
  a {{ color: var(--accent); }}
</style>
<script>
function metascoutStartScan() {{
  var btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.textContent = btn.dataset.loading;
  document.getElementById('scanning').className = 'scanning active';
  var sid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : (Date.now() + '-' + Math.random());
  document.getElementById('scan_id').value = sid;
  var logBox = document.getElementById('log-box');
  try {{
    var es = new EventSource('/scan-log/' + sid);
    es.onmessage = function(e) {{
      logBox.textContent += JSON.parse(e.data) + '\\n';
      logBox.scrollTop = logBox.scrollHeight;
    }};
    es.onerror = function() {{ es.close(); }};
  }} catch (err) {{ /* EventSource unsupported — spinner still shows, just no live log */ }}
}}
</script>
</head>
<body>
<header>
  <div>
    <div class="banner">MetaScout</div>
    <div class="meta">{tagline}</div>
    <div class="page-nav">
      <a href="/?lang={ui_lang}" class="{nav_scan_active}">{nav_scan_label}</a>
      <a href="/local-scan?lang={ui_lang}" class="{nav_local_active}">{nav_local_label}</a>
    </div>
  </div>
  <div class="lang-switch">
    <a href="{base_path}?lang=en" class="{en_active}">EN</a>
    <a href="{base_path}?lang=tr" class="{tr_active}">TR</a>
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
<form class="card" method="post" action="/scan" onsubmit="metascoutStartScan();">
  <input type="hidden" name="ui_lang" value="{ui_lang}">
  <input type="hidden" name="scan_id" id="scan_id" value="">
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
    <label><input type="checkbox" name="content_categories" value="secrets" checked> {cat_secrets}</label>
    <label><input type="checkbox" name="content_categories" value="infra" checked> {cat_infra}</label>
  </div>

  <label><input type="checkbox" name="visual_signature" id="visual_signature"> {visual_signature_label}</label>
  <div class="hint">{visual_signature_hint}</div>

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

  <button type="submit" id="submit-btn" data-loading="{submit_loading_label}">{submit_label}</button>
  <div class="scanning" id="scanning">
    <div class="scanning-row"><div class="spinner"></div> {scanning_hint}</div>
    <pre class="log-box" id="log-box"></pre>
  </div>
  <div class="hint">{footer_hint}</div>
</form>
"""


def _render_page_head(ui_lang: str, current_page: str) -> str:
    """current_page is "scan" or "local" — drives both which nav link is
    highlighted and which page the EN/TR language switcher stays on."""
    base_path = "/local-scan" if current_page == "local" else "/"
    return _PAGE_HEAD.format(
        ui_lang=ui_lang,
        tagline=_t(ui_lang, "tagline"),
        base_path=base_path,
        en_active="active" if ui_lang == "en" else "",
        tr_active="active" if ui_lang == "tr" else "",
        nav_scan_label=_t(ui_lang, "nav_scan_label"),
        nav_local_label=_t(ui_lang, "nav_local_label"),
        nav_scan_active="active" if current_page == "scan" else "",
        nav_local_active="active" if current_page == "local" else "",
    )


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

    page_head = _render_page_head(ui_lang, "scan")
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
        cat_secrets=_t(ui_lang, "cat_secrets"),
        cat_infra=_t(ui_lang, "cat_infra"),
        visual_signature_label=_t(ui_lang, "visual_signature_label"),
        visual_signature_hint=_t(ui_lang, "visual_signature_hint"),
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


_LOCAL_SCAN_FORM_BODY = """
{error_block}
{exiftool_block}
<p class="hint" style="margin-bottom:20px;">{local_intro}</p>
<form class="card" method="post" action="/local-scan" onsubmit="metascoutStartScan();">
  <input type="hidden" name="ui_lang" value="{ui_lang}">
  <input type="hidden" name="scan_id" id="scan_id" value="">
  <label for="local_dir">{local_dir_label}</label>
  <input type="text" id="local_dir" name="local_dir" placeholder="/Users/you/Downloads/reports" value="{local_dir_value}">
  <div class="hint">{local_dir_hint}</div>

  <div class="hint" style="text-align:center;margin:16px 0;">{local_or}</div>

  <label for="local_urls">{local_urls_label}</label>
  <textarea id="local_urls" name="local_urls" placeholder="https://example.com/reports/2023.pdf&#10;https://example.com/files/notes.docx">{local_urls_value}</textarea>
  <div class="hint">{local_urls_hint}</div>

  <label for="filetypes">{filetypes_label}</label>
  <input type="text" id="filetypes" name="filetypes" value="{filetypes_value}">

  <label><input type="checkbox" name="scan_content" id="scan_content"> {content_scan_label}</label>
  <div class="hint">{content_scan_hint}</div>
  <label>{content_categories_label}</label>
  <div class="checks">
    <label><input type="checkbox" name="content_categories" value="tc_kimlik" checked> {cat_tc_kimlik}</label>
    <label><input type="checkbox" name="content_categories" value="email_phone" checked> {cat_email_phone}</label>
    <label><input type="checkbox" name="content_categories" value="iban_card" checked> {cat_iban_card}</label>
    <label><input type="checkbox" name="content_categories" value="address_dob" checked> {cat_address_dob}</label>
    <label><input type="checkbox" name="content_categories" value="signature" checked> {cat_signature}</label>
    <label><input type="checkbox" name="content_categories" value="secrets" checked> {cat_secrets}</label>
    <label><input type="checkbox" name="content_categories" value="infra" checked> {cat_infra}</label>
  </div>

  <label><input type="checkbox" name="visual_signature" id="visual_signature"> {visual_signature_label}</label>
  <div class="hint">{visual_signature_hint}</div>

  <label>{report_lang_label}</label>
  <div class="checks">
    <label><input type="radio" name="report_lang" value="en" {report_lang_en_checked}> English</label>
    <label><input type="radio" name="report_lang" value="tr" {report_lang_tr_checked}> Türkçe</label>
  </div>

  <button type="submit" id="submit-btn" data-loading="{submit_loading_label}">{local_submit_label}</button>
  <div class="scanning" id="scanning">
    <div class="scanning-row"><div class="spinner"></div> {scanning_hint}</div>
    <pre class="log-box" id="log-box"></pre>
  </div>
  <div class="hint">{footer_hint}</div>
</form>
"""


def _render_local_form(
    ui_lang: str = "en",
    error: str | None = None,
    local_dir_value: str = "",
    local_urls_value: str = "",
    filetypes_value: str | None = None,
) -> str:
    if ui_lang not in _STRINGS:
        ui_lang = "en"

    error_block = f'<div class="error">{error}</div>' if error else ""
    exiftool_block = (
        ""
        if exiftool_available()
        else f'<div class="warn">{_t(ui_lang, "exiftool_warning")}</div>'
    )

    page_head = _render_page_head(ui_lang, "local")
    body = _LOCAL_SCAN_FORM_BODY.format(
        error_block=error_block,
        exiftool_block=exiftool_block,
        ui_lang=ui_lang,
        local_intro=_t(ui_lang, "local_intro"),
        local_dir_label=_t(ui_lang, "local_dir_label"),
        local_dir_hint=_t(ui_lang, "local_dir_hint"),
        local_dir_value=local_dir_value,
        local_or=_t(ui_lang, "local_or"),
        local_urls_label=_t(ui_lang, "local_urls_label"),
        local_urls_hint=_t(ui_lang, "local_urls_hint"),
        local_urls_value=local_urls_value,
        filetypes_label=_t(ui_lang, "filetypes_label"),
        filetypes_value=filetypes_value if filetypes_value is not None else ",".join(DEFAULT_FILETYPES),
        content_scan_label=_t(ui_lang, "content_scan_label"),
        content_scan_hint=_t(ui_lang, "content_scan_hint"),
        content_categories_label=_t(ui_lang, "content_categories_label"),
        cat_tc_kimlik=_t(ui_lang, "cat_tc_kimlik"),
        cat_email_phone=_t(ui_lang, "cat_email_phone"),
        cat_iban_card=_t(ui_lang, "cat_iban_card"),
        cat_address_dob=_t(ui_lang, "cat_address_dob"),
        cat_signature=_t(ui_lang, "cat_signature"),
        cat_secrets=_t(ui_lang, "cat_secrets"),
        cat_infra=_t(ui_lang, "cat_infra"),
        visual_signature_label=_t(ui_lang, "visual_signature_label"),
        visual_signature_hint=_t(ui_lang, "visual_signature_hint"),
        report_lang_label=_t(ui_lang, "report_lang_label"),
        report_lang_en_checked="checked" if ui_lang != "tr" else "",
        report_lang_tr_checked="checked" if ui_lang == "tr" else "",
        local_submit_label=_t(ui_lang, "local_submit_label"),
        submit_loading_label=_t(ui_lang, "submit_loading_label"),
        scanning_hint=_t(ui_lang, "scanning_hint"),
        footer_hint=_t(ui_lang, "footer_hint"),
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
        visual_signature = request.form.get("visual_signature") == "on"
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
            visual_signature=visual_signature,
            google_api_key=os.environ.get("GOOGLE_API_KEY"),
            google_cse_id=os.environ.get("GOOGLE_CSE_ID"),
            serper_api_key=os.environ.get("SERPER_API_KEY"),
            brave_api_key=os.environ.get("BRAVE_API_KEY"),
        )

        scan_id = request.form.get("scan_id", "")
        _register_scan_log(scan_id)
        _log = _make_log_fn(scan_id)

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
        run_id = os.path.basename(run_dir)
        html = render_html_report(findings, lang=report_lang, download_url=f"/download/{run_id}")
        with open(os.path.join(run_dir, "report.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
            fh.write(render_json_report(findings))

        _log(f"scan finished: {len(findings.documents)} document(s), report saved to {run_dir}")
        return html

    @app.get("/local-scan")
    def local_scan_index():
        ui_lang = _clean_ui_lang(request.args.get("lang"))
        return _render_local_form(ui_lang=ui_lang)

    @app.post("/local-scan")
    def local_scan():
        ui_lang = _clean_ui_lang(request.form.get("ui_lang"))

        raw_local_dir = request.form.get("local_dir", "").strip()
        raw_local_urls = request.form.get("local_urls", "")
        local_urls = list(dict.fromkeys(u.strip() for u in raw_local_urls.splitlines() if u.strip()))

        if raw_local_dir and local_urls:
            return _render_local_form(
                ui_lang=ui_lang, error=_t(ui_lang, "local_error_both_sources"),
                local_dir_value=raw_local_dir, local_urls_value=raw_local_urls,
            ), 400
        if not raw_local_dir and not local_urls:
            return _render_local_form(
                ui_lang=ui_lang, error=_t(ui_lang, "local_error_no_source"),
                local_dir_value=raw_local_dir, local_urls_value=raw_local_urls,
            ), 400
        if raw_local_dir and not os.path.isdir(raw_local_dir):
            return _render_local_form(
                ui_lang=ui_lang, error=_t(ui_lang, "local_error_dir_not_found"),
                local_dir_value=raw_local_dir, local_urls_value=raw_local_urls,
            ), 400

        filetypes_value = request.form.get("filetypes", ",".join(DEFAULT_FILETYPES))
        filetypes = [f.strip().lower().lstrip(".") for f in filetypes_value.split(",") if f.strip()]
        scan_content = request.form.get("scan_content") == "on"
        content_categories = request.form.getlist("content_categories") or list(DEFAULT_CONTENT_CATEGORIES)
        visual_signature = request.form.get("visual_signature") == "on"
        report_lang = request.form.get("report_lang", "en")
        if report_lang not in ("en", "tr"):
            report_lang = "en"

        run_dir = os.path.join(output_dir, "local-" + datetime.now().strftime("%Y%m%d-%H%M%S"))

        scan_id = request.form.get("scan_id", "")
        _register_scan_log(scan_id)
        _log = _make_log_fn(scan_id)

        try:
            if raw_local_dir:
                _log(f"local-scan started: directory={raw_local_dir}")
                findings = run_local_document_scan(
                    raw_local_dir, filetypes=filetypes, scan_content=scan_content,
                    content_categories=content_categories, visual_signature=visual_signature, log=_log,
                )
            else:
                _log(f"local-scan started: {len(local_urls)} URL(s), no discovery")
                targets = sorted({urlparse(u).netloc for u in local_urls if urlparse(u).netloc})
                cfg = ScanConfig(
                    targets=targets, manual_urls=local_urls, filetypes=filetypes, engines=[],
                    output_dir=run_dir, scan_content=scan_content,
                    content_categories=content_categories, visual_signature=visual_signature,
                )
                findings = run_scan(cfg, log=_log)
        except RuntimeError as exc:
            return _render_local_form(
                ui_lang=ui_lang, error=str(exc),
                local_dir_value=raw_local_dir, local_urls_value=raw_local_urls, filetypes_value=filetypes_value,
            ), 500

        os.makedirs(run_dir, exist_ok=True)
        run_id = os.path.basename(run_dir)
        html = render_html_report(findings, lang=report_lang, download_url=f"/download/{run_id}")
        with open(os.path.join(run_dir, "report.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
            fh.write(render_json_report(findings))

        _log(f"local-scan finished: {len(findings.documents)} document(s), report saved to {run_dir}")
        return html

    @app.get("/scan-log/<scan_id>")
    def scan_log_stream(scan_id: str):
        """Server-Sent Events stream of a running scan's log lines, so the
        browser can show live progress while the /scan or /local-scan POST
        (which the form submits to directly, and which blocks until the
        scan finishes) is still in flight. The client opens this
        concurrently with submitting the form — see metascoutStartScan() in
        _PAGE_HEAD. Ends on its own once the client disconnects (e.g. the
        page navigates away when the form's response finally arrives); the
        idle cap below is just a safety net against an orphaned connection.
        """
        def generate():
            sent = 0
            idle_iterations = 0
            max_idle_iterations = 3 * 60 * 60 * 2  # ~3h at 0.5s/iteration — generous, some scans are slow
            while idle_iterations < max_idle_iterations:
                with _scan_logs_lock:
                    lines = _scan_logs.get(scan_id)
                    if lines is None:
                        return
                    new_lines = lines[sent:]
                    sent = len(lines)
                if new_lines:
                    idle_iterations = 0
                    for line in new_lines:
                        yield f"data: {json.dumps(line)}\n\n"
                else:
                    idle_iterations += 1
                    if idle_iterations % 20 == 0:
                        yield ": keep-alive\n\n"
                time.sleep(0.5)
        return Response(
            stream_with_context(generate()), mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/download/<run_id>")
    def download_results(run_id: str):
        """Zips one run's whole output directory (report.html, report.json,
        downloads/) and serves it as a single file — the "Download results"
        button on the report page. `run_id` is always server-generated (the
        run directory's own basename, e.g. "web-20260101-120000"), but it's
        still validated defensively here since it arrives back as untrusted
        user input on this request.
        """
        base = os.path.realpath(output_dir)
        if not run_id or run_id in (".", "..") or "/" in run_id or "\\" in run_id:
            abort(404)
        run_path = os.path.realpath(os.path.join(base, run_id))
        if run_path != base and not run_path.startswith(base + os.sep):
            abort(404)
        if not os.path.isdir(run_path):
            abort(404)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(run_path):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, arcname=os.path.join(run_id, os.path.relpath(full, run_path)))
        buffer.seek(0)
        return send_file(
            buffer, mimetype="application/zip", as_attachment=True,
            download_name=f"metascout-{run_id}.zip",
        )

    return app


def run_server(host: str = "127.0.0.1", port: int = 8765, output_dir: str = "./metascout_output", open_browser: bool = True) -> None:
    app = create_app(output_dir=output_dir)
    url = f"http://{host}:{port}/"
    if open_browser:
        webbrowser.open(url)
    app.run(host=host, port=port, debug=False, threaded=True)
