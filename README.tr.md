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
  Açık kaynak, çapraz platform belge keşfi ve metadata sızıntı analiz aracı.<br>
  <a href="https://github.com/elevenpaths/foca">FOCA</a>'nın yerini alacak şekilde tasarlandı, ama Windows'a bağımlı değil.
</p>

<p align="center"><sub><a href="README.md">🇬🇧 English</a> · 🇹🇷 Türkçe</sub></p>

<p align="center">
  ⭐ MetaScout işine yaradıysa reponuza bir yıldız bırakmayı düşünün — başkalarının da bulmasına yardımcı olur.
</p>

---

## İçindekiler

- [Nedir bu?](#nedir-bu)
- [Özellikler](#özellikler)
- [Kurulum](#kurulum)
  - [Gereksinimler](#gereksinimler)
  - [macOS](#macos)
  - [Linux](#linux)
  - [Windows](#windows)
  - [Kurulumu doğrulama](#kurulumu-doğrulama)
  - [Global kurulum (pipx)](#global-kurulum-pipx)
- [Hızlı başlangıç](#hızlı-başlangıç)
- [Çoklu hedef taraması](#çoklu-hedef-taraması)
- [Manuel URL listesiyle tarama](#manuel-url-listesiyle-tarama)
- [Web arayüzü](#web-arayüzü)
- [Wayback Machine keşfi](#wayback-machine-keşfi)
- [Subdomain taraması](#subdomain-taraması)
- [Arama motoru API anahtarları](#arama-motoru-api-anahtarları-opsiyonel)
- [Tüm CLI seçenekleri](#tüm-cli-seçenekleri)
- [Çıktı yapısı](#çıktı-yapısı)
- [Mimari](#mimari)
- [Test](#test)
- [Sorun giderme](#sorun-giderme)
- [Etik kullanım](#etik-kullanım)
- [Lisans](#lisans)

## Nedir bu?

[FOCA](https://github.com/elevenpaths/foca), yıllarca metadata tabanlı bilgi
sızıntısı testlerinin standart aracı oldu, ama artık bakımı yapılmıyor ve
sadece Windows'ta çalışıyor. **MetaScout**, aynı fikri (hedef sitede yayınlanmış
belgeleri bul, metadata'sını çıkar, sızan bilgiyi raporla) Python ile yeniden
yazan, tamamen komut satırından çalışan, macOS/Linux/Windows'ta aynı şekilde
kurulan bir alternatif.

Bir hedefte yayınlanmış PDF/Office belgelerini keşfeder, indirir, her birinin
metadata'sını [ExifTool](https://exiftool.org/) ile çıkarır ve şunları raporlar:

- **Kullanıcı adları** (belge yazarları, son düzenleyenler, ev dizini yolları)
- **E-posta adresleri**
- **Yazılım / sürüm bilgisi** (Office sürümü, PDF üretici yazılımı vb.)
- **İşletim sistemi** ipuçları
- **İç dosya yolları** (`C:\Users\...`, ağ paylaşımları)
- **Sunucu / yazıcı isimleri** (UNC yolları, `\\server\share`)

## Özellikler

- **Birden fazla belge keşif yöntemi**: doğrudan site taraması (crawl), `sitemap.xml`/`robots.txt`
  ayrıştırma, Wayback Machine arşivi (canlıda artık olmayan dosyaları bile bulur),
  ve isteğe bağlı arama motoru dork'ları (Google/Serper/Brave `site: filetype:`)
- **Çoklu hedef taraması**: bir kuruma ait onlarca domaini tek komutta/tek formda
  tarayıp tek bir raporda birleştirir
- **Hem CLI hem yerel web arayüzü**: `metascout scan` ile terminalden, `metascout
  web` ile tarayıcıdan form doldurarak
- **Pasif subdomain keşfi**: [crt.sh](https://crt.sh) (Certificate Transparency
  logları) üzerinden API anahtarı gerektirmeden subdomain bulur, her birini de tarar
- **`robots.txt`'e saygılı** varsayılan davranış, dürüst bir User-Agent gönderir
- **Eşzamanlı indirme**, boyut sınırı ve sha256 ile tekilleştirme
- **Detaylı HTML rapor** (koyu tema, kategori bazlı bulgu tabloları, İngilizce
  veya Türkçe) + otomasyon için **JSON rapor**
- Harici bağımlılık yok: tek native bileşen `exiftool`, o da tüm platformlarda mevcut

## Kurulum

### Gereksinimler

- Python 3.10 veya üzeri
- [ExifTool](https://exiftool.org/) (metadata çıkarımı için zorunlu)
- Git (opsiyonel, repoyu klonlamak için)

### macOS

```bash
# Homebrew yoksa: https://brew.sh
brew install exiftool python@3.12 git

git clone https://github.com/gorkemguler/metascout.git
cd metascout
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

MacPorts kullanıyorsanız `exiftool` yerine `sudo port install p5-image-exiftool`.

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

**1. Python'u kurun**

[python.org/downloads](https://www.python.org/downloads/) üzerinden Python 3.10+
indirin. Kurulum ekranında **"Add python.exe to PATH"** kutucuğunu mutlaka işaretleyin.

**2. ExifTool'u kurun** (üç seçenekten biri)

- **Chocolatey ile** (yönetici olarak PowerShell'de):
  ```powershell
  choco install exiftool
  ```
- **Scoop ile**:
  ```powershell
  scoop install exiftool
  ```
- **Manuel**: [exiftool.org](https://exiftool.org/) sayfasından "Windows Executable"
  zip'ini indirin, içindeki `exiftool(-k).exe` dosyasını `exiftool.exe` olarak yeniden
  adlandırıp `C:\Windows\` gibi PATH'te olan bir klasöre kopyalayın, ya da dosyanın
  bulunduğu klasörü sistem PATH değişkenine ekleyin (`Ayarlar › Sistem › Gelişmiş
  sistem ayarları › Ortam Değişkenleri`).

**3. Projeyi kurun** (PowerShell)

```powershell
git clone https://github.com/gorkemguler/metascout.git
cd metascout
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

> PowerShell betik çalıştırmayı engelliyorsa (`.venv\Scripts\Activate.ps1
> dosyası çalıştırılamıyor` hatası), yönetici olmadan bir kez şunu çalıştırın:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Klasik `cmd.exe` kullanıyorsanız etkinleştirme komutu: `.venv\Scripts\activate.bat`

### Kurulumu doğrulama

Hangi platformda olursanız olun, sanal ortam etkinken:

```bash
exiftool -ver
metascout scan --help
```

İkisi de hatasız sürüm/yardım metni basıyorsa kurulum tamam.

> **Dikkat:** Yukarıdaki `pip install -e .` komutu `metascout` komutunu yalnızca
> o an aktif olan `.venv` sanal ortamına kurar. Yeni bir terminal açtığınızda ya
> da proje klasörünün dışındayken `metascout` çalıştırırsanız `zsh: command not
> found: metascout` / `'metascout' is not recognized...` hatası alırsınız.
> Bu bir bozukluk değil, venv'in aktif olmamasından kaynaklanır. Çözüm için aşağıya
> bakın veya her seferinde `source .venv/bin/activate` çalıştırın.

### Global kurulum (pipx)

Her terminalde venv aktive etmeden, sisteminizin her yerinden `metascout`
komutunu çalıştırmak isterseniz [pipx](https://pipx.pypa.io/) kullanın:
paketi kendi izole ortamına kurar ama komutu PATH'e ekler.

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

`pipx ensurepath` çalıştırdıktan sonra **terminali yeniden başlatın** (ya da
`exec zsh` / `exec bash` çalıştırın), ardından proje klasöründen kurun:

```bash
pipx install --editable /tam/yol/metascout
```

`--editable` sayesinde `src/metascout/` altında yapılan kod değişiklikleri
yeniden kurmaya gerek kalmadan otomatik yansır. Kurulumdan sonra `metascout`
komutu hangi dizinde olursanız olun, venv aktive etmeden çalışır.

## Hızlı başlangıç

```bash
metascout scan example.com
```

Varsayılan olarak site taraması (`crawl`) ve `sitemap.xml` kullanılır, API
anahtarı gerekmez. Sonuçlar `./metascout_output/report.html` ve `report.json`
dosyalarına yazılır.

```bash
metascout scan example.com \
  --filetypes pdf,docx,xlsx \
  --max-docs 100 \
  --max-crawl-pages 500 \
  --output-dir ./out
```

## Çoklu hedef taraması

Bir kuruma ait birden fazla domaini tek seferde tarayıp **tek bir raporda**
birleştirebilirsiniz. Arka arkaya çalıştırıp raporları elle birleştirmenize
gerek kalmaz:

```bash
metascout scan example.com example.org another-example.net
```

Domain sayısı fazlaysa bir dosyaya yazıp `--targets-file` ile de verebilirsiniz
(satır başına bir domain, `#` ile başlayan satırlar yok sayılır):

```bash
cat > domains.txt <<EOF
# Acme Corp domainleri
example.com
example.org
another-example.net
EOF

metascout scan --targets-file domains.txt --subdomains
```

Üretilen `report.html`/`report.json` içinde, birden fazla hedef verildiğinde
her domain için ayrı ayrı kaç belge bulunduğunu gösteren bir **"Targets"**
tablosu da yer alır.

## Manuel URL listesiyle tarama

Bir keşif motoru sizde çalışmadıysa (API engellendi, kota bitti, ne olursa)
ve tarayıcıdan aramayla, başka bir araçla ya da herhangi bir yerden elle bir
belge URL listesi topladıysanız, bunu doğrudan `--urls-file` ile verin. Bu
URL'ler için keşif atlanır; motorların bulduğu her şey gibi indirilip
analiz edilir ve rapora eklenir:

```bash
cat > urls.txt <<EOF
# elle toplandı, google motoru reddetti
https://example.com/reports/2023-annual.pdf
https://example.com/files/internal-notes.docx
EOF

metascout scan --urls-file urls.txt
```

`--urls-file` kullanıldığında TARGETS'i atlayabilirsiniz — bu URL'lerin
host'ları otomatik olarak hedef sayılır (rapor başlığı ve hedef bazlı
dökümde kullanılır). Normal keşfi de manuel listeyle birlikte çalıştırmak
isterseniz TARGETS veya `--targets-file` de verebilirsiniz; sonuçlar URL'ye
göre birleştirilip tekilleştirilir, yani bir motorun zaten bulduğu bir belge
manuel dosyanızda da varsa raporda iki kez görünmez. Web arayüzünde de aynı
alan "Manuel URL listesi" olarak mevcuttur.

## Web arayüzü

Terminale komut yazmak yerine tarayıcıdan form doldurarak taramak isterseniz:

```bash
metascout web
```

Bu, `http://127.0.0.1:8765/` adresinde yerel bir arayüz açar (tarayıcınızda
otomatik açılır), varsayılan olarak İngilizce — sağ üstteki **TR**'ye
tıklayarak tüm sayfayı Türkçe'ye çevirebilirsiniz (`EN`/`TR`, doğrudan
`?lang=tr` ile de erişilebilir). Hedefleri (birden fazla, her satıra bir
tane), opsiyonel manuel URL listesini (bkz. [Manuel URL listesiyle tarama](#manuel-url-listesiyle-tarama)
— hedefleri boş bırakırsanız URL'lerden otomatik çıkarılır), dosya
uzantılarını, keşif motorlarını, subdomain seçeneğini ve rapor dilini
(İngilizce/Türkçe, sayfanın kendi dilinden bağımsız) forma girip "Taramayı
başlat"a basmanız yeterli. Tarama bitince sonuç raporu doğrudan tarayıcıda
açılır; ayrıca `--output-dir` altına (varsayılan `./metascout_output/web-<tarih>/`)
`report.html`/`report.json` olarak da kaydedilir.

```bash
metascout web --port 9000 --output-dir ~/MetaScout-Calisma/metascout_output
```

Arayüz yalnızca `127.0.0.1` üzerinde dinler (`--host` ile değiştirilebilir).
İnternete açık bırakmayın. `google`/`serper`/`brave` motorlarını forma işaretlemek
için ilgili API anahtarlarının ortam değişkeni ya da `.env` üzerinden tanımlı
olması gerekir (bkz. [Arama motoru API anahtarları](#arama-motoru-api-anahtarları-opsiyonel)).

## Wayback Machine keşfi

`wayback` motoru (varsayılan olarak açık, API anahtarı gerekmez) [Wayback
Machine](https://web.archive.org)'in CDX Server API'sini sorgulayarak
archive.org'un hedef host için şimdiye kadar arşivlediği **tüm** belgeleri
bulur — sonradan kaldırılmış, linki koparılmış ya da artık erişilemeyen
dosyalar dahil. Bu, canlı siteyi taramanın asla bulamayacağı eski raporları,
taslakları veya iç belgeleri ortaya çıkarabilir.

```bash
metascout scan example.com --engines wayback
```

Tam olarak verdiğiniz host'a odaklıdır (diğer motorlar gibi otomatik
subdomain genişletmesi yapmaz — bunun için `--subdomains` kullanın). Eğer
`web.archive.org` ağınızdan erişilemiyorsa (bazı servis sağlayıcılar
engelliyor), motor sadece o host için sonuç döndürmez; taramanın geri kalanı
etkilenmez.

Her sonuç, canlı sitedeki **orijinal URL**'i ile raporlanır — crawl,
sitemap ya da bir dork motorunun aynı dosya için raporlayacağı URL ile
birebir aynı — böylece birden fazla motorun bulduğu bir belge raporda iki
kez değil, tek seferde görünür. Orijinal URL genelde tam olarak "artık
olmayan" şey olduğu için, MetaScout arka planda gerçek archive.org
anlık görüntü adresini de tutar ve orijinal URL'den indirme başarısız
olursa otomatik olarak oradan indirir.

## Subdomain taraması

`--subdomains` ile [crt.sh](https://crt.sh) (Certificate Transparency log arama,
API anahtarı gerekmez) üzerinden pasif subdomain keşfi yapılır; bulunan her
subdomain de aynı belge-keşif motorlarıyla (crawl/sitemap/google/serper/brave) taranır:

```bash
metascout scan example.com --subdomains --max-subdomains 30
```

`crt.sh` bazen yavaş veya rate-limit'li yanıt verebilir; bu durumda tarama
sessizce boş subdomain listesiyle devam eder, ana domain taraması etkilenmez.

## Arama motoru API anahtarları (opsiyonel)

`google`, `serper` ve `brave` motorları klasik FOCA tarzı `site:hedef filetype:pdf`
dork aramaları yapar; bunlar için API anahtarı gerekir:

```bash
cp .env.example .env
# .env dosyasına GOOGLE_API_KEY, GOOGLE_CSE_ID ve/veya BRAVE_API_KEY girin
```

Anahtarları girdiğinizde `google`/`serper`/`brave` motorları **ayrıca bir şey yapmanıza
gerek kalmadan** otomatik devreye girer (CLI'de varsayılan `--engines`
listesine eklenir, web arayüzünde ilgili kutucuk otomatik işaretlenir).
`--engines` ile elle motor seçerseniz bu otomatik davranış geçersiz olur, o
zaman istediğiniz motorları kendiniz listelemeniz gerekir.

> **Güvenlik notu:** `.env` zaten [.gitignore](.gitignore)'da, yani bu repo
> klasöründe tutsanız bile normal `git add .` ile commit'e girmez. Yine de en
> güvenli yöntem, gerçek anahtarlarınızı **git deposunun dışındaki ayrı bir
> klasörde** tutmaktır, örn. `~/metascout-calisma/.env`. `metascout`'u
> [pipx ile global kurarsanız](#global-kurulum-pipx), `metascout scan` komutu
> hangi klasörden çalıştırılırsa o klasördeki `.env`'i okur; böylece kaynak kod
> deposuna hiç dokunmadan taramalarınızı çalıştırabilirsiniz.

- **Google**: [Programmable Search Engine](https://programmablesearchengine.google.com/)
  üzerinden bir arama motoru oluşturun (tüm web'i arayacak şekilde ayarlayın) ve
  [Custom Search JSON API](https://developers.google.com/custom-search/v1/overview)
  için bir API anahtarı alın. Ücretsiz kota günde 100 sorgu.

  Kota yetmiyorsa `GOOGLE_API_KEY`'e **virgülle ayırarak birden fazla anahtar**
  girebilirsiniz (farklı Google Cloud projelerinden, aynı `GOOGLE_CSE_ID`'yi
  paylaşan anahtarlar): `GOOGLE_API_KEY=anahtar1,anahtar2,anahtar3`. Bir
  anahtarın kotası biterse tarama otomatik olarak bir sonrakine geçer.

  > ⚠️ **Google bu API'yi 1 Ocak 2027'de tamamen kapatıyor** ve şu anda **yeni
  > oluşturulan Google Cloud projelerini zaten reddediyor** — konsolda API
  > "etkin" görünse bile `403 PERMISSION_DENIED` hatası alıyorsanız (yeni bir
  > proje/anahtarsa) bu sizin ayarınızdan değil, Google'ın yeni müşteri
  > kısıtlamasından kaynaklanıyor, düzeltilecek bir şey yok. Aşağıdaki
  > **Serper**'a geçin.
- **Serper**: [serper.dev](https://serper.dev) üzerinden ücretsiz bir hesap açın
  ve API anahtarınızı alın. Google'ın kendi API'si gibi resmi bir Google ürünü
  değil, ama **gerçek Google arama sonuçlarını** JSON olarak döndüren üçüncü
  taraf bir servis — Google API'sinin yerini almak için önerilen yol budur.
  Kayıt olunca ücretsiz kredi tanımlanıyor; güncel miktarı ve fiyatlandırmayı
  [serper.dev](https://serper.dev) üzerinden kontrol edin, zamanla değişebilir.
- **Brave**: [brave.com/search/api](https://brave.com/search/api/) üzerinden bir
  abonelik (ücretsiz "Data for AI" katmanı dahil) oluşturup `X-Subscription-Token`
  anahtarınızı alın.

```bash
metascout scan example.com --engines crawl,sitemap,wayback,google,serper,brave
```

## Tüm CLI seçenekleri

```bash
metascout scan --help
metascout web --help
```

`metascout scan` bir veya daha fazla `TARGET` pozisyonel argümanı alır
(`metascout scan a.com b.com`); alternatif olarak `--targets-file`:

| Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `--targets-file` | – | Satır başına bir domain/URL içeren dosya (`#` yorum) |
| `--urls-file` | – | Satır başına bir tam belge URL'i içeren, keşfi atlayıp doğrudan taranacak dosya (`#` yorum) |
| `--filetypes` | `pdf,doc,docx,xls,xlsx,ppt,pptx,odt,ods,odp` | Aranacak dosya uzantıları |
| `--engines` | `crawl,sitemap` (+`google`/`serper`/`brave` ilgili API anahtarı `.env`'de varsa otomatik eklenir) | `crawl,sitemap,wayback,google,serper,brave` arasından virgülle liste |
| `--subdomains` / `--no-subdomains` | kapalı | crt.sh ile subdomain keşfi |
| `--max-subdomains` | `20` | Taranacak azami subdomain sayısı |
| `--max-docs` | `50` | İndirilip analiz edilecek azami belge sayısı |
| `--max-crawl-pages` | `200` | Crawler'ın host başına gezeceği azami sayfa sayısı |
| `--max-crawl-depth` | `3` | Crawler'ın azami link derinliği |
| `--concurrency` | `8` | Eşzamanlı indirme sayısı |
| `--timeout` | `15` | İstek başına saniye cinsinden zaman aşımı |
| `--max-download-mb` | `50` | Belge başına azami indirme boyutu (MB) |
| `--output-dir` | `./metascout_output` | Çıktı klasörü |
| `--ignore-robots` | kapalı | `robots.txt`'i yok say (yalnızca açık izniniz varsa) |
| `--google-api-key`, `--google-cse-id`, `--serper-api-key`, `--brave-api-key` | – | Ortam değişkeni veya `.env` ile de verilebilir |
| `--json-report` / `--no-json-report` | açık | JSON rapor üretimi |
| `--html-report` / `--no-html-report` | açık | HTML rapor üretimi |
| `--report-lang` | `en` | HTML rapor dili: `en` veya `tr` |

`metascout web` seçenekleri:

| Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `--host` | `127.0.0.1` | Yalnızca yerel, internete açmayın |
| `--port` | `8765` | Dinlenecek port |
| `--output-dir` | `./metascout_output` | Taramaların kaydedileceği klasör |
| `--open-browser` / `--no-open-browser` | açık | Başlarken tarayıcıyı otomatik aç |

## Çıktı yapısı

```
metascout_output/
├── downloads/               indirilen ham belgeler (metascout scan)
├── report.html              görsel özet rapor (metascout scan)
├── report.json              otomasyon/entegrasyon için ham bulgular (metascout scan)
└── web-20260101-120000/     her metascout web taraması kendi zaman damgalı klasörüne yazılır
    ├── downloads/
    ├── report.html
    └── report.json
```

## Mimari

```
src/metascout/
├── discovery/
│   ├── crawler.py         doğrudan site taraması (robots.txt uyumlu)
│   ├── sitemap.py         sitemap.xml / sitemap index ayrıştırma
│   ├── wayback.py         Wayback Machine (archive.org) CDX API keşfi
│   ├── search_engines.py  Google/Serper/Brave dork araması
│   └── subdomains.py      crt.sh üzerinden pasif subdomain keşfi
├── downloader.py           eşzamanlı indirme, boyut sınırı, sha256
├── metadata/
│   ├── exiftool_wrapper.py exiftool subprocess sarmalayıcısı
│   └── analyzer.py         regex + alan bazlı bulgu çıkarımı + hedef bazlı sayım
├── report/
│   ├── html_report.py      Jinja2 tabanlı HTML rapor (report_en/report_tr.html.jinja)
│   └── json_report.py      JSON rapor
├── pipeline.py              discover → download → extract → analyze akışı (CLI ve web'in ortak motoru)
├── cli.py                   click tabanlı `metascout scan` / `metascout web` komutları
└── web.py                   Flask tabanlı yerel web arayüzü
```

## Test

```bash
pip install -e . pytest
pytest
```

## Sorun giderme

**`zsh: command not found: metascout`** (veya PowerShell'de `'metascout' is not recognized...`)
`metascout` komutu, kurulumu yaptığınız `.venv` sanal ortamına özeldir; sanal
ortam aktif değilken herhangi bir terminalden çağrılamaz. İki çözüm:
1. Proje klasörüne gidip venv'i aktive edin: `cd /proje/yolu && source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`)
2. Ya da [pipx ile global kurulum](#global-kurulum-pipx) yaparak komutu her yerden kullanılabilir hale getirin.

**`exiftool not found on PATH`**
ExifTool kurulu değil ya da PATH'te değil. [Kurulum](#kurulum) bölümündeki
platformunuza uygun adımı izleyin, ardından `exiftool -ver` ile doğrulayın.

**Windows'ta `exiftool(-k).exe` çalışıyor ama `exiftool` çalışmıyor**
İndirdiğiniz zip'teki dosya adı `exiftool(-k).exe`. Bunu `exiftool.exe` olarak
yeniden adlandırmanız ve PATH'te bir klasöre koymanız gerekiyor (yukarıdaki
Windows kurulum adımlarına bakın).

**`No documents discovered`**
Hedefte seçtiğiniz uzantılarda (varsayılan: `pdf,doc,docx,...`) herkese açık
belge yok, ya da `robots.txt` crawler'ı engelliyor olabilir. `--engines
crawl,sitemap,wayback,google,serper,brave` ile daha geniş kapsam deneyin ya da (yalnızca
yetkiniz varsa) `--ignore-robots` kullanın.

**crt.sh yanıt vermiyor / yavaş**
Servis zaman zaman rate-limit uygular; tarama sessizce boş subdomain listesiyle
devam eder. Birkaç dakika sonra tekrar deneyin.

**`Google`/`Serper`/`Brave` motoru "skipped" uyarısı veriyor**
İlgili API anahtarı/CSE id tanımlı değil. [Arama motoru API anahtarları](#arama-motoru-api-anahtarları-opsiyonel)
bölümüne bakın.

## Etik kullanım

Bu araç yalnızca **kendi sisteminiz** veya **yazılı izniniz olan** hedefler için
tasarlanmıştır. Varsayılan olarak `robots.txt` kurallarına uyar ve isteklerinde
kendini gizlemeyen dürüst bir User-Agent (`MetaScout/0.1`) gönderir. Yani hedef
site operatörü recon trafiğini loglarında görüp isterse engelleyebilir.
İzniniz olmayan sistemlere karşı kullanmak yasa dışı olabilir; sorumluluk
tamamen kullanıcıya aittir.

## Lisans

[MIT](LICENSE) © 2026 Görkem Güler
