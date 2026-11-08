import os
import json
import hashlib
import requests
from curl_cffi import requests as curl_requests

WATCH_FILE = "campaign_watch.json"
STATE_FILE = "campaign_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
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


def fetch_page(url):
    try:
        # impersonate="chrome" ile gerçek bir Chrome tarayıcısının TLS parmak izini taklit eder
        resp = curl_requests.get(url, impersonate="chrome", timeout=45)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        # Hata durumunda daha anlaşılır bir mesaj fırlat
        raise Exception(f"{type(e).__name__}: {e}")


def main():
    with open(WATCH_FILE, "r", encoding="utf-8") as f:
        watch = json.load(f)

    state = load_state()
    changed = []

    for target in watch["targets"]:
        name = target["name"]
        url = target["url"]

        try:
            html = fetch_page(url)
        except Exception as e:
            print(f"[{name}] fetch error: {e}")
            continue

        current_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        previous_hash = state.get(name)

        if previous_hash is None:
            print(f"[{name}] ilk kayıt, hash kaydedildi.")
        elif previous_hash != current_hash:
            print(f"[{name}] DEĞİŞİKLİK TESPİT EDİLDİ.")
            changed.append((name, url))
        else:
            print(f"[{name}] değişiklik yok.")

        state[name] = current_hash

    for name, url in changed:
        send_telegram(f"🔔 <b>[{name}]</b> sayfasında değişiklik var!\n{url}")

    save_state(state)

    print(f"Toplam değişen: {len(changed)}")


if __name__ == "__main__":
    main()
