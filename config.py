"""
Quantfury Scanner — Konfigürasyon
Evren, eşikler ve veri parametreleri tek yerden.
"""

# ─────────────────────────────────────────────────────────────────────────────
# TARAMA EVRENİ
# ─────────────────────────────────────────────────────────────────────────────
# Quantfury'de işlem açabileceğin enstrümanlar. Sembol formatı = yfinance.
# Yerel Avrupa hisseleri: .DE (Frankfurt), .PA (Paris), .AS (Amsterdam),
#                          .SW (Zürih), .L (Londra), .MI (Milano)
# Asya ADR'leri ABD borsalarında işlem gördüğü için suffix yok.

UNIVERSE = [
    # ── Öncelikli izleme listesi (uzun süredir takip ediyorsun) ────────────
    "GLD", "GDX", "ASML", "NVDA", "TSM", "GEV", "CCJ", "CEG", "NEE",

    # ── ABD mega-cap ───────────────────────────────────────────────────────
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA", "AMD", "AVGO", "NFLX",

    # ── ABD geniş endeks & sektör ETF'leri ─────────────────────────────────
    "SPY", "QQQ", "IWM", "XLE", "XLF", "XLK", "XBI", "SMH",

    # ── ABD spekülatif / crypto-bağlantılı ─────────────────────────────────
    "PLTR", "COIN", "MSTR", "HOOD", "SOFI",

    # ── Asya ADR'leri (ABD listeli, USD bazlı) ─────────────────────────────
    "BABA", "JD", "PDD", "NIO", "BIDU",

    # ── DAX (Frankfurt) ────────────────────────────────────────────────────
    "SAP.DE", "SIE.DE", "ALV.DE", "BMW.DE", "MBG.DE", "BAS.DE", "RHM.DE",

    # ── Paris (CAC) ────────────────────────────────────────────────────────
    "MC.PA",   # LVMH
    "OR.PA",   # L'Oréal
    "AIR.PA",  # Airbus
    "TTE.PA",  # TotalEnergies

    # ── Amsterdam / İsviçre / Diğer Avrupa ─────────────────────────────────
    "ASML.AS",
    "NESN.SW", "NOVN.SW", "ROG.SW",
]

# ─────────────────────────────────────────────────────────────────────────────
# SİNYAL EŞİKLERİ
# ─────────────────────────────────────────────────────────────────────────────
MIN_CONFIDENCE = 65       # Bu skorun altındaki sinyaller mail atılmaz
MIN_BARS = 60             # Bu kadar bar gelmeyen sembol atlanır
DEDUPE_HOURS = 4          # Aynı sembol+yön için tekrar mail göndermeden bekle

# Yön değişimi her zaman tetikler (LONG iken SHORT geldi → bildirim atılır)

# ─────────────────────────────────────────────────────────────────────────────
# VERİ
# ─────────────────────────────────────────────────────────────────────────────
BAR_INTERVAL = "1h"       # 1h = swing/intraday için doğru denge
BAR_PERIOD = "60d"        # ~390 bar → EMA200 dahil tüm indikatörler stabil

# ─────────────────────────────────────────────────────────────────────────────
# İNDİKATÖR PARAMETRELERİ (mevcut botunla aynı)
# ─────────────────────────────────────────────────────────────────────────────
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ST_PERIOD = 10
ST_MULT = 3.0
ATR_PERIOD = 14
