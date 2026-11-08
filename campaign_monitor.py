import os
import json
import re
from curl_cffi import requests as curl_requests

WATCH_FILE = "campaign_watch.json"
STATE_FILE = "campaign_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = curl_requests.post(
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


def fetch_page(url):
    try:
        resp = curl_requests.get(url, impersonate="chrome", timeout=45)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        raise Exception(f"{type(e).__name__}: {e}")


def normalize(text):
    """Dinamik içeriği (tarih, sayı, saat) temizle, küçük harfe çevir."""
    t = text.lower()
    t = re.sub(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", " ", t)  # 12.05.2026
    t = re.sub(r"\d{1,2}:\d{2}", " ", t)                   # 14:30
    t = re.sub(r"\b\d+\b", " ", t)                         # sayılar
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_items(html):
    """Sayfadan kampanya başlıklarını ve anlamlı link metinlerini çıkar."""
    # script ve style'ları at
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)

    items = set()

    # Başlıklar (h1-h4)
    for m in re.finditer(r"<h[1-4][^>]*>(.*?)</h[1-4]>", html, re.DOTALL | re.IGNORECASE):
        text = re.sub(r"<[^>]+>", " ", m.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 5:
            n = normalize(text)
            if len(n) > 3:
                items.add(n)

    # Link metinleri
    for m in re.finditer(r"<a[^>]*>(.*?)</a>", html, re.DOTALL | re.IGNORECASE):
        text = re.sub(r"<[^>]+>", " ", m.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if 5 < len(text) < 200:
            n = normalize(text)
            if len(n) > 3:
                items.add(n)

    return items


def main():
    with open(WATCH_FILE, "r", encoding="utf-8") as f:
        watch = json.load(f)

    state = load_state()

    for target in watch["targets"]:
        name = target["name"]
        url = target["url"]

        try:
            html = fetch_page(url)
        except Exception as e:
            print(f"[{name}] fetch error: {e}")
            continue

        try:
            items = extract_items(html)
        except Exception as e:
            print(f"[{name}] extract error: {e}")
            continue

        if not items:
            print(f"[{name}] sayfadan hiç öğe çıkarılamadı (yapı değişmiş olabilir).")
            continue

        prev = set(state.get(name, []))

        if not prev:
            print(f"[{name}] ilk kayıt: {len(items)} öğe kaydedildi.")
            state[name] = sorted(items)
            continue

        new_items = items - prev
        removed = prev - items

        if new_items:
            print(f"[{name}] {len(new_items)} YENİ öğe:")
            for item in sorted(new_items)[:5]:
                print(f"  + {item[:80]}")

            preview = "\n".join(f"• {item[:100]}" for item in sorted(new_items)[:3])
            send_telegram(
                f"🔔 <b>[{name}]</b> sayfasında {len(new_items)} yeni kampanya/başlık var:\n"
                f"{preview}\n\n{url}"
            )
        elif removed:
            print(f"[{name}] {len(removed)} öğe kalktı (bildirim yok).")
        else:
            print(f"[{name}] değişiklik yok ({len(items)} öğe).")

        state[name] = sorted(items)

    save_state(state)


if __name__ == "__main__":
    main()
