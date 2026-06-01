#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
 SİNYAL KALİTESİ / FORWARD-RETURN ANALİZİ
═══════════════════════════════════════════════════════════════════════════════
Soru: compute_signal'ın ürettiği sinyaller gerçekten lehte hareketten ÖNCE mi
geliyor? Yoksa gürültüye mi ateş ediyor?

Yöntem:
  • Her sembol için geçmiş barları indir.
  • İndikatör serilerini BİR KEZ hesapla (compute_signal ile aynı calc_* fonksiyonları).
  • Bar bar ilerle; her barda compute_signal'ın skorlama mantığını AYNEN uygula.
  • Sinyal çıktıysa: 1 / 4 / 8 / 24 bar sonra fiyat ne yaptı? (yöne göre getiri)
  • İsabet oranı (hit rate), ortalama getiri, MFE/MAE (max lehte/aleyhte hareket).
  • MIN_CONFIDENCE'ı 60→90 süpür: isabet vs sinyal sayısı eğrisi.

LOOKAHEAD YOK: karar bar i'deki kapanışla verilir, sonuç bar i+k'dan ölçülür.
ÖZ-KONTROL: son barda bu script'in skoru ile gerçek compute_signal eşleşmeli;
            eşleşmezse uyarı basar (skorlama kopyası bozulmuş demektir).

Çalıştırma:
  python backtest.py
  python backtest.py --csv signals.csv      # tüm sinyalleri CSV'ye yaz
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
import argparse
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from config import UNIVERSE, DEDUPE_HOURS, BAR_INTERVAL
from indicators import (
    calc_rsi, calc_macd, calc_supertrend, calc_ema, calc_atr, compute_signal, MIN_BARS,
)

try:
    import yfinance as yf
except ImportError:
    print("❌ pip install yfinance")
    sys.exit(1)


# ── Ayarlar ──────────────────────────────────────────────────────────────────
BACKTEST_PERIOD = "730d"            # 1h için yfinance üst sınırı
HORIZONS = [1, 4, 8, 24]            # kaç bar sonrasına bakılacak
THRESHOLDS = [60, 65, 70, 75, 80, 85, 90]
MFE_MAE_WINDOW = 24                 # MFE/MAE bu pencere içinde ölçülür

# Dedupe'u bar cinsine çevir (1h bar varsayımı). Aynı sembol+yön bu kadar bar
# içinde tekrar sayılmaz → örnekler daha bağımsız olur, canlı davranışı yansıtır.
def _bars_per_hour(interval: str) -> float:
    interval = interval.strip().lower()
    if interval.endswith("h"):
        return 1.0 / float(interval[:-1] or 1)
    if interval.endswith("m"):
        return 60.0 / float(interval[:-1] or 1)
    if interval.endswith("d"):
        return 1.0 / (6.5 * float(interval[:-1] or 1))
    return 1.0

COOLDOWN_BARS = max(1, int(round(DEDUPE_HOURS * _bars_per_hour(BAR_INTERVAL))))


# ── Skorlama (compute_signal'dan BİREBİR kopya, skalar girişlerle) ─────────────
def score_at(r, h_now, h_prev, sd, c, c_prev, e20, e50, e200, vol_now, avg_v):
    if pd.isna(r) or pd.isna(h_now) or pd.isna(e50):
        return None
    bull = 0; bear = 0
    # RSI (30)
    if r < 25:    bull += 30
    elif r < 35:  bull += 20
    elif r < 45:  bull += 10
    elif r > 75:  bear += 30
    elif r > 65:  bear += 20
    elif r > 55:  bear += 10
    # MACD (35)
    if h_now > 0 and h_prev <= 0:   bull += 35
    elif h_now > 0:                  bull += 15
    elif h_now < 0 and h_prev >= 0: bear += 35
    elif h_now < 0:                  bear += 15
    # SuperTrend (20)
    if sd == 1:    bull += 20
    elif sd == -1: bear += 20
    # EMA hizalama (10)
    if c > e20 > e50:    bull += 7
    elif c > e50:        bull += 3
    if c < e20 < e50:    bear += 7
    elif c < e50:        bear += 3
    # Hacim (5)
    if vol_now is not None and not pd.isna(vol_now):
        if not pd.isna(avg_v) and vol_now > avg_v * 1.8:
            if c > c_prev:   bull += 5
            elif c < c_prev: bear += 5
    # EMA200 filtresi
    if not pd.isna(e200):
        if c < e200 * 0.97:  bull = max(0, bull - 15)
        if c > e200 * 1.03:  bear = max(0, bear - 15)

    total = bull + bear
    if total < 20:
        return None
    if bull >= bear:
        pct = bull / total; confidence = int(min(99, 40 + pct * 60)); action = "LONG"; dom = bull
    else:
        pct = bear / total; confidence = int(min(99, 40 + pct * 60)); action = "SHORT"; dom = bear
    if dom < 40:
        return None
    return action, confidence


