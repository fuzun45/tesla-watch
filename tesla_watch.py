#!/usr/bin/env python3
"""
Tesla TR - İkinci El Model Y takipçisi (GitHub Actions sürümü)

Her çalıştırmada bir kez kontrol eder:
  - Listeye yeni araç düştüyse   -> WhatsApp / Telegram bildirimi
  - Mevcut aracın fiyatı düştüyse -> bildirim
Durum tesla_seen.json dosyasında tutulur (workflow değişince commit'ler).

Ayarlar ortam değişkenlerinden (GitHub Secrets) okunur:
  WHATSAPP_PHONE, WHATSAPP_APIKEY        (CallMeBot)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (opsiyonel / yedek)

Kullanım:
  python tesla_watch.py           -> kontrol et
  python tesla_watch.py --test    -> deneme bildirimi gönder
  python tesla_watch.py --list    -> mevcut araçları yaz
"""

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests as creq

# ======================= AYARLAR =======================
MODEL = os.getenv("TESLA_MODEL", "my")          # my = Model Y, m3 = Model 3
CONDITION = os.getenv("TESLA_CONDITION", "used")
ZIP = "34080"
LAT, LNG = 41.0082, 28.9784
ALERT_PRICE_DROPS = True
FAIL_ALERT_AFTER = 6          # art arda bu kadar hata olursa uyar
# =======================================================

WA_PHONE = os.getenv("WHATSAPP_PHONE", "").strip()
WA_KEY = os.getenv("WHATSAPP_APIKEY", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()

STATE_FILE = Path(__file__).with_name("tesla_seen.json")
PAGE_URL = (f"https://www.tesla.com/tr_TR/inventory/{CONDITION}/{MODEL}"
            f"?arrangeby=plh&zip={ZIP}&range=0")
API_URL = "https://www.tesla.com/inventory/api/v4/inventory-results"


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}", flush=True)


# ---------------------- Veri çekme ----------------------
def build_query(offset=0, count=50):
    q = {
        "query": {
            "model": MODEL, "condition": CONDITION, "options": {},
            "arrangeby": "Price", "order": "asc",
            "market": "TR", "language": "tr", "super_region": "north america",
            "lng": LNG, "lat": LAT, "zip": ZIP, "range": 0,
        },
        "offset": offset, "count": count,
        "outsideOffset": 0, "outsideSearch": False,
    }
    return API_URL + "?query=" + urllib.parse.quote(json.dumps(q, separators=(",", ":")))


def make_session():
    s = creq.Session(impersonate="chrome")
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        "Referer": PAGE_URL,
    })
    try:
        s.get(PAGE_URL, timeout=30)   # çerez al
    except Exception as e:
        log(f"Sayfa ön-ziyareti başarısız: {e}")
    return s


def extract_results(data):
    res = data.get("results", [])
    if isinstance(res, dict):
        return list(res.get("exact", []) or [])
    return list(res or [])


def fetch_all(session):
    cars, offset = [], 0
    while True:
        r = session.get(build_query(offset), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except Exception:
            raise RuntimeError(f"JSON değil (muhtemelen bot engeli): {r.text[:200]}")
        batch = extract_results(data)
        cars.extend(batch)
        total = int(data.get("total_matches_found") or 0)
        offset += len(batch)
        if not batch or offset >= total:
            break
        time.sleep(1.5)
    return cars


# ---------------------- Biçimlendirme ----------------------
def price_of(c):
    for k in ("InventoryPrice", "Price", "PurchasePrice", "TotalPrice"):
        v = c.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return None


def tl(v):
    return "?" if v is None else f"{v:,.0f} TL".replace(",", ".")


def describe(c):
    parts = []
    if c.get("Year"):
        parts.append(str(c["Year"]))
    parts.append(c.get("TrimName") or "Model Y")
    if c.get("Odometer") is not None:
        parts.append(f"{int(c['Odometer']):,} km".replace(",", "."))
    paint = c.get("PAINT")
    if isinstance(paint, list) and paint:
        parts.append(str(paint[0]).title())
    if c.get("City"):
        parts.append(c["City"])
    return " · ".join(parts)


def car_link(c):
    return (f"https://www.tesla.com/tr_TR/{MODEL}/order/{c.get('VIN', '')}"
            f"?titleStatus={CONDITION}&redirect=no#overview")


# ---------------------- Bildirim ----------------------
def notify(title, body, link=None):
    text = f"*{title}*\n{body}" + (f"\n{link}" if link else "")
    sent = False
    if WA_PHONE and WA_KEY:
        try:
            r = creq.get("https://api.callmebot.com/whatsapp.php",
                         params={"phone": WA_PHONE, "apikey": WA_KEY, "text": text},
                         timeout=30)
            ok = r.status_code == 200 and "error" not in r.text.lower()[:300]
            log(f"WhatsApp: {'OK' if ok else 'HATA ' + str(r.status_code) + ' ' + r.text[:150]}")
            sent |= ok
        except Exception as e:
            log(f"WhatsApp hatası: {e}")
    if TG_TOKEN and TG_CHAT:
        try:
            r = creq.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": text, "parse_mode": "Markdown",
                                "disable_web_page_preview": True}, timeout=30)
            ok = r.status_code == 200
            log(f"Telegram: {'OK' if ok else 'HATA ' + r.text[:150]}")
            sent |= ok
        except Exception as e:
            log(f"Telegram hatası: {e}")
    if not (WA_PHONE and WA_KEY) and not (TG_TOKEN and TG_CHAT):
        log("UYARI: Hiç bildirim kanalı ayarlı değil (secrets eksik).")
    return sent


