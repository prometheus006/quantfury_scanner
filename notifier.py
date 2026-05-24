"""
Gmail SMTP bildirim modülü.
Çevre değişkenleri: SMTP_USER, SMTP_PASS, SMTP_TO (opsiyonel, yoksa USER'a gider)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_TO = os.environ.get("SMTP_TO") or SMTP_USER


def _market_label(symbol: str) -> str:
    """Sembolün borsa/bölge etiketi (görsel referans için)."""
    if symbol.endswith(".DE"):
        return "DAX"
    if symbol.endswith(".PA"):
        return "Paris"
    if symbol.endswith(".AS"):
        return "Amsterdam"
    if symbol.endswith(".SW"):
        return "Zurich"
    if symbol.endswith(".L"):
        return "London"
    if symbol.endswith(".MI"):
        return "Milan"
    return "US"


def _render_html(signals: list[dict], scan_meta: dict) -> str:
    rows = []
    for s in signals:
        is_long = s["action"] == "LONG"
        color = "#16a34a" if is_long else "#dc2626"
        bg = "#f0fdf4" if is_long else "#fef2f2"
        arrow = "▲" if is_long else "▼"
        market = _market_label(s["symbol"])

        rows.append(f"""
        <tr style="background:{bg}">
          <td style="padding:10px 12px;font-family:ui-monospace,SFMono-Regular,monospace;font-weight:600;font-size:14px">
            {s["symbol"]}
            <div style="font-size:10px;color:#64748b;font-weight:400;letter-spacing:0.5px">{market}</div>
          </td>
          <td style="padding:10px 12px;color:{color};font-weight:700;font-size:14px;white-space:nowrap">
            {arrow} {s["action"]}
          </td>
          <td style="padding:10px 12px;font-weight:700;font-size:15px">{s["confidence"]}%</td>
          <td style="padding:10px 12px;font-family:ui-monospace,monospace">${s["price"]}</td>
          <td style="padding:10px 12px;font-family:ui-monospace,monospace">{s["rsi"]}</td>
          <td style="padding:10px 12px;font-family:ui-monospace,monospace">{s["macd_hist"]:+.3f}</td>
          <td style="padding:10px 12px;font-size:12px">{s["supertrend"]}</td>
          <td style="padding:10px 12px;font-family:ui-monospace,monospace">{s["atr_pct"]}%</td>
        </tr>
        """)

    # İstanbul saatiyle de göster
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(ZoneInfo("Europe/Istanbul"))
    ts_str = f"{now_ist.strftime('%Y-%m-%d %H:%M')} TSİ  ·  {now_utc.strftime('%H:%M')} UTC"

    return f"""
    <!doctype html>
    <html><head><meta charset="utf-8"></head>
    <body style="margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;padding:24px">
      <div style="max-width:760px;margin:auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.08)">

        <!-- Header -->
        <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);color:white;padding:20px 24px">
          <div style="display:flex;justify-content:space-between;align-items:baseline">
            <h2 style="margin:0;font-size:20px;font-weight:600">📊 {len(signals)} Yeni Sinyal</h2>
            <span style="font-size:12px;opacity:0.7">{ts_str}</span>
          </div>
          <p style="margin:6px 0 0;opacity:0.6;font-size:13px">
            Tarama #{scan_meta.get("scan_count", "?")} · {scan_meta.get("total_scanned", 0)} sembol tarandı
          </p>
        </div>

        <!-- Signals table -->
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:#f8fafc;text-align:left;border-bottom:2px solid #e2e8f0">
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">SEMBOL</th>
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">YÖN</th>
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">SKOR</th>
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">FİYAT</th>
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">RSI</th>
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">MACD H</th>
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">ST</th>
              <th style="padding:10px 12px;font-weight:600;color:#475569;font-size:11px;letter-spacing:0.5px">ATR%</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>

        <!-- Footer -->
        <div style="padding:16px 24px;background:#fef9c3;border-top:1px solid #fde68a;color:#713f12;font-size:12px;line-height:1.5">
          <strong>⚠ Otomatik tarama.</strong> Quantfury'de manuel açmadan önce: (1) grafiği kontrol et,
          (2) destek/direnci doğrula, (3) ATR%'ye göre stop seviyesini belirle.
          ATR%, hisse oynaklığının fiyata oranı — ne kadar yüksekse o kadar geniş stop gerekir.
        </div>
        <div style="padding:12px 24px;background:#f8fafc;color:#94a3b8;font-size:11px;text-align:center">
          Sinyal motoru: AlphaBot v2 · 1h bar · Min güven %65 · Dedupe 4h
        </div>

      </div>
    </body></html>
    """


def send_email(signals: list[dict], scan_meta: dict | None = None) -> bool:
    """
    Sinyalleri tek bir HTML email'de gönderir.
    Boş liste geldiyse hiçbir şey gönderilmez.
    Dönüş: başarılıysa True.
    """
    if not signals:
        return False

    if not SMTP_USER or not SMTP_PASS:
        print("⚠ SMTP_USER/SMTP_PASS eksik — email gönderilmedi (kuruyu çalıştırma)")
        return False

    scan_meta = scan_meta or {}

    # Subject: en yüksek skorlu sinyal başlığa, geri kalanı sayı olarak
    top = signals[0]
    arrow = "▲" if top["action"] == "LONG" else "▼"
    if len(signals) == 1:
        subject = f"{arrow} {top['symbol']} {top['action']} %{top['confidence']} @ ${top['price']}"
    else:
        subject = f"{arrow} {top['symbol']} {top['action']} %{top['confidence']} · +{len(signals)-1} sinyal daha"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Quantfury Scanner <{SMTP_USER}>"
    msg["To"] = SMTP_TO

    plain = "Yeni sinyaller:\n\n" + "\n".join(
        f"  {s['symbol']:10s} {s['action']:5s}  %{s['confidence']:3d}  ${s['price']:8.2f}  RSI={s['rsi']:5.1f}"
        for s in signals
    )
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(_render_html(signals, scan_meta), "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            recipients = [addr.strip() for addr in SMTP_TO.split(",")]
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"✓ Email gönderildi → {SMTP_TO} ({len(signals)} sinyal)")
        return True
    except Exception as e:
        print(f"✗ Email gönderilemedi: {e}")
        return False
