# Quantfury Scanner

> ABD + Avrupa (DAX/CAC/Swiss) + Asya ADR'leri için **long/short** sinyal tarayıcı.
> Mevcut AlphaBot'un sinyal motorunu kullanır, GitHub Actions'ta ücretsiz çalışır,
> Gmail'e mail atar. Sen Quantfury'de **manuel** açarsın.

## Mimari

```
GitHub Actions cron (her 30 dk, hafta içi)
        ↓
    scanner.py
        ↓
  yfinance batch download (40 sembol, 1h bar, 60 gün)
        ↓
  Bull/Bear skor motoru (RSI + MACD + SuperTrend + EMA + Hacim)
        ↓
  Dedupe (aynı sembol+yön için 4 saat bekle)
        ↓
  Gmail SMTP → mailbox
```

**Maliyet: 0 USD.** GitHub Actions ücretsiz tier'a sığıyor (public repo'da limitsiz, private repo'da aylık 2000 dk — bu scanner ayda ~30 dk kullanır).

## Dosya yapısı

```
quantfury_scanner/
├── .github/workflows/scan.yml    # Cron + iş akışı
├── config.py                      # Evren + eşikler
├── indicators.py                  # RSI/MACD/SuperTrend + skor motoru
├── notifier.py                    # Gmail SMTP + HTML email
├── scanner.py                     # Ana giriş noktası
├── requirements.txt
├── .gitignore
└── README.md
```

## Kurulum (10 dakika)

### 1. Repo oluştur

GitHub'da yeni bir repo aç (public öneririm — Actions dakika limiti yok). Bu klasörü
içine kopyala ve push'la.

```bash
cd quantfury_scanner
git init
git add .
git commit -m "initial scanner"
git remote add origin git@github.com:KULLANICI/quantfury-scanner.git
git push -u origin main
```

### 2. Gmail App Password al

Bot şifresi (gerçek Gmail şifren değil):

