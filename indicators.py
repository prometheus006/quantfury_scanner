"""
Teknik indikatör hesaplamaları + bull/bear skor motoru.
Mevcut AlphaBot mantığı birebir taşındı; sadece broker bağımlılıkları çıkarıldı.
"""

import pandas as pd
import numpy as np

from config import (
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ST_PERIOD, ST_MULT, ATR_PERIOD, MIN_BARS,
)


# ═════════════════════════════════════════════════════════════════════════════
#  İNDİKATÖRLER
# ═════════════════════════════════════════════════════════════════════════════

def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    rs = (
        up.ewm(com=period - 1, min_periods=period).mean()
        / down.ewm(com=period - 1, min_periods=period).mean()
    )
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist


def calc_ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def calc_atr(high, low, close, period: int = ATR_PERIOD) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_supertrend(high, low, close, period: int = ST_PERIOD, mult: float = ST_MULT) -> pd.Series:
    """+1 = Bullish, -1 = Bearish."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr_s = tr.rolling(period).mean()
    hl2 = (high + low) / 2

    basic_upper = hl2 + mult * atr_s
    basic_lower = hl2 - mult * atr_s

    n = len(close)
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    direction = pd.Series(1, index=close.index)

    for i in range(1, n):
        if (basic_upper.iloc[i] < final_upper.iloc[i - 1]) or (close.iloc[i - 1] > final_upper.iloc[i - 1]):
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        if (basic_lower.iloc[i] > final_lower.iloc[i - 1]) or (close.iloc[i - 1] < final_lower.iloc[i - 1]):
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        prev_dir = direction.iloc[i - 1]
        if prev_dir == 1:
            direction.iloc[i] = -1 if close.iloc[i] < final_lower.iloc[i] else 1
        else:
            direction.iloc[i] = 1 if close.iloc[i] > final_upper.iloc[i] else -1

    return direction


# ═════════════════════════════════════════════════════════════════════════════
#  SİNYAL MOTORU — Bull/Bear puanlama
# ═════════════════════════════════════════════════════════════════════════════

def compute_signal(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    AlphaBot mantığı:
      RSI 30 + MACD 35 + SuperTrend 20 + EMA align 10 + Hacim 5 = max 100/yön
      EMA200 trend kapısı (uzun trendin tersine sinyali cezalandırır)
    """
    if len(df) < MIN_BARS:
        return None

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float) if "volume" in df.columns else None

    rsi_s = calc_rsi(close)
    _, _, hist = calc_macd(close)
    st_dir = calc_supertrend(high, low, close)
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    ema200 = calc_ema(close, 200)
    atr_v = calc_atr(high, low, close).iloc[-1]

    r = rsi_s.iloc[-1]
    h_now = hist.iloc[-1]
    h_prev = hist.iloc[-2]
    sd = st_dir.iloc[-1]
    c = close.iloc[-1]
    e20 = ema20.iloc[-1]
    e50 = ema50.iloc[-1]
    e200 = ema200.iloc[-1]

    # NaN koruma — yeni listelenen hisselerde EMA200 erken NaN olabilir
    if pd.isna(r) or pd.isna(h_now) or pd.isna(e50):
        return None

    bull = 0
    bear = 0

    # RSI (30)
    if r < 25:    bull += 30
    elif r < 35:  bull += 20
    elif r < 45:  bull += 10
    elif r > 75:  bear += 30
    elif r > 65:  bear += 20
    elif r > 55:  bear += 10

    # MACD crossover (35) — taze geçiş > pozitif histogram
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

    # Hacim momentum (5)
    if vol is not None and not pd.isna(vol.iloc[-1]):
        avg_v = vol.rolling(20).mean().iloc[-1]
        if not pd.isna(avg_v) and vol.iloc[-1] > avg_v * 1.8:
            if c > close.iloc[-2]:   bull += 5
            elif c < close.iloc[-2]: bear += 5

    # EMA200 uzun trend filtresi
    if not pd.isna(e200):
        if c < e200 * 0.97:  bull = max(0, bull - 15)
        if c > e200 * 1.03:  bear = max(0, bear - 15)

    total = bull + bear
    if total < 20:
        return None

    if bull >= bear:
        pct = bull / total
        confidence = int(min(99, 40 + pct * 60))
        action = "LONG"
        dominant_score = bull
    else:
        pct = bear / total
        confidence = int(min(99, 40 + pct * 60))
        action = "SHORT"
        dominant_score = bear

    # Asgari dominant skor — toplam yüksek olsa bile tek tarafta zayıf sinyali atla
    if dominant_score < 40:
        return None

    return {
        "symbol":      symbol,
        "action":      action,
        "confidence":  confidence,
        "price":       round(float(c), 2),
        "rsi":         round(float(r), 1),
        "macd_hist":   round(float(h_now), 4),
        "supertrend":  "Bull" if sd == 1 else "Bear",
        "ema_align":   "Bull" if c > e50 else "Bear",
        "atr":         round(float(atr_v), 3),
        "atr_pct":     round(float(atr_v / c * 100), 2),
        "bull_score":  int(bull),
        "bear_score":  int(bear),
    }