# ---------------------- Durum ----------------------
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")


def diff(prev, cars):
    new, drops, now = [], [], {}
    for c in cars:
        vin = c.get("VIN")
        if not vin:
            continue
        p = price_of(c)
        now[vin] = p
        if vin not in prev:
            new.append(c)
        elif p and prev[vin] and p < prev[vin]:
            drops.append((c, prev[vin], p))
    return new, drops, now


# ---------------------- Ana mantık ----------------------
def check():
    if not (WA_PHONE and WA_KEY) and not (TG_TOKEN and TG_CHAT):
        log("Bildirim kanalı (secrets) henüz ayarlı değil, kontrol atlandı.")
        return
    state = load_state()
    seen = state.get("cars")
    fails = state.get("fails", 0)

    try:
        cars = fetch_all(make_session())
    except Exception as e:
        fails += 1
        log(f"Veri çekilemedi ({fails}. kez): {e}")
        if fails == FAIL_ALERT_AFTER:
            notify("Tesla takip sorunu ⚠️",
                   f"Son {fails} kontrol başarısız oldu.\n{str(e)[:150]}")
        state["fails"] = fails
        save_state(state)
        return

    if fails >= FAIL_ALERT_AFTER:
        notify("Tesla takip tekrar çalışıyor ✅", f"{len(cars)} araç listede.")
    state["fails"] = 0

    if seen is None:   # ilk çalıştırma
        _, _, now = diff({}, cars)
        cheapest = min((price_of(c) for c in cars if price_of(c)), default=None)
        msg = f"Şu an {len(now)} araç listede. En ucuzu: {tl(cheapest)}"
        log("İlk çalıştırma. " + msg)
        notify("Tesla takip aktif ✅", msg, PAGE_URL)
        state["cars"] = now
        save_state(state)
        return

    new, drops, now = diff(seen, cars)
    for c in sorted(new, key=lambda c: price_of(c) or 0):
        log(f"YENİ: {c.get('VIN')} {tl(price_of(c))} {describe(c)}")
        notify(f"🚨 Yeni Model Y: {tl(price_of(c))}", describe(c), car_link(c))
    if ALERT_PRICE_DROPS:
        for c, old, newp in drops:
            log(f"FİYAT DÜŞTÜ: {c.get('VIN')} {tl(old)} -> {tl(newp)}")
            notify(f"📉 Fiyat düştü: {tl(newp)}", f"{tl(old)} → {tl(newp)}\n{describe(c)}",
                   car_link(c))
    gone = set(seen) - set(now)
    log(f"{len(now)} araç | yeni: {len(new)} | fiyatı düşen: {len(drops)} | kalkan: {len(gone)}")
    state["cars"] = now
    save_state(state)


def main():
    args = set(sys.argv[1:])
    if "--test" in args:
        ok = notify("Tesla takip testi", "Bu mesajı görüyorsan bildirim kurulumu tamam 👍", PAGE_URL)
        sys.exit(0 if ok else 1)
    if "--list" in args:
        cars = fetch_all(make_session())
        log(f"{len(cars)} araç bulundu:")
        for c in sorted(cars, key=lambda c: price_of(c) or 0):
            print(f"  {tl(price_of(c)):>16}  {describe(c)}  [{c.get('VIN')}]")
        return
    check()


if __name__ == "__main__":
    main()
