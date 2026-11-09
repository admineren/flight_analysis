import os
import json
import hashlib
import html
import re
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from swoop import search as swoop_search

# --- Kaynaklar ---
FEEDS = {
    "theflightdeal": "https://www.theflightdeal.com/feed/",
    "fly4free": "https://www.fly4free.pl/feed/",
    "faredealalert": "https://faredealalert.com/feed/",
    "holidaypirates": "https://www.holidaypirates.com/feed",
    "thriftytraveler": "https://thriftytraveler.com/feed/",
    "reddit_awardtravel": "https://www.reddit.com/r/awardtravel/.rss",
}

SOURCE_LABELS = {
    "theflightdeal": "The Flight Deal",
    "fly4free": "Fly4Free",
    "faredealalert": "Fare Deal Alert",
    "holidaypirates": "Holiday Pirates",
    "thriftytraveler": "Thrifty Traveler",
    "reddit_awardtravel": "Reddit r/awardtravel",
}

SEEN_FILE = "seen.json"
GF_STATE_FILE = "gf_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

KEYWORDS_SUBSTR = ["istanbul", "sabiha", "türkiye", "turkey", "stambuł"]
MAX_NOTIFY = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Cache-Control": "no-cache",
}
REQUEST_TIMEOUT = 20

# --- Google Flights Watchlist ---
# İki mod destekleniyor:
#   1) departure_offset_days + stay_days → tarihler her çalıştırmada bugüne göre hesaplanır
#   2) departure + return_date → sabit tarih; geçmişse +90 gün kaydırılır
USD_TO_TL = 50.0

GOOGLE_FLIGHTS_WATCH = [
    {
        "name": "IST → Bangkok (esnek)",
        "origin": "IST", "destination": "BKK",
        "departure_offset_days": 90, "stay_days": 7,
        "max_price_tl": 29000,   # 33.850 → 29.000 (~%14 düşüş)
    },
    {
        "name": "IST → Kuala Lumpur (esnek)",
        "origin": "IST", "destination": "KUL",
        "departure_offset_days": 60, "stay_days": 14,
        "max_price_tl": 28000,   # 32.450 → 28.000 (~%14 düşüş)
    },
    {
        "name": "IST → Singapore (esnek)",
        "origin": "IST", "destination": "SIN",
        "departure_offset_days": 60, "stay_days": 10,
        "max_price_tl": 33000,   # 38.500 → 33.000 (~%14 düşüş)
    },
    {
        "name": "IST → Seoul (esnek)",
        "origin": "IST", "destination": "ICN",
        "departure_offset_days": 90, "stay_days": 10,
        "max_price_tl": 35000,   # 40.700 → 35.000 (~%14 düşüş)
    },
    {
        "name": "IST → Hong Kong (esnek)",
        "origin": "IST", "destination": "HKG",
        "departure_offset_days": 60, "stay_days": 10,
        "max_price_tl": 32000,   # 37.100 → 32.000 (~%14 düşüş)
    },
    {
        "name": "IST → Manila (esnek)",
        "origin": "IST", "destination": "MNL",
        "departure_offset_days": 60, "stay_days": 14,
        "max_price_tl": 39000,   # 45.300 → 39.000 (~%14 düşüş)
    },
]


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, list):
        return {"secretflying": set(data)}
    if isinstance(data, dict):
        return {s: set(ids) for s, ids in data.items() if isinstance(ids, list)}
    return {}


def save_seen(seen):
    serializable = {src: sorted(list(ids)) for src, ids in seen.items()}
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_gf_state():
    if not os.path.exists(GF_STATE_FILE):
        return {}
    try:
        with open(GF_STATE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return {}


def save_gf_state(state):
    tmp = GF_STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, GF_STATE_FILE)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)


def matches_istanbul(haystack):
    if any(k in haystack.lower() for k in KEYWORDS_SUBSTR):
        return True
    if re.search(r"\bIST\b", haystack, re.IGNORECASE):
        return True
    if re.search(r"\bSAW\b", haystack):
        return True
    return False


