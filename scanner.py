#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
 QUANTFURY SCANNER — yfinance + Gmail SMTP + GitHub Actions cron
═══════════════════════════════════════════════════════════════════════════════
Akış:
  1) state.json yükle (önceki alarmlar)
  2) yfinance ile evren bar verisi indir (batch)
  3) Her sembol için bull/bear skor hesapla
  4) Eşik üstü + dedupe geçen sinyalleri topla
  5) Varsa tek email gönder
  6) state.json kaydet (sonraki tarama için)

Komut satırı:
  python scanner.py                # normal çalışma
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


STATE_FILE = Path(__file__).parent / "state.json"


# ─────────────────────────────────────────────────────────────────────────────
# DURUM (state) — dedupe için son sinyaller
# ─────────────────────────────────────────────────────────────────────────────

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
    """
    Aynı sembol için son bildirimden bu yana DEDUPE_HOURS geçti mi?
    Yön değiştiyse her zaman tetikler (LONG→SHORT veya tersi).
    """
    rec = alerts.get(symbol)
    if not rec:
        return False
    if rec["action"] != action:
        return False  # yön değişti → tetikle
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


# ─────────────────────────────────────────────────────────────────────────────
# VERİ ÇEKME
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """yfinance batch download. Sembol başına DataFrame döner."""
    print(f"📥 yfinance batch download → {len(symbols)} sembol, {BAR_PERIOD} / {BAR_INTERVAL}")

    try:
        data = yf.download(
            tickers=symbols,
            period=BAR_PERIOD,
            interval=BAR_INTERVAL,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception as e:
        print(f"✗ yfinance download hatası: {e}")
        return {}

    if data is None or data.empty:
        print("✗ yfinance boş döndü")
        return {}

    results: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []

    for sym in symbols:
        try:
            if len(symbols) == 1:
                df = data.copy()
            else:
                df = data[sym].copy()

            df = df.dropna()
            if df.empty or len(df) < 50:
                skipped.append(f"{sym}(az_veri:{len(df)})")
                continue

            # Kolon adlarını normalize et: Open/High/Low/Close/Volume → küçük harf
            df.columns = [str(c).lower() for c in df.columns]
            required = {"open", "high", "low", "close"}
            if not required.issubset(df.columns):
                skipped.append(f"{sym}(eksik_kolon)")
                continue

            results[sym] = df
        except (KeyError, AttributeError) as e:
            skipped.append(f"{sym}(yok)")
        except Exception as e:
            skipped.append(f"{sym}(hata:{type(e).__name__})")

    print(f"   ✓ {len(results)} sembol veri çekti, atlanan: {len(skipped)}")
    if skipped:
        print(f"   ⚠ Atlananlar: {', '.join(skipped[:8])}{'...' if len(skipped) > 8 else ''}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ANA
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Email gönderme, sadece konsola yaz")
    parser.add_argument("--no-dedupe", action="store_true", help="Dedupe'u atla (test için)")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    print("=" * 78)
    print(f"  QUANTFURY SCANNER · {started.isoformat()}")
    print("=" * 78)

    # 1) Durum yükle
    state = load_state()
    state["scan_count"] = state.get("scan_count", 0) + 1
    alerts = state.setdefault("alerts", {})

    # 2) Veri çek
    bars = fetch_all_bars(UNIVERSE)
    if not bars:
        print("✗ Veri yok, çıkılıyor.")
        return 1

    # 3) Sinyal üret
    all_signals: list[dict] = []
    new_signals: list[dict] = []

    for sym, df in bars.items():
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

    # 4) Konsol özeti
    new_signals.sort(key=lambda s: s["confidence"], reverse=True)
    all_signals.sort(key=lambda s: s["confidence"], reverse=True)

    print(f"\n📊 Tüm sinyaller ({len(all_signals)}):")
    for s in all_signals[:15]:
        flag = "🔔" if s in new_signals else "  "
        print(f"   {flag} {s['symbol']:10s} {s['action']:5s} %{s['confidence']:3d}  ${s['price']:>8.2f}  "
              f"RSI={s['rsi']:5.1f}  MACD_H={s['macd_hist']:+.3f}  ST={s['supertrend']}")

    print(f"\n🔔 Eşik üstü + dedupe geçen yeni sinyaller: {len(new_signals)}")

    # 5) Email gönder
    scan_meta = {
        "scan_count": state["scan_count"],
        "total_scanned": len(bars),
    }

    if new_signals and not args.dry_run:
        send_email(new_signals, scan_meta)
    elif new_signals and args.dry_run:
        print("   (--dry-run aktif, email atlandı)")

    # 6) Durum kaydet — sadece yeni alarm varsa state güncellenir
    if new_signals or not STATE_FILE.exists():
        save_state(state)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"\n✓ Tamamlandı · {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
