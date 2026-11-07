import os
import json
import hashlib
import re
import feedparser
import requests

FEED_URL = "https://www.secretflying.com/feed/"
SEEN_FILE = "seen.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Kalkış noktası filtreleri
# "ist" kısa olduğu için kelime sınırıyla (regex) aranacak; diğerleri substring.
KEYWORDS_SUBSTR = ["istanbul", "sabiha", "saw", "türkiye", "turkey"]
KEYWORDS_REGEX = [r"\bIST\b"]  # "(IST)" veya " IST " gibi geçişler için

MAX_NOTIFY = 5  # Aynı çalıştırmada en fazla bu kadar mesaj gönder


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
    try:
        r = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)


def matches_istanbul(haystack: str) -> bool:
    if any(k in haystack for k in KEYWORDS_SUBSTR):
        return True
    return any(re.search(pat, haystack, re.IGNORECASE) for pat in KEYWORDS_REGEX)


def main():
    first_run = not os.path.exists(SEEN_FILE)

    feed = feedparser.parse(FEED_URL)
    if not feed.entries:
        print("Feed boş veya okunamadı. URL veya ağ sorunu olabilir.")
        return

    seen = load_seen()
    new_items = []
    matched_count = 0

    for entry in feed.entries:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "")
        haystack = f"{title} {summary}"

        if not matches_istanbul(haystack):
            continue

        matched_count += 1

        item_id = link if link else hashlib.md5(title.encode("utf-8")).hexdigest()
        if item_id in seen:
            continue

        seen.add(item_id)
        new_items.append((title, link))

    # --- Bildirimler ---
    if first_run:
        if new_items:
            send_telegram(
                f"✅ Sistem kuruldu. Feed'de şu an {len(new_items)} İstanbul "
                f"fırsatı bulundu; 'görüldü' olarak işaretlendi. Yenilerde haber vereceğim."
            )
        else:
            send_telegram(
                "✅ Sistem kuruldu ve çalışıyor. Şu an feed'de İstanbul çıkışlı "
                "fırsat yok. Yeni fırsat çıkınca haber vereceğim."
            )
    else:
        for title, link in new_items[:MAX_NOTIFY]:
            send_telegram(f"✈️ <b>{title}</b>\n{link}")
        if len(new_items) > MAX_NOTIFY:
            send_telegram(
                f"ℹ️ Toplam {len(new_items)} yeni fırsat var; "
                f"ilk {MAX_NOTIFY} tanesi gönderildi."
            )

    save_seen(seen)

    print(
        f"Feed entries: {len(feed.entries)}, "
        f"keyword-matched: {matched_count}, "
        f"new: {len(new_items)}, "
        f"total seen: {len(seen)}"
    )


if __name__ == "__main__":
    main()