# ── Veri ───────────────────────────────────────────────────────────────────--
def download_history(symbols):
    print(f"📥 {len(symbols)} sembol · {BACKTEST_PERIOD} / {BAR_INTERVAL}")
    data = yf.download(symbols, period=BACKTEST_PERIOD, interval=BAR_INTERVAL,
                       group_by="ticker", auto_adjust=True, threads=True, progress=False)
    out = {}
    for sym in symbols:
        try:
            df = data.copy() if len(symbols) == 1 else data[sym].copy()
            df = df.dropna()
            if df.empty or len(df) < MIN_BARS + max(HORIZONS) + 5:
                continue
            df.columns = [str(c).lower() for c in df.columns]
            if not {"open", "high", "low", "close"}.issubset(df.columns):
                continue
            out[sym] = df
        except Exception:
            continue
    print(f"   ✓ {len(out)} sembol kullanılabilir veri verdi\n")
    return out


# ── Sembol replay'i + forward-return ───────────────────────────────────────--
def analyze_symbol(df, sym):
    """Bu sembol için tüm sinyalleri (cooldown uygulanmış) forward-return ile döner."""
    close = df["close"].astype(float)
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    has_vol = "volume" in df.columns
    vol = df["volume"].astype(float) if has_vol else None

    rsi_s  = calc_rsi(close)
    _, _, hist = calc_macd(close)
    st_dir = calc_supertrend(high, low, close)
    ema20  = calc_ema(close, 20)
    ema50  = calc_ema(close, 50)
    ema200 = calc_ema(close, 200)
    vol_avg = vol.rolling(20).mean() if has_vol else None

    closes = close.values
    n = len(df)
    records = []
    last_fire = {}  # (action) -> bar index, cooldown için

    # son bar forward-return ölçülemez → max(HORIZONS) kadar geriden bitir
    end = n - max(HORIZONS)

    for i in range(MIN_BARS, end):
        res = score_at(
            rsi_s.iloc[i], hist.iloc[i], hist.iloc[i-1], st_dir.iloc[i],
            closes[i], closes[i-1], ema20.iloc[i], ema50.iloc[i], ema200.iloc[i],
            (vol.iloc[i] if has_vol else None),
            (vol_avg.iloc[i] if has_vol else float("nan")),
        )
        if res is None:
            continue
        action, confidence = res

        # cooldown: aynı yönde COOLDOWN_BARS içinde tekrar sayma
        if action in last_fire and (i - last_fire[action]) < COOLDOWN_BARS:
            continue
        last_fire[action] = i

        entry = closes[i]
        rec = {"symbol": sym, "ts": df.index[i], "action": action, "confidence": confidence, "entry": entry}

        # yöne göre forward getiri (LONG: yukarı kâr, SHORT: aşağı kâr)
        sign = 1.0 if action == "LONG" else -1.0
        for k in HORIZONS:
            fwd = (closes[i + k] - entry) / entry * sign * 100.0
            rec[f"ret_{k}"] = fwd

        # MFE/MAE — pencere içindeki en iyi/en kötü yönlü hareket
        window = closes[i+1 : i+1+MFE_MAE_WINDOW]
        exc = (window - entry) / entry * sign * 100.0
        rec["mfe"] = float(np.max(exc)) if len(exc) else 0.0
        rec["mae"] = float(np.min(exc)) if len(exc) else 0.0
        records.append(rec)

    # ÖZ-KONTROL: gerçek compute_signal son barda ne diyor, biz ne diyoruz?
    check = _self_check(df, sym, rsi_s, hist, st_dir, ema20, ema50, ema200, vol, vol_avg, has_vol)
    return records, check


