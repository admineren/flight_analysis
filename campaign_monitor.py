import os
import json
import re
import html as html_lib
from urllib.parse import urljoin
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

WATCH_FILE = "campaign_watch.json"
STATE_FILE = "campaign_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


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
            json={"chat_id": CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
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
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def extract_items(html, selector, mode, base_url):
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    soup = BeautifulSoup(html, "html.parser")
    items = {}

    if not selector:
        return items

    for node in soup.select(selector):
        if mode == "links":
            a = node if node.name == "a" else node.find("a", href=True)
            if not a or not a.get("href"):
                continue
            href = urljoin(base_url, a["href"])
            # UTM parametrelerini temizle (aynı kampanya farklı URL üretmesin)
            href = re.sub(r"[?&]utm_[^&]+", "", href).rstrip("?&")
            # Link metnini de etiket olarak kullan
            label = html_lib.unescape(a.get_text(" ", strip=True))
            label = re.sub(r"\s+", " ", label).strip()
            items[href] = label or href
        else:  # text
            text = html_lib.unescape(node.get_text(" ", strip=True))
            text = re.sub(r"\s+", " ", text).strip()
            if 5 < len(text) < 200:
                items[normalize(text)] = text

    return items


def main():
    with open(WATCH_FILE, "r", encoding="utf-8") as f:
        watch = json.load(f)

    state = load_state()

    for target in watch["targets"]:
        name = target["name"]
        url = target["url"]
        selector = target.get("selector")
        mode = target.get("mode", "text")

        try:
            html = fetch_page(url)
        except Exception as e:
            print(f"[{name}] fetch error: {e}")
            continue

        try:
            items = extract_items(html, selector, mode, url)
        except Exception as e:
            print(f"[{name}] extract error: {e}")
            continue

        if not items:
            print(f"[{name}] hiç öğe çıkarılamadı.")
            continue

        prev = set(state.get(name, []))
        current = set(items.keys())
        new_keys = current - prev
        removed = prev - current

        if not prev:
            print(f"[{name}] ilk kayıt: {len(current)} öğe.")
            state[name] = sorted(current)
            continue

        if new_keys:
            print(f"[{name}] {len(new_keys)} YENİ:")
            for k in sorted(new_keys):
                print(f"  + {k}")
                print(f"    {items[k][:80]}")

            lines = []
            for k in sorted(new_keys)[:5]:
                label = items[k][:100] or k
                lines.append(f"• <a href=\"{k}\">{html_lib.escape(label)}</a>")
            send_telegram(
                f"🔔 <b>[{name}]</b> sayfasında {len(new_keys)} yeni kampanya:\n"
                + "\n".join(lines)
            )
        elif removed:
            print(f"[{name}] {len(removed)} öğe kalktı (bildirim yok).")
        else:
            print(f"[{name}] değişiklik yok ({len(current)} öğe).")

        state[name] = sorted(current)

    save_state(state)


if __name__ == "__main__":
    main()
