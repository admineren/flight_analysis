import os, json, hashlib, feedparser, requests

FEED_URL = "https://www.secretflying.com/feed/"
SEEN_FILE = "seen.json"
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
KEYWORDS = ["istanbul", "ist"]
MAX_NOTIFY = 5

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen)), f, ensure_ascii=False, indent=2)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    if r.status_code != 200:
        print("Telegram error:", r.status_code, r.text)

def main():
    first_run = not os.path.exists(SEEN_FILE)
    feed = feedparser.parse(FEED_URL)
    seen = load_seen()
    new_items = []

    for entry in feed.entries:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "")
        haystack = f"{title} {summary}".lower()
        if not any(k in haystack for k in KEYWORDS):
            continue
        item_id = link if link else hashlib.md5(title.encode()).hexdigest()
        if item_id in seen:
            continue
        seen.add(item_id)
        new_items.append((title, link))

    if first_run:
        send_telegram(
            f"✅ Sistem kuruldu ve çalışıyor. "
            f"Şu an feed'de {len(new_items)} İstanbul fırsatı bulundu; "
            f"bunlar 'görüldü' olarak işaretlendi. Yeni fırsatlarda haber vereceğim."
        )
    else:
        for title, link in new_items[:MAX_NOTIFY]:
            send_telegram(f"✈️ <b>{title}</b>\n{link}")

    save_seen(seen)
    print(f"Done. New: {len(new_items)}, total seen: {len(seen)}")

if __name__ == "__main__":
    main()
