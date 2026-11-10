import os
import json
import re
import requests
from bs4 import BeautifulSoup

# --- Ucuza Uç Kaynağı ---
UCUZAUC_URL = "https://www.ucuzauc.org/kalkis/istanbul"
UCUZAUC_STATE_FILE = "ucuzauc_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_NOTIFY = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

# ============================================================
# STATE YÖNETİMİ
# ============================================================
def _load_json_state(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return default if default is not None else {}
        data = json.loads(content)
        return data if isinstance(data, dict) else (default if default is not None else {})
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def _save_json_state(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_ucuzauc_state():
    return _load_json_state(UCUZAUC_STATE_FILE)


def save_ucuzauc_state(state):
    _save_json_state(UCUZAUC_STATE_FILE, state)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)

# ============================================================
# UCUZA UÇ KATMANI
# ============================================================
def filter_tags(tags):
    time_patterns = [
        r"^\d+\s*(dakika|saat|gün|hafta|ay|yıl)\s*önce$",
        r"^(dün|bugün)$",
    ]
    filtered, seen = [], set()
    for tag in tags:
        t = tag.strip()
        if not t or any(re.match(p, t.lower()) for p in time_patterns):
            continue
        if t in seen:
            continue
        seen.add(t)
        filtered.append(t)
    return filtered


def parse_ucuzauc_main(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    routes, warnings = {}, []

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        route_raw = cells[0].get_text(" ", strip=True)
        route_name = re.sub(r"\s*rehber\s*$", "", route_raw, flags=re.IGNORECASE).strip()
        if not route_name:
            continue

        pub_text = cells[1].get_text(" ", strip=True)
        pub_match = re.search(r"(\d+)", pub_text)
        pub_count = int(pub_match.group(1)) if pub_match else None

        price_date_text = cells[2].get_text(" ", strip=True)
        price_match = re.search(r"(\d{1,3}(?:\.\d{3})*)\s*TL", price_date_text)
        lowest = int(price_match.group(1).replace(".", "")) if price_match else None

        date_match = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", price_date_text)
        caught_date = date_match.group(1) if date_match else None

        route_href = None
        for a in cells[3].find_all("a", href=True):
            if "/ucuz-ucak-biletleri/" in a["href"]:
                route_href = a["href"]
                break

        if pub_count is None or lowest is None:
            warnings.append(f"{route_name}: pub={pub_count}, lowest={lowest}")
            continue

        routes[route_name] = {
            "pub_count": pub_count,
            "lowest_ever": lowest,
            "caught_date": caught_date,
            "href": route_href,
        }

    return routes, warnings


def parse_ucuzauc_detail(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(" ", strip=True)

    current_match = re.search(r"(\d{1,3}\.\d{3})\s*₺", text)
    current_price = int(current_match.group(1).replace(".", "")) if current_match else None

    month_match = re.search(
        r"en ucuz\s+([\wçğıöşüÇĞİÖŞÜ]+\s*\d+)\s*\(\s*([\d\.]+)\s*₺",
        text, re.IGNORECASE
    )
    cheapest_month = month_match.group(1) if month_match else None
    cheapest_month_price = int(month_match.group(2).replace(".", "")) if month_match else None

    normal_match = re.search(r"aylık normal fiyat\s*([\d\.]+)\s*₺", text)
    normal_price = int(normal_match.group(1).replace(".", "")) if normal_match else None

    raw_tags = [t.get_text(strip=True) for t in soup.select("span.tag")[:10]]
    tags = filter_tags(raw_tags)[:5]

    return {
        "current_price": current_price,
        "cheapest_month": cheapest_month,
        "cheapest_month_price": cheapest_month_price,
        "normal_price": normal_price,
        "tags": tags,
    }


def format_ucuzauc_notification(route_name, change, detail, href):
    base = ""
    if change["type"] == "new_record":
        base = (
            f"🏆 <b>[Ucuza Uç] {route_name}</b> — YENİ REKOR\n"
            f"📉 {change['old_low']:,} ₺ → <b>{change['new_low']:,} ₺</b> "
            f"(%{change['drop_pct']:.0f} düşüş)\n"
            f"📅 Yakalandı: {change['data']['caught_date']}"
        )
    elif change["type"] == "new_publish":
        base = (
            f"🎯 <b>[Ucuza Uç] {route_name}</b> — YENİ FIRSAT\n"
            f"📢 Yayın: {change['old_pub']} → {change['new_pub']}\n"
            f"💰 En düşük: <b>{change['data']['lowest_ever']:,} ₺</b>\n"
            f"📅 Yakalandı: {change['data']['caught_date']}"
        )

    if detail:
        if detail.get("tags"):
            base += f"\n🏷️ {', '.join(detail['tags'][:3])}"
        current = detail.get("current_price")
        normal = detail.get("normal_price")
        if current and normal:
            diff = abs(normal - current) / normal * 100
            direction = "altında ✅" if current < normal else "üstünde ⚠️"
            base += f"\n💰 Şu an: {current:,} ₺ (normalin %{diff:.0f} {direction})"
        if detail.get("cheapest_month") and detail.get("cheapest_month_price"):
            base += f"\n🗓️ En ucuz ay: {detail['cheapest_month']} ({detail['cheapest_month_price']:,} ₺)"

    url = f"https://www.ucuzauc.org{href}" if href and href.startswith("/") else (
        href or f"https://www.ucuzauc.org/ucuz-ucak-biletleri/istanbul-{route_name.lower()}"
    )
    base += f"\n🔗 {url}"
    return base


def check_ucuzauc_all():
    state = load_ucuzauc_state()
    first_run = not os.path.exists(UCUZAUC_STATE_FILE)

    print("\n--- Ucuza Uç ---")
    try:
        resp = requests.get(UCUZAUC_URL, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code}, atlandı")
            return 0
        html_text = resp.text
    except Exception as e:
        print(f"  fetch hata: {e}")
        return 0

    routes, warnings = parse_ucuzauc_main(html_text)
    print(f"  {len(routes)} rota parse, {len(warnings)} uyarı")
    if warnings:
        for w in warnings[:3]:
            print(f"    ⚠️ {w}")

    if first_run:
        for name, data in routes.items():
            state[name] = {
                "pub_count": data["pub_count"],
                "lowest_ever": data["lowest_ever"],
                "caught_date": data["caught_date"],
                "href": data["href"],
            }
        save_ucuzauc_state(state)
        print(f"  İlk kayıt: {len(routes)} rota (bildirim yok)")
        return 0

    changes = []
    for name, data in routes.items():
        old = state.get(name)
        if not old:
            continue

        if data["pub_count"] > old.get("pub_count", 0):
            changes.append({
                "route": name, "type": "new_publish",
                "old_pub": old["pub_count"], "new_pub": data["pub_count"],
                "data": data,
            })
        elif data["lowest_ever"] < old.get("lowest_ever", 10**9):
            drop_pct = (old["lowest_ever"] - data["lowest_ever"]) / old["lowest_ever"] * 100
            changes.append({
                "route": name, "type": "new_record",
                "old_low": old["lowest_ever"], "new_low": data["lowest_ever"],
                "drop_pct": drop_pct, "data": data,
            })

    alerts = 0
    for change in changes[:MAX_NOTIFY]:
        name = change["route"]
        href = change["data"].get("href")
        detail = None

        if href:
            try:
                detail_url = f"https://www.ucuzauc.org{href}" if href.startswith("/") else href
                detail_resp = requests.get(detail_url, headers=HEADERS, timeout=30)
                if detail_resp.status_code == 200:
                    detail = parse_ucuzauc_detail(detail_resp.text)
            except Exception as e:
                print(f"  [{name}] detay hata: {e}")

        msg = format_ucuzauc_notification(name, change, detail, href)
        send_telegram(msg)
        alerts += 1

    if len(changes) > MAX_NOTIFY:
        send_telegram(f"ℹ️ Ucuza Uç: {len(changes)} değişiklik, ilk {MAX_NOTIFY} gönderildi")

    for name, data in routes.items():
        state[name] = {
            "pub_count": data["pub_count"],
            "lowest_ever": data["lowest_ever"],
            "caught_date": data["caught_date"],
            "href": data["href"],
        }

    save_ucuzauc_state(state)
    print(f"  {len(changes)} değişiklik, {alerts} bildirim")
    return alerts


# ============================================================
# ANA AKIŞ
# ============================================================
def main():
    print("=== Ucuza Uç Monitor Başladı ===")
    check_ucuzauc_all()
    print("=== Tamamlandı ===")


if __name__ == "__main__":
    main()
