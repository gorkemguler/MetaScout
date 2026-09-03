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
- [REST API](#rest-api-opsiyonel)
- [Docker](#docker)
- [Wayback Machine keşfi](#wayback-machine-keşfi)
- [Anahtarsız arama: DDGS](#anahtarsız-arama-ddgs)
- [Subdomain taraması](#subdomain-taraması)
- [Kişisel veri (PII) içerik taraması](#kişisel-veri-içerik-taraması-opsiyonel)
  - [Görsel (ıslak) imza tespiti](#görsel-ıslak-imza-tespiti--deneysel-ayrıca-opsiyonel)
  - [Taranmış belgeler için OCR](#taranmış-belgeler-için-ocr)
- [Kritik / hassas dosya keşfi](#kritik--hassas-dosya-keşfi-opsiyonel)
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
- **GPS koordinatları**, konum bilgisi içeren bir fotoğraf (ör. bir
  belgeye yapıştırılmış telefon fotoğrafı) belgeye gömülüyse — raporda
  haritada görüntüleme linki de sunulur

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
- **İsteğe bağlı belge *içerik* taraması** kişisel/kritik veri için — TC kimlik
  no, e-posta/telefon, IBAN/kredi kartı no, adres/doğum tarihi ipuçları ve
  imza ipuçları — her zaman açık olan metadata taramasının üzerine (bkz.
  [Kişisel veri (PII) içerik taraması](#kişisel-veri-içerik-taraması-opsiyonel))
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

Varsayılan olarak site taraması (`crawl`), `sitemap.xml`, [Wayback
Machine](#wayback-machine-keşfi) ve [DDGS](#anahtarsız-arama-ddgs) kullanılır
— hiçbiri için API anahtarı gerekmez. Sonuçlar `./metascout_output/report.html`
ve `report.json` dosyalarına yazılır.

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
başlat"a basmanız yeterli. Tarama çalışırken, düğmenin altındaki canlı log
kutusu terminaldeki ile aynı ilerleme satırlarını (bulunan belgeler,
sorgulanan motorlar, içerik taraması/görsel imza ilerlemesi, ...)
server-sent events ile akıtır — böylece uzun bir tarama sadece dönen bir
spinner arkasında donmuş gibi görünmez. Tarama bitince sonuç raporu
doğrudan tarayıcıda açılır, sağ üstte bir **"Sonuçları indir (.zip)"**
butonuyla — o taramanın `report.html`, `report.json` ve indirilen her
belgesini tek bir zip'te toplar, böylece tam çıktıyı kendi makinenize
almak için `metascout web`'in gerçekte çalıştığı yere dosya sistemi
erişimi gerekmez. Aynı dosyalar olduğu gibi `--output-dir` altına da
(varsayılan `./metascout_output/web-<tarih>/`) kaydedilir.

```bash
metascout web --port 9000 --output-dir ~/MetaScout-Calisma/metascout_output
```

Arayüz varsayılan olarak yalnızca `127.0.0.1` üzerinde dinler (`--host`
ile değiştirilebilir). `google`/`serper`/`brave` motorlarını forma
işaretlemek için ilgili API anahtarlarının ortam değişkeni ya da `.env`
üzerinden tanımlı olması gerekir (bkz. [Arama motoru API
anahtarları](#arama-motoru-api-anahtarları-opsiyonel)).

> ⚠️ **Bunun hiç kimlik doğrulaması yok, hiç.** Kendi makinenizde tek
> kişi için sorun değil (varsayılan kullanım). Bir ekip tek bir örneği
> paylaşsın diye `metascout web --host 0.0.0.0` çalıştırmak isterseniz:
> doğrudan yapmayın — buna erişebilen herkes (kendi seçtiği herhangi bir
> hedefe karşı, sizin sunucunuzu/IP'nizi kullanarak) tarama başlatabilir
> ve `--scan-content` kullanılmışsa gerçek PII içerenler dahil, başka
> herkesin tarama sonuçlarını indirebilir. Birden fazla güvenilir kişinin
> erişmesine izin vermeden önce, gerçekten kullanıcı doğrulayan bir şeyin
> arkasına koyun — basic auth'lu bir reverse proxy, sadece
> Tailscale/WireGuard üzerinden erişim, SSO destekli bir gateway gibi.

**"Mevcut Belgeleri Tara"** (üst navigasyon) farklı bir durum için ikinci,
ayrı bir sayfa: zaten belgeleriniz var — kendi dosyalarınız ya da başka bir
şekilde topladıklarınız — ve sadece analiz edilmelerini istiyorsunuz, hedef
yok, keşif yok. Ya bir yerel dizin yolu (özyinelemeli aranır) ya da bir URL
listesi (doğrudan indirilir, keşif yok) verin, artı isteğe bağlı içerik
taraması ve görsel imza kontrolleri, ana form ile aynı. Bunu bilerek ayrı
bir sayfada tuttuk, ana forma sıkıştırmak yerine — çünkü ana form zaten daha
fazla tarama seçeneği eklendikçe okunması zorlaşıyordu.

**"Geçmiş"** (üst navigasyon) `--output-dir` altında kayıtlı her önceki
çalıştırmayı listeler (hem `metascout scan`/`local-scan` çalıştırmaları hem
web UI çalıştırmaları — aynı `report.json`/`report.html` dosyalarını
yazdıkları için) — hedef(ler), belge sayısı ve tarih, en yeniden eskiye —
raporu yeniden açmak için bir "Raporu görüntüle" linki ve "İndir (.zip)"
linki ile birlikte, böylece geçmiş sonuçlara `metascout web`'in gerçekte
çalıştığı yere dosya sistemi erişimi gerekmeden, sadece tarayıcıdan
ulaşılabilir.

İki veya daha fazla çalıştırma olduğunda, Geçmiş sayfasında ayrıca bir
**"İki çalıştırmayı karşılaştır"** formu vardır: daha eski ve daha yeni bir
çalıştırma seçin, aralarında tam olarak ne değişmiş görün — yeni/kaldırılmış
belgeler, kategoriye göre yeni/kaldırılmış metadata bulguları,
yeni/kaldırılmış içerik taraması sonuçları. Bir hedefi zaman içinde takip
etmek için: periyodik olarak tarayın (her seferinde kendi zaman damgalı
çıktı dizinine, varsayılan davranış budur) ve neyin değiştiğini görmek için
iki çalıştırmayı karşılaştırın. Aynı karşılaştırma, tarayıcı olmadan
doğrudan CLI'dan da kullanılabilir:

```bash
metascout diff metascout_output/web-20260101-100000 metascout_output/web-20260201-100000
```

## REST API (opsiyonel)

Yukarıdaki CLI ve web arayüzü, elle tarama yapan bir insan içindir.
`metascout api`, bunun yerine bir *programın* bunu yapması için üçüncü,
ayrı bir arayüz — kendi uygulamanızdan/pipeline'ınızdan bir tarama başlatın,
durumunu sorgulayın, sonucu (JSON rapor, HTML rapor, ya da tüm çalıştırmanın
zip'i) gerçekten istediğiniz yere aktarın: bir SIEM'e, bir talebe (ticket),
dahili bir dashboard'a, zamanlanmış bir işe — entegrasyon neyi
gerektiriyorsa.

```bash
pip install 'metascout[api]'
metascout api
```

Bu, `http://127.0.0.1:8000` üzerinde bir REST API başlatır — etkileşimli,
otomatik üretilmiş dokümantasyonla (Swagger UI) birlikte,
`http://127.0.0.1:8000/docs` adresinde: her istek/yanıt alanı, doğrudan
tarayıcıdan denenebilir, elle senkron tutulacak ayrı bir API referansı yok.
`/openapi.json`, aynısını makine tarafından okunabilir bir şema olarak verir
— kurumsal uygulamanızın kullandığı dilde bir istemci üretmek için.

**İş (job) tabanlıdır**, tek bir bloklayan çağrı değil: bir tarama saniyeler
ile saatler arasında herhangi bir sürebilir, bu yüzden `POST /v1/scans`
tüm çalıştırma boyunca HTTP bağlantısını açık tutmak yerine hemen bir
`job_id` ile döner — `status` `"done"` (ya da `"error"`) olana kadar `GET
/v1/scans/{job_id}`'yi sorgulayın, sonra sonucu al.

```bash
# Tarama başlat
curl -s -X POST http://127.0.0.1:8000/v1/scans \
  -H 'Content-Type: application/json' \
  -d '{"targets": ["example.com"], "scan_content": true, "critical_files": true}'
# -> {"job_id": "…", "status": "queued", "links": {...}, ...}

# Bitene kadar sorgula
curl -s http://127.0.0.1:8000/v1/scans/<job_id>

# status "done" olunca:
curl -s http://127.0.0.1:8000/v1/scans/<job_id>/report.json
curl -s http://127.0.0.1:8000/v1/scans/<job_id>/report.html
curl -s -o result.zip http://127.0.0.1:8000/v1/scans/<job_id>/download
```

| Endpoint | Açıklama |
|---|---|
| `GET /v1/health` | Canlılık kontrolü + versiyon + o an çalışan/kuyrukta job sayısı |
| `POST /v1/scans` | Tarama başlatır — `metascout scan` ile aynı seçenekler (targets/manual_urls, filetypes, engines, scan_content, critical_files, ...) bir JSON gövde olarak |
| `POST /v1/local-scans` | Sunucudaki yerel bir dizinin ya da sabit bir URL listesinin taramasını başlatır — `metascout local-scan` ile aynı |
| `GET /v1/scans` | Job'ları listeler (en yeniden eskiye), güncel durumlarıyla |
| `GET /v1/scans/{job_id}` | Bir job'ın durumu, zaman damgaları ve bitince bir bulgu özeti |
| `GET /v1/scans/{job_id}/log` | O ana kadar toplanan ilerleme log satırları (hâlâ çalışırken de işler) |
| `GET /v1/scans/{job_id}/report.json` | Tam JSON rapor — henüz bitmemişse 409 |
| `GET /v1/scans/{job_id}/report.html` | Tam HTML rapor — henüz bitmemişse 409 |
| `GET /v1/scans/{job_id}/download` | Tüm çalıştırmanın zip'i (raporlar + indirilen belgeler) — henüz bitmemişse 409 |

`metascout api` seçenekleri:

| Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `--host` | `127.0.0.1` | Başka makinelerden bağlantı kabul etmek için `0.0.0.0` kullanın — önce aşağıdaki uyarıyı okuyun |
| `--port` | `8000` | Dinlenecek port |
| `--output-dir` | `./metascout_output` | Her job'ın `report.json`/`report.html`/`downloads/`'unun kaydedileceği yer (job başına bir alt klasör, CLI/web arayüzüyle aynı düzen) |
| `--max-workers` | `2` | Aynı anda gerçekten çalışan azami tarama sayısı; fazlası kuyruğa girip sırasını bekler |

Job takibi (durum, devam eden log satırları) **sadece bellekte** tutulur —
sunucu yeniden başlatıldığında kaybolur. Bitmiş bir job'ın
`report.json`/`report.html`'i yine de `--output-dir` altına diskte güvenle
yazılır, tam olarak CLI/web arayüzündeki gibi — bu yüzden bir yeniden
başlatma asla **tamamlanmış** bir sonucu kaybettirmez, sadece o an
kuyrukta/çalışmakta olan işlerin canlı durumunu.

> ⚠️ **Kimlik doğrulama yerleşik değil**, [Web arayüzü](#web-arayüzü) ve
> [Docker](#docker) imajıyla aynı duruş: kendi makinenizde ya da güvenilir
> bir ağın içinde olduğu gibi sorun değil, ama buna erişebilen herkes
> sunucunuzu kullanarak seçtiği herhangi bir hedefe karşı tarama
> başlatabilir ve `--scan-content` kullanılmışsa PII dahil her job'ın
> sonucunu çekebilir. Güvenilir bir ağ dışından herhangi bir şeyin
> erişmesine izin vermeden önce, çağıranları gerçekten doğrulayan bir şeyin
> arkasına koyun — API key'li ya da mTLS'li bir reverse proxy, sadece
> Tailscale/WireGuard üzerinden erişim, bir API gateway. `--host 0.0.0.0`
> tek başına **hiçbir** kimlik doğrulama eklemez.

**Canlı uçtan uca doğrulandı**: `metascout api`'yi gerçekten çalıştırdım
(sadece FastAPI'nin process-içi test istemcisine karşı değil), sahte bir
AWS anahtarı içeren `.env` bulunan bir dizin için HTTP üzerinden bir
local-scan job'ı `POST`ladım, `GET /v1/scans/{job_id}`'yi `"done"`'a kadar
sorguladım, ve anahtarın `report.json`'da doğru şekilde maskelenmiş
geldiğini doğruladım — artı `report.html`, zip indirme, ve `/docs`'taki
Swagger UI'ın hepsi gerçek bir tarayıcıda kontrol edildi.

## Docker

Python/ExifTool/ImageMagick/Ghostscript'i elle kurmadan web arayüzünü
(ya da yukarıdaki [REST API](#rest-api-opsiyonel)'yi) çalıştırmak için, ya da
kendi bilgisayarınız dışında bir yere koymak
istiyorsanız:

```bash
git clone https://github.com/gorkemguler/metascout.git
cd metascout
docker build -t metascout .
docker run --rm -p 127.0.0.1:8765:8765 -v "$(pwd)/metascout_output:/data" metascout
```

Bu, konteyneri ön planda çalıştırır (`--rm` durduğu an — ör. Ctrl+C ile —
konteyneri siler) — denemek için iyi. Arka planda sürekli çalışsın,
çökerse ya da makine yeniden başlarsa kendiliğinden geri gelsin
istiyorsanız, `--rm`'i kaldırıp yerine `-d --restart unless-stopped`
ekleyin:

```bash
docker run -d --name metascout --restart unless-stopped \
  -p 127.0.0.1:8765:8765 -v "$(pwd)/metascout_output:/data" metascout
```

Ya da repoda hazır bulunan `docker-compose.yml` ile (`restart:
unless-stopped` zaten ayarlı) — aynı şekilde arka planda çalıştırmak için
`-d` ekleyin:

```bash
docker compose up -d --build
```

> `--restart unless-stopped`, Docker'ın kendisi tekrar çalışmaya
> başladığında *konteynerin* geri gelmesini sağlar — Docker'ın kendisinin
> önyüklemede (boot) başlamasını sağlamaz. Bu, projenin dışında bir kerelik
> bir ayar: Docker Desktop'ta "Start Docker Desktop when you sign in"
> tercihi var (macOS/Windows); Linux'ta `sudo systemctl enable docker`
> daemon için aynısını yapar. Bunu bir kez yaptıktan sonra, yukarıdaki
> konteyner yeniden başlatma politikası her reboot'ta işi devralır.

Her iki yöntemde de, konteyner çalıştıktan sonra kendi makinenizde
`http://localhost:8765` adresinden web arayüzüne ulaşırsınız, ve her
taramanın çıktısı (`report.html`, `report.json`, `downloads/`) volume
mount sayesinde host'ta `./metascout_output` içine düşer — konteyner
yeniden başlasa bile kalıcıdır, ve konteynere `docker exec` girmeden
erişilebilir.

İmaj **her şeyi** paketliyor, isteğe bağlı `content-scan` ve
`visual-signature` eklentileri dahil (ImageMagick + Ghostscript de
içeride) — konteyner içinde ayrı bir `pip install` adımı gerekmiyor.
Bu gerçek bir ödünleşim: imaj, sade bir `pip install metascout`'tan
belirgin şekilde daha büyük (bu ikisinin neden gerçekten ağırlık
kattığı için bkz. [Görsel (ıslak) imza
tespiti](#görsel-ıslak-imza-tespiti--deneysel-ayrıca-opsiyonel)), ama
karşılığında gerçekten kutudan çıktığı gibi çalışıyor.

API anahtarları (`GOOGLE_API_KEY`, `SERPER_API_KEY`, `BRAVE_API_KEY`, ...)
projenin başka her yerindeki gibi çalışır — `.env.example`'ı `.env`'e
kopyalayıp elinizdekileri doldurun, sonra ya `docker run`'a `--env-file .env`
verin ya da `docker-compose.yml`'deki `env_file:` satırının yorumunu kaldırın.

> ⚠️ **[Web arayüzü](#web-arayüzü) bölümündeki uyarının aynısı, burada
> tekrarlamaya değer çünkü insanların `--host 0.0.0.0`'a en çok
> başvurduğu yer tam olarak Docker:** bu imajda hiç kimlik doğrulama yok.
> Yukarıdaki `docker run`/compose örnekleri, yayınlanan portu bilerek
> host'ta `127.0.0.1`'e bağlıyor — sadece konteyneri çalıştıran makineden
> erişilebilir. Bunu başkalarının erişmesi gereken bir yere (paylaşılan
> bir sunucu, bulut VM'i) koyuyorsanız, önce kimlik doğrulayan bir
> reverse proxy koyun; portu doğrudan `0.0.0.0`'a ya da genel bir arayüze
> yayınlamayın. Kimlik doğrulamasız bir örneğe erişebilen herkes, sizin
> sunucunuzu kullanarak seçtiği herhangi bir hedefe karşı tarama
> başlatabilir ve önceki her taramanın sonucunu indirebilir — `--scan-content`
> kullanıldıysa PII dahil.

Aynı imajın içine `api` eki de gömülü — web arayüzü yerine REST API'yi
çalıştırmak için `CMD`'yi geçersiz kılın:

```bash
docker run --rm -p 127.0.0.1:8000:8000 -v "$(pwd)/metascout_output:/data" metascout \
  api --host 0.0.0.0 --port 8000 --output-dir /data
```

Bkz. yukarıdaki [REST API](#rest-api-opsiyonel) — orada da aynı "host'ta
`127.0.0.1`'e bağla, daha fazla açmadan önce kimlik doğrulayan bir proxy
koy" uyarısı geçerli.

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

## Anahtarsız arama: DDGS

`ddgs` motoru, [DDGS](https://pypi.org/project/ddgs/) adlı Python kütüphanesini
kullanıyor — DuckDuckGo'yu (ve varsayılan `auto` modunda yedek olarak
Bing, Brave, Google, Yandex gibi başka motorları) kazıyarak `site:`/`filetype:`
sonuçlarını **hiçbir API anahtarı ya da hesap olmadan** getiriyor:

```bash
metascout scan example.com --engines ddgs
```

Diğer anahtarsız motorlardan (`wayback`, `crawl`, `sitemap`) farklı olarak bu
bir kazıyıcı, resmi bir API değil — bu yüzden buradaki en kırılgan seçenek
(prensipte): sonuçlar DDGS geliştiricilerinin her motorun bot-koruma
önlemlerine karşı o an neyi çalışır durumda tuttuğuna bağlı, ve yoğun
kullanımda hız sınırına takılabilir. Pratikte testlerde hızlı ve güvenilir
çıktı (gerçek bir hedefte ~2 saniyede 26 gerçek PDF, art arda çalıştırmalarda
hatasız), bu yüzden **varsayılan** motor setinde. Bir kazıyıcıya bağımlı
olmak istemiyorsanız `--engines`'ten çıkarın (ya da web arayüzünde işaretini
kaldırın).

DDGS'in hangi motor(lar)ı sorgulayacağını `--ddgs-backend` ile seçebilirsiniz
(varsayılan `auto`; `duckduckgo`, `google`, `bing` gibi tek bir motor ya da
sırayla denenecek virgülle ayrılmış bir liste de verilebilir). Özellikle
`--ddgs-backend google`, `google_dork_search` ve Serper'in de kullandığı
gerçek Google arama sonuçlarını **hiç API anahtarı olmadan** verir. Motor,
DDGS'in tek-sayfa sınırını aşmak için her filetype için birden fazla sonuç
sayfasını dener (başarısız sayfalarda yeniden deneme/backoff ile), ama
Google'ın botlara karşı savunması buna gerçekte ciddi direnç gösteriyor:
aynı gerçek hedefe karşı tekrarlanan canlı testlerde, sayfalama olmadan tek
sayfada 26 sonuç bulunurken, sayfalama açıkken ~300 gerçek sonuçtan 50 ile
114 arası (bazen de motor geçici olarak bloke olduğunda 0) sonuç elde
edildi. `ddgs`+`google`'ı, ücretsiz ve kurulum gerektirmeyen bir kısmi
örnekleme/tek seferlik sorgu çözümü olarak görün — `serper`'in ya da
Google'ın (yakında kapatılacak) kendi API'sinin yerine geçen hacimli/eksiksiz
bir çözüm olarak değil (bkz. [Arama motoru API
anahtarları](#arama-motoru-api-anahtarları-opsiyonel)). Aynı alan web
arayüzünde "DDGS motoru" olarak sunulur.

## Subdomain taraması

`--subdomains` ile [crt.sh](https://crt.sh) (Certificate Transparency log arama,
API anahtarı gerekmez) üzerinden pasif subdomain keşfi yapılır; bulunan her
subdomain de aynı belge-keşif motorlarıyla (crawl/sitemap/google/serper/brave) taranır:

```bash
metascout scan example.com --subdomains --max-subdomains 30
```

`crt.sh` bazen yavaş veya rate-limit'li yanıt verebilir; bu durumda tarama
sessizce boş subdomain listesiyle devam eder, ana domain taraması etkilenmez.

## Kişisel veri içerik taraması (opsiyonel)

Yukarıdakilerin hepsi belge **metadata**'sını tarar (yazar, yazılım, dosya
yolları — exiftool'un çıkardığı etiketler). `--scan-content` daha ileri gider
ve her indirilen belgenin gerçek **gövde metnini** okuyup kişisel/kritik veri
arar:

| Kategori | Ne tespit eder | Güvenilirlik |
|---|---|---|
| `tc_kimlik` | TC kimlik numaraları | Yüksek — checksum ile doğrulanır (geçersiz numaralar elenir) |
| `email_phone` | E-postalar (regex) ve telefon numaraları ([`phonenumbers`](https://pypi.org/project/phonenumbers/) ile — Google'ın libphonenumber portu, küresel, sadece TR değil) | Telefon için yüksek (kütüphane doğrulamalı) |
| `iban_card` | IBAN'lar (sadece Türkiye değil, tüm ISO 13616 ülkeleri) ve kart numaraları | Yüksek — mod-97 (IBAN) / Luhn (kart) checksum doğrulamalı |
| `address_dob` | Adres benzeri ve doğum-tarihi-benzeri metin kalıpları | **Düşük** — regex sezgisi, yanlış pozitif bekleyin |
| `signature` | Metinde "imza"/"signature"/"signed by" gibi anahtar kelimeler, **ve** PDF'in gerçek bir kriptografik imza alanı (`/Sig`) olup olmadığı | Anahtar kelime bulguları ipucudur, kanıt değil; yapısal `/Sig` kontrolü güvenilirdir |
| `secrets` | Belge gövdesinde sızmış kimlik bilgileri: AWS access key, Google API anahtarı, GitHub/Slack/Stripe token'ları, PEM private key blokları, DB bağlantı string'leri (`postgres://user:pass@host`), JWT'ler | Yüksek — genel entropy skorlaması yerine bilinen sağlayıcıların gerçek anahtar *formatlarına* karşı eşleştirilir, bu yüzden sadece bilinen formatları yakalar |
| `infra` | Belge gövdesinde sızmış altyapı bilgisi: cloud storage/paylaşım linkleri (S3, GCS, Azure Blob, Drive, Dropbox, SharePoint), ve iç ağ topolojisi — RFC 1918 özel IP'ler ve `.local`/`.internal`/`.corp`/`.lan` hostname'leri | Orta — eşleşen link/IP gerçek, ama varlığı kaynağın gerçekten yanlış yapılandırılmış/açık olduğunu kanıtlamaz; yine de elle kontrol gerekir |

Varsayılan kapalı, isteğe bağlı ve sezgiseldir — her bulgu **elle
doğrulanması** gereken bir şeydir, metadata bulgusu gibi kesin bir sızıntı
değil.

```bash
pip install 'metascout[content-scan]'   # tek seferlik: pypdf + phonenumbers kurar
metascout scan example.com --scan-content
# ya da bir alt küme:
metascout scan example.com --scan-content --content-categories tc_kimlik,iban_card
```

Aynı anahtar ve kategori kutucukları web arayüzünde de mevcuttur, "Belge
içeriğinde kişisel/kritik veri taraması (PII)" altında — varsayılan
işaretsiz. Ek paketi kurmadan etkinleştirirseniz tarama yine de çalışır ve
hangi bağımlılığın eksik olduğunu loglar, tamamen durmaz; PDF metin
çıkarımı ve telefon numarası tespiti özellikle `pypdf` ve `phonenumbers`
gerektirir, geri kalanı (Office/OpenDocument metin çıkarımı, e-posta/TC
no/IBAN/kart regex'i, imza anahtar kelimeleri) onlar olmadan da çalışır.

**Raporda gizlilik:** daha kritik kategoriler tespit anında maskelenir — bir
TC kimlik no `123******78` olarak, bir kart numarası `************1111`
olarak, bir IBAN sadece ilk/son 4 karakteri görünecek şekilde gösterilir —
böylece rapor ve JSON çıktısı gerçek değerlerin düz metin deposu haline
gelmez. E-posta/telefon ve zayıf sinyalli adres/doğum tarihi ipuçları
bulundukları haliyle gösterilir, çünkü onları göstermenin amacı zaten bu.

Metin çıkarımı PDF (`pypdf` ile), `.docx`/`.xlsx`/`.pptx` ve
`.odt`/`.ods`/`.odp` formatlarını kapsar. Eski ikili Office formatları
(`.doc`/`.xls`/`.ppt`) desteklenmez — çok daha ağır bir bağımlılık
(`olefile`) gerektirir, görece nadir kazanımlar için, bu yüzden atlanır
(bu formatlarda metadata taraması normal şekilde çalışmaya devam eder).

### Görsel (ıslak) imza tespiti — DENEYSEL, ayrıca opsiyonel

Yukarıdaki her şey, `signature` kategorisi dahil, sadece belgenin **metnini**
görür — gövdede "signed by" gibi bir kelime, ya da PDF'in `/Sig` alanı.
Hiçbiri, **hiç metin katmanı olmayan, sadece el yazısı imza içeren taranmış
bir sayfayı** yakalayamaz. `--visual-signature` bunu ekliyor: her sayfayı
görüntüye çevirip [`signature-detect`](https://github.com/EnzoSeason/signature_detection)
sezgisel görüntü işleme hattını (parlaklık eşikleme → bağlı bölge çıkarımı →
aspect-ratio/piksel-yoğunluk değerlendirmesi) çalıştırarak el yazısı imza
şeklindeki mürekkep lekelerini işaretliyor.

Bu, bilerek **iki bağımsız seviyede** opsiyonel yapıldı, ve — `signature`
metin/anahtar-kelime kategorisinin aksine — **`--scan-content` gerektirmiyor**;
içerik taramasının geri kalanıyla ya da onsuz çalışan kendi başına bir
anahtar:

```bash
pip install 'metascout[visual-signature]'
metascout scan example.com --visual-signature
```

1. Sadece `pip install 'metascout[visual-signature]'` yapmak **hiçbir şey
   değiştirmez** — gerçekten çalıştırmak için yine de komutta
   `--visual-signature` (ya da web arayüzünde ilgili kutucuk) gerekir.
2. Projenin geri kalanından gerçekten daha ağır bir bağımlılık. pip paketinin
   üstüne, **sistemde kurulu ImageMagick ve Ghostscript** gerektiriyor
   (Wand, ImageMagick'i çağırıyor, o da PDF rasterizasyonunu Ghostscript'e
   devrediyor) — canlı doğrulandı: Ghostscript olmadan doğrudan
   `DelegateError` ile başarısız oluyor. Normal kuruluma ek olarak ~150–250MB
   native kütüphane bekleyin.

**Bunu sonradan, ayrıca çalıştırın.** Bu kontrol yeterince yavaş (aşağıya
bakın) ki çoğu taramanın onu beklemesi mantıklı değil. `metascout
visual-signature-scan`, normal bir taramanın zaten indirdiği belgeler
üzerinde, ayrıca ve sonradan çalışır — tekrar keşif ya da tekrar indirme
yok:

```bash
metascout scan example.com                          # hızlı, her zamanki gibi
metascout visual-signature-scan ./metascout_output   # yavaş, ne zaman isterseniz
```

Verilen çıktı dizinindeki `report.json`'ı okur, başarıyla indirilmiş her
belgeyi kontrol eder, bir sonuç tablosu basar ve yanına
`visual_signature_report.json` yazar.

**Canlı test sonuçları (gerçek veri kümesi, DENEYSEL statü doğrulandı):**
yetkili bir tarama sırasında toplanan 162 gerçek PDF'e karşı (form belgeleri,
duyurular ve finansal raporlar) çalıştırıldı; süre nedeniyle durdurulmadan
önce ilk 76'sı işlendi:

| | Sayı |
|---|---|
| Görsel imza içerdiği işaretlenen | 26 (%34) |
| İçermediği işaretlenen | 50 (%66) |
| Çalışma zamanı hatası | 0 |

İşaretlenen belgelerden bir örneklemi elle inceledim (gerçek dosya
adları/hedef burada belirtilmiyor — bu proje hangi belgenin kime ait
olduğunu yayınlamıyor) ve **her iki sonucu da** buldum: gerçek bir şirket
kaşesi ve el yazısı imza içeren bir belge doğru işaretlendi, ama iki
tamamen boş form şablonu da işaretlendi — biri yazdırılmış "İmza:"
etiketi ve kutucuk-ızgara kenarları yüzünden, diğeri bir logo ve çapraz
bir filigran yüzünden. Bu, tam olarak yukarıdaki "sezgisel, elle
doğrulayın" uyarısının anlattığı türden bir yanlış pozitif —
**her bulguyu bakılması gereken bir şey olarak görün, doğrulanmış bir
imza olarak değil.**

**Aynı çalışmada ölçülen süre**: bir saniyenin çok altından, tek bir büyük
çok-sayfalı finansal rapor için **131 saniyeye** kadar değişiyor, ağırlıklı
olarak Ghostscript'in sayfa başına 200 DPI'da PDF rasterizasyonundan
kaynaklanıyor. 76 belgelik örneklem toplam yaklaşık 1 saat 21 dakika sürdü
— buna göre bütçeleyin, ve büyük bir taramanın tamamında
`--visual-signature` kullanmak yerine seçilmiş bir alt kümede
`visual-signature-scan` kullanmayı tercih edin.

Açmadan önce bilmekte fayda var:

- Üst kaynak proje **Ekim 2022'den beri bakımsız**, ve şu anki
  scikit-image'da zaten bir `FutureWarning` tetikliyor (burada bastırıldı,
  ama algoritmanın bağımlılıklarının eskidiğine dair gerçek bir sinyal).
- Tespit sezgisel ve parametre-hassas: varsayılan aspect-ratio penceresi çok
  geniş/yassı imza şekillerini reddediyor, yani gerçek imzalar tarama
  kalitesine ve imza tarzına göre kaçırılabilir — canlı sentetik test
  görüntüleriyle doğrulandı (kompakt, imza-şeklinde bir mürekkep izi doğru
  işaretlendi; aynı iz daha geniş gerilince işaretlenmedi).
- Kontrol hiç çalışamazsa (bağımlılık eksik, Ghostscript eksik, bozuk dosya)
  bu "doğrulanamadı" olarak ele alınır, "imza yok" olarak değil — o sayfa
  için rapora hiçbir şey eklenmez, yanlış-negatif bir bulgu olarak
  raporlanmaz.
- ImageMagick/Ghostscript'i `exiftool` ile aynı şekilde kurun:
  `brew install imagemagick ghostscript` (macOS),
  `apt install imagemagick ghostscript` (Debian/Ubuntu), ya da
  [imagemagick.org](https://imagemagick.org/script/download.php#windows) ve
  [ghostscript.com](https://www.ghostscript.com/releases/gsdnld.html)
  adreslerindeki resmi Windows kurulum dosyaları.

### Taranmış belgeler için OCR

`--scan-content`'in PII/secret/altyapı tespiti PDF'in gerçek metin
katmanını okur — **taranmış** bir sayfanın (bir kimlik fotokopisi, fotoğrafı
çekilmiş ya da tarayıcıdan geçirilmiş imzalı bir sözleşme) genelde hiç metin
katmanı yoktur, bu yüzden içerik taraması bu tür belgelere tamamen kördü.
`pip install 'metascout[ocr]'` bunu çözer: bir sayfanın çıkarılan metni
~20 karakterin altına düşerse (gerçekten neredeyse-boş değil, taranmış
olduğuna dair güçlü bir sinyal), o sayfa görüntüye çevrilip
[Tesseract](https://github.com/tesseract-ocr/tesseract) OCR ile taranır ve
sonuç normal metinle aynı dedektörlere beslenir.

```bash
pip install 'metascout[ocr]'
metascout scan example.com --scan-content   # ekstra bayrak yok — OCR otomatik devreye girer
```

Ayrı bir CLI bayrağı yok: bu, ek paket (artı sistemde kurulu Tesseract,
ImageMagick ve Ghostscript — [görsel imza
tespiti](#görsel-ıslak-imza-tespiti--deneysel-ayrıca-opsiyonel)'yle aynı
rasterizasyon tekniği) kullanılabilir olduğunda otomatik çalışır. Değilse,
taranmış sayfalar OCR desteği eklenmeden önceki gibi basitçe atlanır —
her iki durumda da hiçbir şey bozulmaz.

**Canlı uçtan uca doğrulandı**: gerçek metin içeren ama hiç metin katmanı
olmayan sentetik bir taranmış PDF oluşturdum (pypdf'in kendi çıkarımı boş
döndü), OCR'dan geçirdim, ve görüntüye gömülü checksum-doğrulamalı bir TC
kimlik numarası doğru şekilde bulunup işaretlendi. Bunun dürüst bir
sınırını da doğruladım: OCR metni gürültülü, aynı testteki bir e-posta
adresi araya sıkışan bir boşlukla geri geldi (`jane.doe @example.com`),
bu da e-posta regex'ini atlatmaya yetti — OCR kaynaklı bulguları, hiçbir
şey bulamamaya göre gerçek bir iyileşme olarak görün, gerçek bir metin
katmanınınki kadar güvenilir değil.

## Kritik / hassas dosya keşfi (opsiyonel)

Yukarıdaki her şey — `--filetypes`, dork arama dahil — *belge* türlerini
(pdf/doc/docx/...) arar. `--critical-files`, aynı motorlar üzerinden ikinci,
bağımsız bir keşif geçişi çalıştırır — ama bu sefer sadece var olup
indekslenmiş olmalarıyla bile sızıntı sayılabilecek düz metin/config tarzı
dosyalar için: açıkta kalmış bir `.env`, bir debug `.log`, unutulmuş bir
`.sql`/`.bak` dökümü.

```bash
metascout scan example.com --critical-files
```

Varsayılan uzantılar: `txt,log,conf,cfg,ini,env,yml,yaml,sql,bak` —
`--critical-file-types` ile değiştirilebilir. Varsayılan kapalı; bulunan
dosyalar normal belgeler listesine karışmadan kendi **"Kritik / Hassas
Dosyalar"** rapor bölümünde listelenir (ve risk rozetine katkıda bulunur) —
buradaki bulgu, dosyanın herkese açık erişilebilir olmasının kendisidir,
içinde ne bulunduğundan bağımsız. `--scan-content` ile birlikte kullanınca,
bu dosyaların içerdiği metinde de aynı sızmış kimlik bilgisi/PII
tarayıcılarını (bkz. yukarıdaki [İçerik
taraması](#kişisel-veri-içerik-taraması-opsiyonel)) çalıştırır — artık
PDF/Office dosyaları yerine düz metne yönelik olarak:

```bash
metascout scan example.com --critical-files --scan-content --content-categories secrets,infra
```

`metascout local-scan DIRECTORY --critical-files` aynısını yerel olarak
yapar: `DIRECTORY` altında `--critical-file-types`'a uyan dosyalar,
`--filetypes`'a uyan belgelerden ayrı listelenir — bir dosyanın uzantısı her
iki listede de olsa çift saymadan. Web arayüzünde de hem ana tarama
formunda hem "Mevcut Belgeleri Tara" sayfasında karşılık gelen
**"Kritik/hassas dosyaları da ara"** onay kutusu var.

**Canlı uçtan uca doğrulandı**: içinde `AWS_ACCESS_KEY_ID=AKIA...` geçen bir
`.env` ve iç bir hostname'den bahseden bir `.log` içeren yerel bir test
dizini — her iki dosya da "Kritik / Hassas Dosyalar" altında (boyut ve
durumuyla) çıktı, `--scan-content` açıkken AWS anahtarı doğru şekilde
maskelendi (`AKIA****...`) ve iç hostname, tıpkı bir PDF'de olacağı gibi
İçerik Taraması altında işaretlendi. Web arayüzü üzerinden de doğrulandı:
sadece kritik dosya içeren, normal belge içermeyen bir dizin bile "analiz
edilecek bir şey yok" eski çıkmazına düşmeden, risk rozeti dahil tam bir
rapor üretiyor.

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
metascout scan example.com --engines crawl,sitemap,wayback,google,serper,brave,ddgs
```

## Tüm CLI seçenekleri

```bash
metascout scan --help
metascout web --help
metascout api --help
metascout local-scan --help
metascout visual-signature-scan --help
metascout diff --help
```

`metascout scan` bir veya daha fazla `TARGET` pozisyonel argümanı alır
(`metascout scan a.com b.com`); alternatif olarak `--targets-file`:

| Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `--targets-file` | – | Satır başına bir domain/URL içeren dosya (`#` yorum) |
| `--urls-file` | – | Satır başına bir tam belge URL'i içeren, keşfi atlayıp doğrudan taranacak dosya (`#` yorum) |
| `--filetypes` | `pdf,doc,docx,xls,xlsx,ppt,pptx,odt,ods,odp` | Aranacak dosya uzantıları |
| `--engines` | `crawl,sitemap,wayback,ddgs` (+`google`/`serper`/`brave` ilgili API anahtarı `.env`'de varsa otomatik eklenir) | `crawl,sitemap,wayback,google,serper,brave,ddgs` arasından virgülle liste |
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
| `--ddgs-backend` | `auto` | `ddgs` motoru için motor(lar), ör. `duckduckgo`, `google`, `bing` ya da virgülle ayrılmış liste |
| `--scan-content` / `--no-scan-content` | kapalı | Belge gövde metnini de PII için tarar (bkz. [Kişisel veri içerik taraması](#kişisel-veri-içerik-taraması-opsiyonel)); `pip install 'metascout[content-scan]'` gerekir |
| `--content-categories` | `tc_kimlik,email_phone,iban_card,address_dob,signature,secrets,infra` | Virgülle ayrılmış alt küme, sadece `--scan-content` ile kullanılır |
| `--visual-signature` / `--no-visual-signature` | kapalı | **DENEYSEL**, `--scan-content`'ten bağımsız: görsel (görüntü tabanlı) imza tespiti; yavaş (bkz. [yukarıda](#görsel-ıslak-imza-tespiti--deneysel-ayrıca-opsiyonel)), `pip install 'metascout[visual-signature]'` + ImageMagick + Ghostscript gerektirir |
| `--critical-files` / `--no-critical-files` | kapalı | Düz metin/config tarzı dosyalar için ikinci keşif geçişi (bkz. [yukarıda](#kritik--hassas-dosya-keşfi-opsiyonel)) |
| `--critical-file-types` | `txt,log,conf,cfg,ini,env,yml,yaml,sql,bak` | Virgülle ayrılmış alt küme, sadece `--critical-files` ile kullanılır |
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

`metascout api` seçenekleri — bkz. yukarıdaki [REST API](#rest-api-opsiyonel):

| Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `--host` | `127.0.0.1` | Başka makinelerden bağlantı kabul etmek için `0.0.0.0` kullanın — önce yukarıdaki uyarıyı okuyun |
| `--port` | `8000` | Dinlenecek port |
| `--output-dir` | `./metascout_output` | Her job'ın rapor/indirmelerinin kaydedileceği yer |
| `--max-workers` | `2` | Aynı anda çalışan azami tarama sayısı |

`metascout local-scan DIRECTORY` — `DIRECTORY`'de (özyinelemeli aranır)
zaten bulunan belgeleri analiz eder: keşif yok, indirme yok, sadece
metadata çıkarımı artı istediğiniz opsiyonel kontroller. Web arayüzünün
"Mevcut Belgeleri Tara" sayfasının CLI karşılığı — canlı bir hedef değil,
zaten sahip olduğunuz bir belge klasörü için. (Terminalden URL-listesi
karşılığı için: `metascout scan --urls-file urls.txt --engines ""` —
hedef/`--targets-file` gerekmez, hostname'ler URL'lerden çıkarılır ve
`--engines` boş olduğu için keşif çalışmaz.)

```bash
metascout local-scan ~/Downloads/raporlar --scan-content --visual-signature
```

`metascout scan` ile aynı `--filetypes`, `--scan-content`,
`--content-categories`, `--visual-signature`, `--critical-files`,
`--critical-file-types`, `--json-report`/`--html-report`, `--report-lang` ve
`--output-dir` seçeneklerini alır (yukarıdaki tabloya bakın).

`metascout visual-signature-scan REPORT_DIR` — **DENEYSEL** görsel imza
kontrolünü (bkz. [yukarıda](#görsel-ıslak-imza-tespiti--deneysel-ayrıca-opsiyonel))
önceki bir taramanın belgelerine karşı, tekrar keşif ya da indirme
yapmadan çalıştırır:

```bash
metascout visual-signature-scan --help
```

| Argüman/Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `REPORT_DIR` | – | Bir taramanın çıktı dizini (`report.json` içerir), ör. `./metascout_output` ya da bir `web-YYYYMMDD-HHMMSS` klasörü |
| `--json-out` | `REPORT_DIR/visual_signature_report.json` | Sonuçların yazılacağı yer |

`metascout diff RUN_A RUN_B` — iki önceki tarama çalıştırmasını karşılaştırır
ve aralarında neyin yeni, neyin kaybolmuş olduğunu yazdırır (belgeler,
metadata bulguları, içerik taraması sonuçları). Bkz. [Web arayüzü](#web-arayüzü)
altındaki **"İki çalıştırmayı karşılaştır"** paragrafı.

```bash
metascout diff --help
```

| Argüman/Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `RUN_A` | – | Daha eski çalıştırmanın çıktı dizini (`report.json` içerir) |
| `RUN_B` | – | Daha yeni çalıştırmanın çıktı dizini (`report.json` içerir) |
| `--json-out` | – | Opsiyonel: tam karşılaştırmayı JSON olarak da bu yola yazar |

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
│   ├── ddgs_search.py     anahtarsız DDGS (DuckDuckGo/diğer motorlar) dork araması
│   └── subdomains.py      crt.sh üzerinden pasif subdomain keşfi
├── downloader.py           eşzamanlı indirme, boyut sınırı, sha256
├── metadata/
│   ├── exiftool_wrapper.py exiftool subprocess sarmalayıcısı
│   └── analyzer.py         regex + alan bazlı bulgu çıkarımı + hedef bazlı sayım
├── content_scan/            isteğe bağlı belge *içerik* PII taraması (--scan-content)
│   ├── text_extract.py     PDF (pypdf) / Office / OpenDocument metin çıkarımı
│   ├── pii_patterns.py     TC no/IBAN/kart checksum doğrulayıcıları, e-posta/telefon/doğum tarihi/adres/imza regex'i
│   ├── signature.py        PDF dijital imza (/Sig alanı) yapısal kontrolü
│   ├── visual_signature.py  opsiyonel görüntü-tabanlı imza tespiti (--visual-signature)
│   └── ocr.py               taranmış PDF sayfaları için opsiyonel OCR fallback (kurulunca otomatik)
├── report/
│   ├── html_report.py      Jinja2 tabanlı HTML rapor (report_en/report_tr.html.jinja)
│   └── json_report.py      JSON rapor
├── diff.py                  iki report.json çıktısını karşılaştırır (yeni/kaldırılmış belge, bulgu, içerik sonucu)
├── api/                      opsiyonel REST API servisi (`metascout api`), web.py'dan ayrı
│   ├── app.py               FastAPI uygulaması + route'lar (job tabanlı: POST başlatır, GET sorgular/getirir)
│   ├── jobs.py               bellek-içi job kaydı + pipeline'ı çalıştıran arka plan thread havuzu
│   └── schemas.py            Pydantic istek/yanıt modelleri (otomatik üretilen /docs'u da besler)
├── pipeline.py              discover → download → extract → analyze akışı (CLI, web ve api'nin ortak motoru)
├── cli.py                   click tabanlı `scan` / `web` / `api` / `local-scan` / `visual-signature-scan` / `diff` komutları
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
crawl,sitemap,wayback,google,serper,brave,ddgs` ile daha geniş kapsam deneyin ya da (yalnızca
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
