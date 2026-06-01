"""
Günlük "bot yaşıyor" bildirimi.
scanner.py her çalıştığında değil, sadece kapanışa yakın pencerede (15:30–16:00 ET)
bir kez tetiklenir. Bu mail gelmiyorsa → ya tatil ya da bir şey kırıldı demektir.

SMTP bilgileri scan.yml'deki ortam değişkenlerinden okunur (notifier.py ile aynı
SMTP_USER / SMTP_PASS / SMTP_TO). notifier.py'ye dokunmaz, bağımsız çalışır.
"""

import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, time
from zoneinfo import ZoneInfo


def is_heartbeat_time() -> bool:
    """Kapanıştan önceki son yarım saat (15:30–16:00 ET) içinde miyiz?"""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    return time(15, 30) <= now_et.time() < time(16, 0)


def send_heartbeat(signal_count: int, scanned_count: int, scan_count: int) -> None:
    """Kısa bir 'alive' maili gönderir. Hata olursa taramayı çökertmez, sadece loglar."""
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    to = os.environ.get("SMTP_TO")
    if not (user and password and to):
        print("⚠ Heartbeat: SMTP bilgileri eksik, atlandı.")
        return

    now_et = datetime.now(ZoneInfo("America/New_York"))
    body = (
        f"<h3>✅ Quantfury Scanner — günlük durum</h3>"
        f"<p>Tarama çalışıyor.</p>"
        f"<ul>"
        f"<li>Zaman (ET): {now_et:%Y-%m-%d %H:%M}</li>"
        f"<li>Bu turda taranan sembol: {scanned_count}</li>"
        f"<li>Bu turda eşik üstü yeni sinyal: {signal_count}</li>"
        f"<li>Toplam tarama (ömür boyu): {scan_count}</li>"
        f"</ul>"
        f"<p style='color:#888;font-size:12px'>Bu mail gelmezse bot durmuş olabilir.</p>"
    )

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = "✅ Scanner heartbeat"
    msg["From"] = user
    msg["To"] = to

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [to], msg.as_string())
        print("✓ Heartbeat maili gönderildi.")
    except Exception as e:
        print(f"⚠ Heartbeat gönderilemedi: {e}")
