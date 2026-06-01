"""
ABD borsa seansı kontrolü.
scanner.py bu fonksiyonu en üstte çağırır; piyasa kapalıysa tarama hiç başlamaz.
America/New_York saat dilimi kullanıldığı için yaz/kış saati (DST) otomatik halledilir.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo


def is_market_open() -> bool:
    """ABD seansı (NYSE/NASDAQ) şu an açık mı? Tatilleri bilmez, sadece gün+saat."""
    now_et = datetime.now(ZoneInfo("America/New_York"))

    # Hafta sonu: 5 = Cumartesi, 6 = Pazar
    if now_et.weekday() >= 5:
        return False

    # Normal seans: 09:30 - 16:00 ET
    return time(9, 30) <= now_et.time() <= time(16, 0)


# Yerelde hızlı test için: python market_hours.py
if __name__ == "__main__":
    now_et = datetime.now(ZoneInfo("America/New_York"))
    print(f"Şu an (ET): {now_et:%Y-%m-%d %H:%M:%S %A}")
    print(f"Piyasa açık mı? {is_market_open()}")
