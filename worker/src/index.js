// Tesla TR ikinci el Model Y takipçisi - Cloudflare Worker
// Cron ile 5 dk'da bir çalışır, yeni ilan / fiyat düşüşünde WhatsApp (CallMeBot) ve/veya Telegram'a yazar.
// Secrets: WHATSAPP_PHONE, WHATSAPP_APIKEY, (opsiyonel) TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
// KV binding: STATE

const MODEL = "my", CONDITION = "used", ZIP = "34080", LAT = 41.0082, LNG = 28.9784;
const PAGE_URL = `https://www.tesla.com/tr_TR/inventory/${CONDITION}/${MODEL}?arrangeby=plh&zip=${ZIP}&range=0`;
const FAIL_ALERT_AFTER = 6;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

function apiUrl(offset = 0, count = 50) {
  const q = {
    query: { model: MODEL, condition: CONDITION, options: {}, arrangeby: "Price", order: "asc",
      market: "TR", language: "tr", super_region: "north america", lng: LNG, lat: LAT, zip: ZIP, range: 0 },
    offset, count, outsideOffset: 0, outsideSearch: false,
  };
  return "https://www.tesla.com/inventory/api/v4/inventory-results?query=" + encodeURIComponent(JSON.stringify(q));
}

async function fetchAll() {
  const cars = [];
  let offset = 0;
  for (let i = 0; i < 10; i++) {
    const r = await fetch(apiUrl(offset), { headers: {
      "User-Agent": UA, "Accept": "application/json, text/plain, */*",
      "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8", "Referer": PAGE_URL,
      "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"', "sec-ch-ua-mobile": "?0",
      "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
    }});
    const text = await r.text();
    if (r.status !== 200) throw new Error(`HTTP ${r.status}: ${text.slice(0, 150)}`);
    let data;
    try { data = JSON.parse(text); } catch { throw new Error("JSON değil (bot engeli?): " + text.slice(0, 150)); }
    let res = data.results || [];
    if (!Array.isArray(res)) res = res.exact || [];
    cars.push(...res);
    const total = parseInt(data.total_matches_found || 0);
    offset += res.length;
    if (!res.length || offset >= total) break;
  }
  return cars;
}

const priceOf = c => { for (const k of ["InventoryPrice", "Price", "PurchasePrice", "TotalPrice"]) if (typeof c[k] === "number" && c[k] > 0) return Math.round(c[k]); return null; };
const tl = v => v == null ? "?" : v.toLocaleString("tr-TR") + " TL";
const link = c => `https://www.tesla.com/tr_TR/${MODEL}/order/${c.VIN}?titleStatus=${CONDITION}&redirect=no#overview`;
function describe(c) {
  const p = [];
  if (c.Year) p.push(String(c.Year));
  p.push(c.TrimName || "Model Y");
  if (c.Odometer != null) p.push(Number(c.Odometer).toLocaleString("tr-TR") + " km");
  if (Array.isArray(c.PAINT) && c.PAINT.length) p.push(String(c.PAINT[0]).toLowerCase().replace(/^./, s => s.toUpperCase()));
  if (c.City) p.push(c.City);
  return p.join(" · ");
}

async function notify(env, title, body, url) {
  const text = `*${title}*\n${body}` + (url ? `\n${url}` : "");
  const out = [];
  if (env.WHATSAPP_PHONE && env.WHATSAPP_APIKEY) {
    const u = "https://api.callmebot.com/whatsapp.php?" + new URLSearchParams({ phone: env.WHATSAPP_PHONE, apikey: env.WHATSAPP_APIKEY, text });
    try { const r = await fetch(u); out.push(`whatsapp:${r.status}`); } catch (e) { out.push("whatsapp:ERR " + e); }
  }
  if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
    try {
      const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, { method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text, parse_mode: "Markdown", disable_web_page_preview: true }) });
      out.push(`telegram:${r.status}`);
    } catch (e) { out.push("telegram:ERR " + e); }
  }
  return out.join(" ");
}

async function check(env) {
  const state = JSON.parse((await env.STATE.get("state")) || "{}");
  const log = [];
  let cars;
  try {
    cars = await fetchAll();
  } catch (e) {
    state.fails = (state.fails || 0) + 1;
    log.push(`Hata (${state.fails}): ${e.message}`);
    if (state.fails === FAIL_ALERT_AFTER) await notify(env, "Tesla takip sorunu ⚠️", `Son ${state.fails} kontrol başarısız.\n${e.message.slice(0, 150)}`);
    await env.STATE.put("state", JSON.stringify(state));
    return log;
  }
  if ((state.fails || 0) >= FAIL_ALERT_AFTER) await notify(env, "Tesla takip tekrar çalışıyor ✅", `${cars.length} araç listede.`);
  const now = {};
  for (const c of cars) if (c.VIN) now[c.VIN] = priceOf(c);

  if (!state.cars) {
    const prices = Object.values(now).filter(Boolean);
    const msg = `Şu an ${Object.keys(now).length} araç listede. En ucuzu: ${tl(prices.length ? Math.min(...prices) : null)}`;
    log.push("İlk çalıştırma. " + msg, await notify(env, "Tesla takip aktif ✅", msg, PAGE_URL));
  } else {
    const fresh = cars.filter(c => c.VIN && !(c.VIN in state.cars)).sort((a, b) => (priceOf(a) || 0) - (priceOf(b) || 0));
    for (const c of fresh) log.push(`YENİ ${c.VIN} ${tl(priceOf(c))}`, await notify(env, `🚨 Yeni Model Y: ${tl(priceOf(c))}`, describe(c), link(c)));
    for (const c of cars) {
      const old = state.cars[c.VIN], p = priceOf(c);
      if (old && p && p < old) log.push(`DÜŞÜŞ ${c.VIN}`, await notify(env, `📉 Fiyat düştü: ${tl(p)}`, `${tl(old)} → ${tl(p)}\n${describe(c)}`, link(c)));
    }
    log.push(`${Object.keys(now).length} araç, yeni: ${fresh.length}`);
  }
  const changed = JSON.stringify(now) !== JSON.stringify(state.cars) || state.fails;
  if (changed) await env.STATE.put("state", JSON.stringify({ cars: now, fails: 0 }));  // KV yazma kotasını korumak için sadece değişince yaz
  return log;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(check(env).then(l => console.log(l.join(" | "))));
  },
  async fetch(req, env) {
    const path = new URL(req.url).pathname;
    if (path === "/diag") {
      try {
        const cars = await fetchAll();
        return Response.json({ ok: true, count: cars.length,
          sample: cars.slice(0, 5).map(c => `${tl(priceOf(c))} ${describe(c)}`) });
      } catch (e) { return Response.json({ ok: false, error: e.message }); }
    }
    return new Response("tesla-watch çalışıyor");
  },
};
