import json, time
from curl_cffi import requests as creq
import tesla_watch as t

print("== curl_cffi ==")
for imp in ["chrome", "safari", "firefox"]:
    try:
        s = creq.Session(impersonate=imp)
        r1 = s.get(t.PAGE_URL, timeout=30)
        r2 = s.get(t.build_query(), timeout=30, headers={"Referer": t.PAGE_URL, "Accept": "application/json"})
        print(imp, "page", r1.status_code, len(r1.text), "| api", r2.status_code, r2.text[:80].replace("\n", " "))
    except Exception as e:
        print(imp, "ERR", e)

print("== playwright ==")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    for headless in [True]:
        b = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(locale="tr-TR", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        pg = ctx.new_page()
        got = []
        pg.on("response", lambda r: got.append((r.status, r.url[:90])) if "inventory-results" in r.url else None)
        try:
            resp = pg.goto(t.PAGE_URL, timeout=60000, wait_until="domcontentloaded")
            print("page status", resp.status if resp else None)
            pg.wait_for_timeout(15000)
            print("title", pg.title())
            print("api responses", got)
            txt = pg.inner_text("body")[:300].replace("\n", " ")
            print("body", txt)
        except Exception as e:
            print("ERR", e)
        b.close()
