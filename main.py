import os
import json
import hashlib
import html
import re
import feedparser
import requests
from swoop import search as swoop_search  # Google Flights

# --- Kaynaklar ---
FEEDS = {
    "theflightdeal": "https://www.theflightdeal.com/feed/",
    "fly4free": "https://www.fly4free.pl/feed/",
    "faredealalert": "https://faredealalert.com/feed/",
    "holidaypirates": "https://www.holidaypirates.com/feed",
    "thriftytraveler": "https://thriftytraveler.com/feed/",
    "reddit_awardtravel": "https://www.reddit.com/r/awardtravel/.rss",
    # Cloudflare engeli nedeniyle devre dışı:
    # "secretflying": "https://www.secretflying.com/feed/",
    # "flyertalk_mileagerun": "https://www.flyertalk.com/forum/external.php?type=RSS2&forumids=372",
    # "flyertalk_premium": "https://www.flyertalk.com/forum/external.php?type=RSS2&forumids=740",
}

SOURCE_LABELS = {
    "theflightdeal": "The Flight Deal",
    "fly4free": "Fly4Free",
    "faredealalert": "Fare Deal Alert",
    "holidaypirates": "Holiday Pirates",
    "thriftytraveler": "Thrifty Traveler",
    "reddit_awardtravel": "Reddit r/awardtravel",
    "secretflying": "Secret Flying",
    "flyertalk_mileagerun": "FlyerTalk Mileage Run",
    "flyertalk_premium": "FlyerTalk Premium Fares",
}

SEEN_FILE = "seen.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

KEYWORDS_SUBSTR = ["istanbul", "sabiha", "saw", "türkiye", "turkey", "stambuł"]
KEYWORDS_REGEX = [r"\bIST\b", r"\bSAW\b"]

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

# Google Flights demo: bu rotaları test amaçlı sorgular
GOOGLE_FLIGHTS_DEMO_ROUTES = [
    ("IST", "LHR", "2026-12-15"),
    ("IST", "CDG", "2026-12-20"),
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
    if any(k in haystack for k in KEYWORDS_SUBSTR):
        return True
    return any(re.search(pat, haystack, re.IGNORECASE) for pat in KEYWORDS_REGEX)


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


def check_google_flights(origin, destination, date_str):
    """
    swoop-flights ile Google Flights fiyatlarını çeker.
    Dönen: (min_price, avg_price, sample_airlines) veya None
    """
    try:
        results = swoop_search(origin, destination, date_str)
        if not results.results:
            print(f"  [GF] {origin}->{destination} {date_str}: sonuç yok")
            return None

        prices = [opt.price for opt in results.results if opt.price]
        if not prices:
            print(f"  [GF] {origin}->{destination} {date_str}: fiyat yok")
            return None

        min_price = min(prices)
        avg_price = sum(prices) / len(prices)
        airlines = set()
        for opt in results.results[:5]:
            for leg in opt.legs:
                if leg.itinerary:
                    airlines.add(leg.itinerary.airline_names)

        print(f"  [GF] {origin}->{destination} {date_str}: "
              f"min=${min_price}, avg=${avg_price:.0f}, "
              f"options={len(prices)}, airlines={airlines}")
        return min_price, avg_price, airlines
    except Exception as e:
        print(f"  [GF] {origin}->{destination} {date_str} hata: {e}")
        return None


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

            if not matches_istanbul(haystack):
                continue

            total_matched += 1
            item_id = link if link else hashlib.md5(title.encode("utf-8")).hexdigest()
            if item_id in source_seen:
                continue

            source_seen.add(item_id)
            new_items.append((source, title, link))

    # --- Google Flights test (sadece loglara yazar, Telegram'a göndermez) ---
    print("\n--- Google Flights demo ---")
    for origin, destination, date_str in GOOGLE_FLIGHTS_DEMO_ROUTES:
        check_google_flights(origin, destination, date_str)

    # --- Bildirimler ---
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