def _self_check(df, sym, rsi_s, hist, st_dir, ema20, ema50, ema200, vol, vol_avg, has_vol):
    """Son barda score_at == compute_signal mi? Skorlama kopyası bozulduysa yakalar."""
    i = len(df) - 1
    mine = score_at(
        rsi_s.iloc[i], hist.iloc[i], hist.iloc[i-1], st_dir.iloc[i],
        df["close"].iloc[i], df["close"].iloc[i-1], ema20.iloc[i], ema50.iloc[i], ema200.iloc[i],
        (vol.iloc[i] if has_vol else None),
        (vol_avg.iloc[i] if has_vol else float("nan")),
    )
    real = compute_signal(df, sym)
    mine_t = None if mine is None else (mine[0], mine[1])
    real_t = None if real is None else (real["action"], real["confidence"])
    return mine_t == real_t


# ── Raporlama ─────────────────────────────────────────────────────────────--
def summarize(records):
    if not records:
        print("⚠ Hiç sinyal üretilmedi — eşik/parametre ya da veri kontrol et.")
        return
    df = pd.DataFrame(records)

    print("=" * 78)
    print(f"  TOPLAM SİNYAL: {len(df)}  ·  LONG: {(df.action=='LONG').sum()}  ·  SHORT: {(df.action=='SHORT').sum()}")
    print(f"  Cooldown: {COOLDOWN_BARS} bar  ·  Horizon (bar): {HORIZONS}")
    print("=" * 78)

    # Eşik süpürme tablosu
    print("\n  CONFIDENCE EŞİĞİ SÜPÜRMESİ")
    print("  (her eşik için: sinyal sayısı, ve her horizon'da isabet% / ort.getiri%)")
    header = f"  {'eşik':>5} {'adet':>6} "
    for k in HORIZONS:
        header += f"| {f'{k}b hit%':>7} {f'{k}b ort%':>8} "
    print(header)
    print("  " + "-" * (len(header) - 2))

    for th in THRESHOLDS:
        sub = df[df.confidence >= th]
        line = f"  {th:>5} {len(sub):>6} "
        for k in HORIZONS:
            col = f"ret_{k}"
            if len(sub):
                hit = (sub[col] > 0).mean() * 100
                avg = sub[col].mean()
                line += f"| {hit:>6.1f}% {avg:>+7.2f}% "
            else:
                line += f"| {'-':>7} {'-':>8} "
        print(line)

    # Ayrıntı: MIN_CONFIDENCE=75 kesiti (canlıda kullanılan eşik)
    cut = df[df.confidence >= 75]
    if len(cut):
        print(f"\n  CANLI EŞİK (75+) DETAYI · {len(cut)} sinyal")
        for k in HORIZONS:
            col = f"ret_{k}"
            hit = (cut[col] > 0).mean() * 100
            print(f"    {k:>2} bar sonra:  isabet {hit:5.1f}%   ort {cut[col].mean():+.2f}%   "
                  f"medyan {cut[col].median():+.2f}%")
        print(f"    Ortalama MFE (max lehte): {cut['mfe'].mean():+.2f}%   "
              f"Ortalama MAE (max aleyhte): {cut['mae'].mean():+.2f}%")
        # rastgele bir 50/50'den iyi mi? Basit referans:
        print(f"\n  Yorum ipucu: isabet% sürekli ~50'nin belirgin üstündeyse sinyalde bilgi var.")
        print(f"  ~50 civarıysa skor gürültüye ateş ediyor; eşiği/ağırlıkları gözden geçir.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="Tüm sinyalleri bu dosyaya yaz")
    args = ap.parse_args()

    bars = download_history(UNIVERSE)
    if not bars:
        print("✗ Veri yok."); return 1

    all_records = []
    failed_checks = []
    for sym, df in bars.items():
        recs, ok = analyze_symbol(df, sym)
        all_records.extend(recs)
        if not ok:
            failed_checks.append(sym)

    if failed_checks:
        print(f"⚠ ÖZ-KONTROL UYARISI — şu sembollerde replay skoru compute_signal ile EŞLEŞMEDİ:")
        print(f"   {', '.join(failed_checks)}")
        print(f"   (Skorlama kopyası ile indicators.py arasında fark var; sonuçlara dikkat.)\n")
    else:
        print("✓ Öz-kontrol geçti: replay skoru tüm sembollerde compute_signal ile birebir aynı.\n")

    summarize(all_records)

    if args.csv and all_records:
        pd.DataFrame(all_records).to_csv(args.csv, index=False)
        print(f"\n💾 {len(all_records)} sinyal yazıldı: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
