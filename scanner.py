#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
 QUANTFURY SCANNER — yfinance + Gmail SMTP + GitHub Actions cron
═══════════════════════════════════════════════════════════════════════════════
7/24 evrensel mantık: saat guard'ı YOK. Bunun yerine her sembolün son barı
TAZE mi diye bakılır. Bayat (donmuş/kapalı piyasa) barlar atlanır; taze veri
varsa taranır. Böylece US gece seansı, Asya erken açılış, Avrupa gündüz ve
kripto-benzeri sürekli akış — hepsi tek kuralla, timezone/tatil tablosu olmadan.

Komut satırı:
  python scanner.py
  python scanner.py --dry-run      # email gönderme, sadece konsola yaz
  python scanner.py --no-dedupe    # dedupe'u atla (test için)
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
import os
import json
import argparse
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("❌ pip install yfinance pandas numpy")
    sys.exit(1)

from config import UNIVERSE, MIN_CONFIDENCE, DEDUPE_HOURS, BAR_INTERVAL, BAR_PERIOD
from indicators import compute_signal
from notifier import send_email
from heartbeat import send_heartbeat


STATE_FILE = Path(__file__).parent / "state.json"


# ── Bar tazeliği ───────────────────────────────────────────────────────────--
def _interval_minutes(interval: str) -> int:
    s = interval.strip().lower()
    if s.endswith("h"): return int(float(s[:-1] or 1) * 60)
    if s.endswith("m"): return int(float(s[:-1] or 1))
    if s.endswith("d"): return int(float(s[:-1] or 1) * 60 * 24)
    return 60

BAR_MIN = _interval_minutes(BAR_INTERVAL)
FRESH_FACTOR = 2.5   # son bar, bar aralığının bu katından eskiyse "bayat" say

def is_fresh(df) -> bool:
    """Sembolün son barı yeterince yeni mi? Bayatsa piyasası donmuş demektir."""
    last_ts = pd.Timestamp(df.index[-1])
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize("UTC")
    age_min = (pd.Timestamp.now(tz="UTC") - last_ts).total_seconds() / 60.0
    return age_min <= BAR_MIN * FRESH_FACTOR


# ── Durum (state) ─────────────────────────────────────────────────────────--
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception as e:
            print(f"⚠ state.json okunamadı, sıfırdan başlanıyor: {e}")
    return {"alerts": {}, "scan_count": 0}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def is_duplicate(alerts: dict, symbol: str, action: str) -> bool:
    rec = alerts.get(symbol)
    if not rec:
        return False
    if rec["action"] != action:
        return False
    try:
        last = datetime.fromisoformat(rec["ts"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return delta_h < DEDUPE_HOURS
    except Exception:
        return False


def mark_alerted(alerts: dict, symbol: str, action: str, confidence: int) -> None:
    alerts[symbol] = {
        "action": action,
        "confidence": confidence,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ── Veri çekme ────────────────────────────────────────────────────────────--
def fetch_all_bars(symbols: list) -> dict:
    print(f"📥 yfinance batch download → {len(symbols)} sembol, {BAR_PERIOD} / {BAR_INTERVAL}")
    try:
        data = yf.download(
            tickers=symbols, period=BAR_PERIOD, interval=BAR_INTERVAL,
            group_by="ticker", auto_adjust=True, threads=True,
            progress=False, prepost=True,          # ← US uzatılmış seans barları dahil
        )
    except Exception as e:
        print(f"✗ yfinance download hatası: {e}")
        return {}

    if data is None or data.empty:
        print("✗ yfinance boş döndü")
        return {}

    results = {}
    skipped = []
    for sym in symbols:
        try:
            df = data.copy() if len(symbols) == 1 else data[sym].copy()
            df = df.dropna()
            if df.empty or len(df) < 50:
                skipped.append(f"{sym}(az_veri:{len(df)})")
                continue
            df.columns = [str(c).lower() for c in df.columns]
            if not {"open", "high", "low", "close"}.issubset(df.columns):
                skipped.append(f"{sym}(eksik_kolon)")
                continue
            results[sym] = df
        except (KeyError, AttributeError):
            skipped.append(f"{sym}(yok)")
        except Exception as e:
            skipped.append(f"{sym}(hata:{type(e).__name__})")

    print(f"   ✓ {len(results)} sembol veri çekti, atlanan: {len(skipped)}")
    if skipped:
        print(f"   ⚠ {', '.join(skipped[:8])}{'...' if len(skipped) > 8 else ''}")
    return results


# ── Ana ───────────────────────────────────────────────────────────────────--
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-dedupe", action="store_true")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    print("=" * 78)
    print(f"  QUANTFURY SCANNER · {started.isoformat()}")
    print("=" * 78)

    state = load_state()
    state["scan_count"] = state.get("scan_count", 0) + 1
    alerts = state.setdefault("alerts", {})

    bars = fetch_all_bars(UNIVERSE)
    if not bars:
        print("✗ Veri yok, çıkılıyor.")
        save_state(state)
        return 1

    all_signals = []
    new_signals = []
    stale = []

    for sym, df in bars.items():
        # TAZELİK KAPISI — bayat (donmuş piyasa) barı tarama
        if not is_fresh(df):
            stale.append(sym)
            continue
        try:
            sig = compute_signal(df, sym)
        except Exception as e:
            print(f"   ⚠ {sym} sinyal hatası: {e}")
            continue
        if not sig:
            continue
        all_signals.append(sig)
        if sig["confidence"] < MIN_CONFIDENCE:
            continue
        if not args.no_dedupe and is_duplicate(alerts, sym, sig["action"]):
            continue
        new_signals.append(sig)
        mark_alerted(alerts, sym, sig["action"], sig["confidence"])

    fresh_count = len(bars) - len(stale)
    print(f"\n   Taze: {fresh_count}/{len(bars)} sembol  ·  bayat atlanan: {len(stale)}")

    new_signals.sort(key=lambda s: s["confidence"], reverse=True)
    all_signals.sort(key=lambda s: s["confidence"], reverse=True)

    print(f"\n📊 Tüm sinyaller ({len(all_signals)}):")
    for s in all_signals[:15]:
        flag = "🔔" if s in new_signals else "  "
        print(f"   {flag} {s['symbol']:10s} {s['action']:5s} %{s['confidence']:3d}  ${s['price']:>8.2f}  "
              f"RSI={s['rsi']:5.1f}  MACD_H={s['macd_hist']:+.3f}  ST={s['supertrend']}")
    print(f"\n🔔 Eşik üstü + dedupe geçen yeni sinyaller: {len(new_signals)}")

    scan_meta = {"scan_count": state["scan_count"], "total_scanned": fresh_count}
    if new_signals and not args.dry_run:
        send_email(new_signals, scan_meta)
    elif new_signals and args.dry_run:
        print("   (--dry-run aktif, email atlandı)")

    # Heartbeat — günde bir kez (UTC günü), günün ilk run'ında. 7/24 mantığa uygun.
    today = started.strftime("%Y-%m-%d")
    if state.get("last_heartbeat") != today and not args.dry_run:
        send_heartbeat(signal_count=len(new_signals), scanned_count=fresh_count,
                       scan_count=state["scan_count"])
        state["last_heartbeat"] = today

    save_state(state)   # her zaman kaydet (scan_count + heartbeat tarihi kalıcı olsun)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"\n✓ Tamamlandı · {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
