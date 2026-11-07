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
}

SOURCE_LABELS = {
    "secretflying": "Secret Flying",
    "theflightdeal": "The Flight Deal",
    "fly4free": "Fly4Free",
}

SEEN_FILE = "seen.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Kalkış filtresi
KEYWORDS_SUBSTR = ["istanbul", "sabiha", "saw", "türkiye", "turkey", "stambuł"]
KEYWORDS_REGEX = [r"\bIST\b"]

MAX_NOTIFY = 5


# --- seen.json yönetimi (kaynak bazlı) ---
def load_seen():
    """dict[str, set[str]] döndürür. Eski düz liste formatını da migrate eder."""
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    # Eski format: düz liste -> "secretflying" altına taşı
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


def main():
    first_run = not os.path.exists(SEEN_FILE)
    seen = load_seen()

    total_entries = 0
    total_matched = 0
    new_items = []  # (source, title, link)

    for source, url in FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[{source}] parse error: {e}")
            continue

        entries = feed.entries or []
        total_entries += len(entries)

        if not entries:
            print(f"[{source}] feed boş veya okunamadı.")
            continue

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

    print(
        f"Feeds: {len(FEEDS)}, entries: {total_entries}, "
        f"matched: {total_matched}, new: {len(new_items)}, "
        f"sources in seen: {sorted(seen.keys())}"
    )


if __name__ == "__main__":
    main()