def fetch_feed(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            feed = feedparser.parse(resp.content)
            if feed.entries:
                return feed, f"HTTP 200 ({len(feed.entries)} entries)"
            return feed, "HTTP 200 ama boş içerik"
        if resp.status_code in (403, 503):
            return None, f"HTTP {resp.status_code} (bot koruması)"
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        print(f"  requests error: {e}")
        try:
            feed = feedparser.parse(url, agent=HEADERS["User-Agent"])
            if feed.entries:
                return feed, f"fallback ({len(feed.entries)} entries)"
            return feed, "fallback boş"
        except Exception as e2:
            print(f"  feedparser fallback error: {e2}")
            return None, "bağlantı hatası"


def resolve_dates(route):
    """Route'daki tarihleri bugüne göre çöz. Geçmiş tarihleri otomatik kaydır."""
    today = datetime.now(timezone.utc).date()
    min_date = today + timedelta(days=3)

    if "departure_offset_days" in route:
        depart = today + timedelta(days=route["departure_offset_days"])
    else:
        depart = datetime.strptime(route["departure"], "%Y-%m-%d").date()
        if depart < min_date:
            shift = (min_date - depart).days + 90
            depart = depart + timedelta(days=shift)
            print(f"  ⚠️ {route['name']}: tarih geçmiş, +{shift} gün kaydırıldı → {depart}")

    if "stay_days" in route:
        ret = depart + timedelta(days=route["stay_days"])
    else:
        ret = datetime.strptime(route["return_date"], "%Y-%m-%d").date()
        if ret < depart + timedelta(days=1):
            ret = depart + timedelta(days=7)
            print(f"  ⚠️ {route['name']}: dönüş tarihi geçersiz, +7 gün → {ret}")

    return depart, ret


def check_google_flights_watch():
    """Google Flights rotalarını tara, eşik altındakileri Telegram'a gönder."""
    gf_state = load_gf_state()
    first_run = not os.path.exists(GF_STATE_FILE)
    today = datetime.now(timezone.utc).date()

    print("\n--- Google Flights ---")
    alerts = 0

    for route in GOOGLE_FLIGHTS_WATCH:
        name = route["name"]
        depart, ret_date = resolve_dates(route)
        state_key = f"{name}|{depart}|{ret_date}"

        try:
            out = swoop_search(route["origin"], route["destination"], str(depart))
            ret = swoop_search(route["destination"], route["origin"], str(ret_date))

            if not out.results or not ret.results:
                print(f"  [{name}] {depart}→{ret_date}: sonuç yok")
                continue

            out_min = min(opt.price for opt in out.results if opt.price)
            ret_min = min(opt.price for opt in ret.results if opt.price)
            total_usd = out_min + ret_min
            total_tl = total_usd * USD_TO_TL

            prev = gf_state.get(state_key, {})
            prev_tl = prev.get("last_tl")
            was_below = prev.get("below_threshold", False)
            below = total_tl <= route["max_price_tl"]

            trend = ""
            if prev_tl and prev_tl > total_tl:
                pct = (prev_tl - total_tl) / prev_tl * 100
                if pct >= 3:
                    trend = f" (↓ %{pct:.0f})"

            print(f"  [{name}] {depart}→{ret_date} | "
                  f"{total_usd} USD = {total_tl:,.0f} TL | "
                  f"eşik {route['max_price_tl']:,} | altında: {below}{trend}")

            if first_run:
                pass
            elif below and not was_below:
                send_telegram(
                    f"✈️ <b>[Google Flights] {name}</b>\n"
                    f"📅 {depart} → {ret_date}\n"
                    f"💰 ~<b>{total_tl:,.0f} TL</b>{trend}\n"
                    f"⚠️ <i>USD bazlı tahmin, fiyat +1-3K farklı olabilir</i>"
                )
                alerts += 1
            elif below and was_below and trend:
                send_telegram(
                    f"📉 <b>[Google Flights] {name}</b> daha da düştü\n"
                    f"📅 {depart} → {ret_date}\n"
                    f"💰 ~<b>{total_tl:,.0f} TL</b>{trend}"
                )
                alerts += 1

            gf_state[state_key] = {
                "last_tl": total_tl,
                "below_threshold": below,
            }
        except Exception as e:
            print(f"  [{name}] hata: {type(e).__name__}: {e}")

    # Eski state key'lerini temizle (geçmiş tarihli)
    today_str = str(today)
    removed = 0
    for k in list(gf_state.keys()):
        parts = k.split("|")
        if len(parts) == 3 and parts[1] < today_str:
            del gf_state[k]
            removed += 1
    if removed:
        print(f"  🗑️ {removed} eski state temizlendi")

    save_gf_state(gf_state)
    print(f"  Google Flights: {alerts} yeni alert")
    return alerts


def main():
    first_run = not os.path.exists(SEEN_FILE)
    seen = load_seen()

    total_entries = 0
    total_matched = 0
    new_items = []
    source_stats = {}
    source_status = {}

    for source, url in FEEDS.items():
        feed, status = fetch_feed(url)
        source_status[source] = status

        if feed is None or not feed.entries:
            print(f"[{source}] okunamadı: {status}")
            source_stats[source] = 0
            continue

        entries = feed.entries
        source_stats[source] = len(entries)
        total_entries += len(entries)
        print(f"[{source}] {status}")

        source_seen = seen.setdefault(source, set())

        for entry in entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            haystack = f"{title} {summary}"

            if source == "reddit_awardtravel":
                tags = entry.get("tags", [])
                tag_terms = [t.get("term", "").lower() for t in tags]
                if not any("deal" in term for term in tag_terms):
                    continue

            if not matches_istanbul(haystack):
                continue

            total_matched += 1
            item_id = link if link else hashlib.md5(title.encode("utf-8")).hexdigest()
            if item_id in source_seen:
                continue

            source_seen.add(item_id)
            new_items.append((source, title, link))

    # --- Google Flights watch ---
    check_google_flights_watch()

    # --- RSS Bildirimler ---
    if first_run:
        if new_items:
            by_source = {}
            for src, _, _ in new_items:
                by_source[src] = by_source.get(src, 0) + 1
            breakdown = ", ".join(
                f"{SOURCE_LABELS.get(s, s)}: {c}" for s, c in by_source.items()
            )
            send_telegram(
                f"✅ Sistem kuruldu. Toplam {len(new_items)} İstanbul fırsatı "
                f"bulundu ({breakdown}); 'görüldü' işaretlendi. Yenilerde haber vereceğim."
            )
        else:
            send_telegram(
                "✅ Sistem kuruldu ve çalışıyor. Şu an hiçbir kaynakta İstanbul "
                "çıkışlı fırsat yok. Yeni fırsat çıkınca haber vereceğim."
            )
    else:
        for source, title, link in new_items[:MAX_NOTIFY]:
            label = SOURCE_LABELS.get(source, source)
            safe_title = html.escape(title)
            send_telegram(f"✈️ <b>[{label}]</b> {safe_title}\n{link}")
        if len(new_items) > MAX_NOTIFY:
            send_telegram(
                f"ℹ️ Toplam {len(new_items)} yeni fırsat var; "
                f"ilk {MAX_NOTIFY} tanesi gönderildi."
            )

    save_seen(seen)

    print("=" * 60)
    print(f"Feeds: {len(FEEDS)}, entries: {total_entries}, "
          f"matched: {total_matched}, new: {len(new_items)}")
    print("Per-source entries:", source_stats)
    print("Per-source status:", source_status)
    print("Sources in seen:", sorted(seen.keys()))


if __name__ == "__main__":
    main()
