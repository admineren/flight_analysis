import os
import json
import hashlib
import html
import re
import feedparser
import requests

# --- Kaynaklar ---
FEEDS = {
    "secretflying": "https://www.secretflying.com/feed/",
    "theflightdeal": "https://www.theflightdeal.com/feed/",
    "fly4free": "https://www.fly4free.pl/feed/",
    "faredealalert": "https://faredealalert.com/feed/",
    "holidaypirates": "https://www.holidaypirates.com/feed",
    "flyertalk_mileagerun": "https://www.flyertalk.com/forum/external.php?type=RSS2&forumids=372",
    "flyertalk_premium": "https://www.flyertalk.com/forum/external.php?type=RSS2&forumids=740",
    "thriftytraveler": "https://thriftytraveler.com/feed/",
}

SOURCE_LABELS = {
    "secretflying": "Secret Flying",
    "theflightdeal": "The Flight Deal",
    "fly4free": "Fly4Free",
    "faredealalert": "Fare Deal Alert",
    "holidaypirates": "Holiday Pirates",
    "flyertalk_mileagerun": "FlyerTalk Mileage Run",
    "flyertalk_premium": "FlyerTalk Premium Fares",
    "thriftytraveler": "Thrifty Traveler",
}

SEEN_FILE = "seen.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Kalkış filtresi
KEYWORDS_SUBSTR = [
    "istanbul", "sabiha", "saw", "türkiye", "turkey",
    "stambuł",
]
KEYWORDS_REGEX = [r"\bIST\b", r"\bSAW\b"]

MAX_NOTIFY = 5

# Bot korumasını aşmak için gerçekçi tarayıcı kimliği
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


# --- seen.json yönetimi ---
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
        result = {}
        for source, ids in data.items():
            if isinstance(ids, list):
                result[source] = set(ids)
        return result

    return {}


def save_seen(seen):
    serializable = {src: sorted(list(ids)) for src, ids in seen.items()}
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2, sort_keys=True)


# --- Bildirim ---
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
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


# --- Feed çekme: önce requests, sonra feedparser ---
def fetch_feed(url):
    """
    Returns (feed_obj, status_info).
    feed_obj: feedparser sonucu (entries dolu veya boş)
    status_info: log için kısa string
    """
    # 1. requests ile çek (User-Agent + HTTP durum kodu görünür)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        status = resp.status_code
        if status == 200:
            feed = feedparser.parse(resp.content)
            if feed.entries:
                return feed, f"HTTP 200 ({len(feed.entries)} entries)"
            # 200 ama boş/parse edilemiyor
            return feed, f"HTTP 200 ama boş içerik"
        if status in (403, 503):
            return None, f"HTTP {status} (bot koruması)"
        return None, f"HTTP {status}"
    except requests.exceptions.RequestException as e:
        print(f"  requests error: {e}")
        # 2. Fallback: feedparser doğrudan denesin
        try:
            feed = feedparser.parse(url, agent=HEADERS["User-Agent"])
            if feed.entries:
                return feed, f"fallback feedparser ({len(feed.entries)} entries)"
            return feed, "fallback boş"
        except Exception as e2:
            print(f"  feedparser fallback error: {e2}")
            return None, "bağlantı hatası"


def main():
    first_run = not os.path.exists(SEEN_FILE)
    seen = load_seen()

    total_entries = 0
    total_matched = 0
    new_items = []
    source_stats = {}
    source_status = {}

    for source, url in FEEDS.items():
        print(f"[{source}] fetching {url}")
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
                f"bulundu ({breakdown}); 'görüldü' olarak işaretlendi. "
                f"Yenilerde haber vereceğim."
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
