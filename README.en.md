<p align="center">
  <img src="assets/banner.svg" alt="MetaScout banner" width="100%">
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-6ea8fe.svg">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-8b7dfb.svg">
  <img alt="Platforms" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-7dd88f.svg">
  <img alt="Status" src="https://img.shields.io/badge/status-active%20development-f2a65a.svg">
</p>

<p align="center">
  Open-source, cross-platform document discovery and metadata leak analysis tool.<br>
  Designed as a spiritual successor to <a href="https://github.com/elevenpaths/foca">FOCA</a>, without the Windows lock-in.
</p>

<p align="center"><sub><a href="README.md">🇹🇷 Türkçe</a> · 🇬🇧 English</sub></p>

---

## Table of contents

- [What is this?](#what-is-this)
- [Features](#features)
- [Installation](#installation)
  - [Requirements](#requirements)
  - [macOS](#macos)
  - [Linux](#linux)
  - [Windows](#windows)
  - [Verify the install](#verify-the-install)
  - [Global install (pipx)](#global-install-pipx)
- [Quick start](#quick-start)
- [Scanning multiple targets](#scanning-multiple-targets)
- [Web UI](#web-ui)
- [Subdomain enumeration](#subdomain-enumeration)
- [Search engine API keys](#search-engine-api-keys-optional)
- [Full CLI reference](#full-cli-reference)
- [Output layout](#output-layout)
- [Architecture](#architecture)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Responsible use](#responsible-use)
- [License](#license)

## What is this?

[FOCA](https://github.com/elevenpaths/foca) was the go-to tool for metadata-based
information leakage testing for years, but it's unmaintained now and
Windows-only. **MetaScout** rewrites the same idea (find documents published on
a target site, extract their metadata, report what leaks) in Python: a fully
command-line tool that installs the same way on macOS, Linux, and Windows.

It discovers PDF/Office documents published on a target, downloads them,
extracts their metadata with [ExifTool](https://exiftool.org/), and reports:

- **Usernames** (document authors, last-modified-by, home directory paths)
- **Email addresses**
- **Software / version info** (Office build, PDF producer, etc.)
- **Operating system** hints
- **Internal file paths** (`C:\Users\...`, network shares)
- **Server / printer names** (UNC paths, `\\server\share`)

## Features

- **Three document discovery methods**: direct site crawling, `sitemap.xml`/`robots.txt`
  parsing, and optional search engine dorking (Google/Brave `site: filetype:`)
- **Multi-target scanning**: scan dozens of domains belonging to one organization
  in a single run and get one merged report
- **CLI and local web UI**: `metascout scan` from the terminal, or `metascout
  web` for a browser form
- **Passive subdomain enumeration** via [crt.sh](https://crt.sh) (Certificate
  Transparency logs), no API key required, each subdomain gets scanned too
- **Respects `robots.txt` by default** and sends an honest, non-spoofed User-Agent
- **Concurrent downloads** with a size cap and sha256 deduplication
- **Detailed HTML report** (dark theme, findings grouped by category) plus a
  **JSON report** for automation
- No exotic dependencies: the only native component is `exiftool`, available
  on every platform

## Installation

### Requirements

- Python 3.10 or newer
- [ExifTool](https://exiftool.org/) (required for metadata extraction)
- Git (optional, to clone the repo)

### macOS

```bash
# No Homebrew? https://brew.sh
brew install exiftool python@3.12 git

git clone https://github.com/gorkemguler/metascout.git
cd metascout
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On MacPorts, use `sudo port install p5-image-exiftool` instead.

### Linux

**Debian / Ubuntu**

```bash
sudo apt update
sudo apt install -y libimage-exiftool-perl python3-venv python3-pip git

git clone https://github.com/gorkemguler/metascout.git
cd metascout
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Fedora / RHEL / CentOS**

```bash
sudo dnf install -y perl-Image-ExifTool python3 git

git clone https://github.com/gorkemguler/metascout.git
cd metascout
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Arch Linux**

```bash
sudo pacman -S perl-image-exiftool python git

git clone https://github.com/gorkemguler/metascout.git
cd metascout
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Windows

**1. Install Python**

Download Python 3.10+ from [python.org/downloads](https://www.python.org/downloads/).
On the installer screen, make sure **"Add python.exe to PATH"** is checked.

**2. Install ExifTool** (pick one)

- **Chocolatey** (in an elevated PowerShell):
  ```powershell
  choco install exiftool
  ```
- **Scoop**:
  ```powershell
  scoop install exiftool
  ```
- **Manual**: download the "Windows Executable" zip from [exiftool.org](https://exiftool.org/),
  rename the extracted `exiftool(-k).exe` to `exiftool.exe`, and either copy it
  into a folder already on PATH (e.g. `C:\Windows\`) or add its folder to the
  system PATH (`Settings › System › Advanced system settings › Environment
  Variables`).

**3. Install the project** (PowerShell)

```powershell
git clone https://github.com/gorkemguler/metascout.git
cd metascout
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

> If PowerShell blocks script execution (`.venv\Scripts\Activate.ps1 cannot be
> loaded`), run this once as your own user (no admin needed):
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Using plain `cmd.exe` instead? Activate with `.venv\Scripts\activate.bat`.

### Verify the install

On any platform, with the virtual environment active:

```bash
exiftool -ver
metascout scan --help
```

If both print version/help text without errors, you're set.

> **Note:** `pip install -e .` installs the `metascout` command only into
> whichever `.venv` was active at the time. Open a new terminal, or run
> `metascout` from outside the project directory, and you'll get `zsh:
> command not found: metascout` (or `'metascout' is not recognized...` on
> Windows). That's not broken, the venv just isn't active. Either activate
> it each time (`source .venv/bin/activate`) or install it globally below.

### Global install (pipx)

If you'd rather run `metascout` from anywhere without activating a venv every
time, use [pipx](https://pipx.pypa.io/): it installs the package into its own
isolated environment but puts the command on your PATH.

```bash
# macOS
brew install pipx
pipx ensurepath

# Debian/Ubuntu
sudo apt install pipx
pipx ensurepath

# Windows (PowerShell)
python -m pip install --user pipx
python -m pipx ensurepath
```

After `pipx ensurepath`, **restart your terminal** (or run `exec zsh` / `exec
bash`), then install from the project directory:

```bash
pipx install --editable /full/path/to/metascout
```

`--editable` means code changes under `src/metascout/` take effect
immediately, no reinstall needed. After this, `metascout` works from any
directory without activating a venv.

## Quick start

```bash
metascout scan example.com
```

By default this uses site crawling (`crawl`) and `sitemap.xml`, no API key
needed. Results are written to `./metascout_output/report.html` and `report.json`.

```bash
metascout scan example.com \
  --filetypes pdf,docx,xlsx \
  --max-docs 100 \
  --max-crawl-pages 500 \
  --output-dir ./out
```

## Scanning multiple targets

Scan several domains belonging to the same organization in one run and get a
**single merged report**, no need to run the tool repeatedly and stitch
reports together yourself:

```bash
metascout scan example.com example.org another-example.net
```

For a longer list, put them in a file and use `--targets-file` (one domain
per line, `#` starts a comment):

```bash
cat > domains.txt <<EOF
# Acme Corp domains
example.com
example.org
another-example.net
EOF

metascout scan --targets-file domains.txt --subdomains
```

When more than one target is given, the generated `report.html`/`report.json`
includes a **"Targets"** table breaking down how many documents were found per
domain.

## Web UI

If you'd rather fill out a browser form than type CLI flags:

```bash
metascout web
```

This opens a local UI at `http://127.0.0.1:8765/` (launches in your browser
automatically). Enter your targets (one per line), file extensions, discovery
engines, and the subdomain toggle, then hit "Taramayı başlat" (Start scan).
When the scan finishes, the report opens right in the browser; it's also saved
under `--output-dir` (default `./metascout_output/web-<timestamp>/`) as
`report.html`/`report.json`.

```bash
metascout web --port 9000 --output-dir ~/metascout-workspace/metascout_output
```

The UI only listens on `127.0.0.1` (change with `--host`). Don't expose it to
the internet. To use the `google`/`brave` checkboxes, the matching API
keys need to be set via environment variable or `.env` (see [Search engine API
keys](#search-engine-api-keys-optional)).

## Subdomain enumeration

`--subdomains` performs passive subdomain discovery via [crt.sh](https://crt.sh)
(Certificate Transparency log search, no API key required); every discovered
subdomain is scanned with the same document-discovery engines (crawl/sitemap/google/brave):

```bash
metascout scan example.com --subdomains --max-subdomains 30
```

`crt.sh` can be slow or rate-limited at times. In that case the scan silently
continues with an empty subdomain list; the scan of the main domain is unaffected.

## Search engine API keys (optional)

The `google` and `brave` engines run classic FOCA-style
`site:target filetype:pdf` dork searches; each needs an API key:

```bash
cp .env.example .env
# fill in GOOGLE_API_KEY, GOOGLE_CSE_ID and/or BRAVE_API_KEY
```

> **Security note:** `.env` is already in [.gitignore](.gitignore), so even if
> you keep it in this repo folder, `git add .` won't pick it up. Still, the
> safest setup is to keep your real keys in a **separate folder outside the
> git repository entirely**, e.g. `~/metascout-workspace/.env`. If you
> [install metascout globally with pipx](#global-install-pipx), `metascout
> scan` reads the `.env` from whatever directory you run it in, so you can run
> scans without ever touching the source repo.

- **Google**: create a search engine at [Programmable Search Engine](https://programmablesearchengine.google.com/)
  (configure it to search the entire web) and get an API key for the
  [Custom Search JSON API](https://developers.google.com/custom-search/v1/overview).
  Free tier: 100 queries/day.
- **Brave**: sign up at [brave.com/search/api](https://brave.com/search/api/)
  (a free "Data for AI" tier is available) and get your `X-Subscription-Token`.

```bash
metascout scan example.com --engines crawl,sitemap,google,brave
```

## Full CLI reference

```bash
metascout scan --help
metascout web --help
```

`metascout scan` takes one or more `TARGET` positional arguments
(`metascout scan a.com b.com`), or use `--targets-file` instead:

| Option | Default | Description |
|---|---|---|
| `--targets-file` | – | File with one domain/URL per line (`#` for comments) |
| `--filetypes` | `pdf,doc,docx,xls,xlsx,ppt,pptx,odt,ods,odp` | File extensions to look for |
| `--engines` | `crawl,sitemap` | Comma-separated: `crawl,sitemap,google,brave` |
| `--subdomains` / `--no-subdomains` | off | Enumerate subdomains via crt.sh |
| `--max-subdomains` | `20` | Maximum subdomains to scan |
| `--max-docs` | `50` | Maximum documents to download and analyze |
| `--max-crawl-pages` | `200` | Max pages the crawler visits per host |
| `--max-crawl-depth` | `3` | Max link depth for the crawler |
| `--concurrency` | `8` | Concurrent downloads |
| `--timeout` | `15` | Per-request timeout in seconds |
| `--max-download-mb` | `50` | Max download size per document (MB) |
| `--output-dir` | `./metascout_output` | Output directory |
| `--ignore-robots` | off | Ignore `robots.txt` (only with explicit authorization) |
| `--google-api-key`, `--google-cse-id`, `--brave-api-key` | – | Can also be set via env var or `.env` |
| `--json-report` / `--no-json-report` | on | Produce a JSON report |
| `--html-report` / `--no-html-report` | on | Produce an HTML report |

`metascout web` options:

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Local only, don't expose to the internet |
| `--port` | `8765` | Port to listen on |
| `--output-dir` | `./metascout_output` | Where scan runs get saved |
| `--open-browser` / `--no-open-browser` | on | Auto-open the browser on startup |

## Output layout

```
metascout_output/
├── downloads/               raw downloaded documents (metascout scan)
├── report.html              visual summary report (metascout scan)
├── report.json              raw findings for automation/integration (metascout scan)
└── web-20260101-120000/     each metascout web run gets its own timestamped folder
    ├── downloads/
    ├── report.html
    └── report.json
```

## Architecture

```
src/metascout/
├── discovery/
│   ├── crawler.py         direct site crawling (robots.txt aware)
│   ├── sitemap.py         sitemap.xml / sitemap index parsing
│   ├── search_engines.py  Google/Brave dork search
│   └── subdomains.py      passive subdomain discovery via crt.sh
├── downloader.py           concurrent downloads, size cap, sha256
├── metadata/
│   ├── exiftool_wrapper.py exiftool subprocess wrapper
│   └── analyzer.py         regex + field-based extraction, per-target counts
├── report/
│   ├── html_report.py      Jinja2-based HTML report
│   └── json_report.py      JSON report
├── pipeline.py              discover → download → extract → analyze flow (shared by CLI and web)
├── cli.py                   click-based `metascout scan` / `metascout web` commands
└── web.py                   Flask-based local web UI
```

## Testing

```bash
pip install -e . pytest
pytest
```

## Troubleshooting

**`zsh: command not found: metascout`** (or `'metascout' is not recognized...` on PowerShell)
`metascout` only exists inside the `.venv` you installed it into. It's not
callable from any random terminal unless that venv is active. Two fixes:
1. `cd` into the project and activate the venv: `cd /path/to/metascout && source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`)
2. Or do a [global install with pipx](#global-install-pipx) to make the command available everywhere.

**`exiftool not found on PATH`**
ExifTool isn't installed or isn't on PATH. Follow the step for your platform
under [Installation](#installation), then verify with `exiftool -ver`.

**On Windows, `exiftool(-k).exe` works but `exiftool` doesn't**
The file in the zip is named `exiftool(-k).exe`. Rename it to `exiftool.exe`
and place it in a folder on PATH (see the Windows install steps above).

**`No documents discovered`**
The target has no publicly linked documents matching your extensions
(default: `pdf,doc,docx,...`), or `robots.txt` is blocking the crawler. Try a
wider net with `--engines crawl,sitemap,google,brave`, or (only if you're
authorized) `--ignore-robots`.

**crt.sh is unresponsive / slow**
The service rate-limits occasionally; the scan silently continues with an
empty subdomain list. Try again in a few minutes.

**`Google`/`Brave` engine prints a "skipped" warning**
The corresponding API key/CSE id isn't set. See [Search engine API keys](#search-engine-api-keys-optional).

## Responsible use

This tool is built for **your own systems** or targets you have **written
authorization** to test. It respects `robots.txt` by default and sends an
honest, non-spoofed User-Agent (`MetaScout/0.1`), so a target's operators can
see recon traffic in their logs and block it if they want to. Using it against
systems you're not authorized to test may be illegal; that responsibility is
entirely on the user.

## License

[MIT](LICENSE) © 2026 Görkem Güler