1. [myaccount.google.com/security](https://myaccount.google.com/security) → 2 adımlı doğrulamayı aktif et
2. [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) → yeni şifre oluştur
3. Uygulama adı "Quantfury Scanner" yaz → 16 haneli şifreyi kopyala

### 3. GitHub secret'larını ekle

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret name | Değer |
|---|---|
| `SMTP_USER` | `your_email@gmail.com` |
| `SMTP_PASS` | 16 haneli app password (boşluksuz) |
| `SMTP_TO`   | mail alacak adres (kendin olabilir) |

### 4. Actions'ı aktif et

Repo → **Actions** sekmesi → "I understand my workflows, go ahead and enable them"

İlk run'ı manuel test et:
**Actions** → "Quantfury Scanner" → **Run workflow** → main → **Run workflow**

Birkaç dakika içinde tamamlanır. Yeşil tik = başarılı. Yüksek skorlu sinyal varsa
mailine düşer.

## Lokal test

GitHub'a push'lamadan önce:

```bash
cd quantfury_scanner
pip install -r requirements.txt

# Email göndermeden tara (sadece konsol çıktısı)
python scanner.py --dry-run

# Gerçek email — env değişkenleri lazım
export SMTP_USER=your@gmail.com
export SMTP_PASS="16hanelisifre"
export SMTP_TO=your@gmail.com
python scanner.py
```

## Çalışma takvimi

| Saat (TSİ)      | Saat (UTC)   | Hangi piyasalar açık                                |
|-----------------|--------------|-----------------------------------------------------|
| 10:00 – 18:30   | 07:00 – 15:30| DAX, CAC, AEX, SMI (yaz)                            |
| 16:30 – 23:00   | 13:30 – 20:00| ABD (yaz)                                           |
| 17:30 – 18:30   | 14:30 – 15:30| Çakışma — hem ABD hem Avrupa                        |

Scanner Pzt–Cum 10:00 TSİ – 00:30 TSİ arası her 30 dk çalışır. GitHub Actions
yoğun saatlerde 10–30 dk gecikebilir; 1h bar'la çalıştığımız için kritik değil.

> ⚠ Avrupa hisselerinin son barı seans kapandıktan sonra güncellenmez. Akşam saat
> 19:00 TSİ'den sonra DAX sinyalleri "günün barı" üzerinden hesaplanır — bu
> yarınki aç için bir görüş verir, anlık tetik için değil.

## Sinyal mantığı

Mevcut botundaki skor sistemi aynen taşındı:

| İndikatör          | Max puan | Şart                                       |
|--------------------|----------|--------------------------------------------|
| RSI                | 30       | <25 (long) / >75 (short) en güçlü          |
| MACD crossover     | 35       | Taze geçiş 35, mevcut yön 15               |
| SuperTrend         | 20       | Yön                                        |
| EMA 20/50 hizalama | 10       | Tam hizalama 7, yarım 3                    |
| Hacim momentum     | 5        | Son bar > 1.8x ortalama                    |
| **EMA200 filtresi**| -15      | Trende ters sinyali cezalandırır           |

Toplam Bull veya Bear puanından **güven skoru (40–99)** hesaplanır. **65 ve üzeri**
mail atılır. Aynı sembolde aynı yön için **4 saat** içinde tekrar mail atılmaz
(dedupe). Yön değiştiyse her zaman tetiklenir.

## Evreni düzenleme

`config.py` → `UNIVERSE` listesini düzenle. Format yfinance ile aynı:

- ABD: `AAPL`, `NVDA`, `SPY`
- DAX: `SAP.DE`, `BMW.DE`, `RHM.DE`
- Paris: `MC.PA`, `OR.PA`
- Amsterdam: `ASML.AS`
- Zürih: `NESN.SW`
- Londra: `SHEL.L`, `AZN.L`
- Milano: `RACE.MI`
- Asya ADR'leri (ABD listeli): `BABA`, `TSM`, `JD`

> 💡 İpucu: Çok büyük evren = çok gürültü. 30–45 sembol ideal. Skoru sıkı tutarsan
> günde 1–3 yüksek kaliteli sinyal gelir, bu da senin "manuel ben açacağım"
> akışına uygun.

## Eşik ayarları

`config.py`:

```python
MIN_CONFIDENCE = 65    # Daha katı: 70-75 → daha az ama daha güçlü sinyal
DEDUPE_HOURS = 4       # Daha uzun: 8 → daha az tekrar mail
BAR_INTERVAL = "1h"    # "30m" daha çok sinyal, "1d" daha az ve daha güvenilir
```

## Sorun giderme

**"Gmail authentication failed"** → 2FA açık değil ya da regular password kullandın.
App Password lazım, [link](https://myaccount.google.com/apppasswords).

**"yfinance returned empty"** → yfinance bazen geçici timeout veriyor. Bir dahaki
cron tetiklemesinde toparlar. Sürekli oluyorsa sembol formatını kontrol et
(`.DE` küçük harf olmaz, büyük olmalı).

**Mail gelmiyor ama Actions yeşil** → Spam klasörüne bak; ilk maillerde Gmail
"Quantfury Scanner" göndericisini güvenli işaretlemen lazım.

**GitHub Actions cron geç çalışıyor** → Normal. Free tier yoğun saatlerde 10–30
dk gecikir. Acil sinyaller için Telegram'a geçmek istersen `notifier.py`'ye
Telegram bot eklenir, 5 dk'lık bir iş.

## Geliştirme yol haritası

- [ ] Birden fazla zaman dilimi (1h sinyal + 1d trend teyidi)
- [ ] News filter (sinyalin geldiği günde major haber varsa skor düşür)
- [ ] Backtest modu — son 90 günde bu kurallar ne kazandırırdı?
- [ ] Quantfury'de hangi sembollerin **şu anda işlem yapılabilir** olduğunu
  kontrol eden filtre (manuel liste)
- [ ] Telegram bildirim opsiyonu

## Disclaimer

Eğitim ve karar-destek amaçlıdır. Otomatik emir yok, finansal tavsiye değil.
Her sinyali Quantfury'de açmadan önce grafik üzerinde teyit et.
