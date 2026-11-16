# tesla-watch

Tesla TR ikinci el Model Y ilanlarını takip eder; yeni ilan veya fiyat düşüşünde WhatsApp (CallMeBot) / Telegram bildirimi gönderir.

- `worker/` — Cloudflare Worker (5 dk'da bir cron). GitHub Actions ile otomatik kurulur.
- `tesla_watch.py` — aynı mantığın Python sürümü (ev bilgisayarında çalıştırmak için).

GitHub Actions sunucuları Tesla (Akamai) tarafından engellendiği için takip Cloudflare üzerinde çalışır.
