import os
import json
import hashlib
import html
import re
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
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
UCUZAUC_STATE_FILE = "ucuzauc_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

KEYWORDS_SUBSTR = ["istanbul", "sabiha", "stambuł"]
HOTEL_PACKAGE_WORDS = [
    "hotel", "otel", "resort", "all-inclusive", "all inclusive",
    "package", "paket", "villa", "apartment", "cruise",
    "holiday break", "tatil", "konaklama", "accommodation",
]
FLIGHT_WORDS = [
    "flight", "fly", "airline", "airfare",
    "uçuş", "bilet", "ticket", "one-way", "roundtrip", "round-trip",
]
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

USD_TO_TL = 50.0

GOOGLE_FLIGHTS_WATCH = [
    {"name": "IST → Bangkok (esnek)", "origin": "IST", "destination": "BKK",
     "departure_offset_days": 90, "stay_days": 7, "max_price_tl": 29000},
    {"name": "IST → Kuala Lumpur (esnek)", "origin": "IST", "destination": "KUL",
     "departure_offset_days": 60, "stay_days": 14, "max_price_tl": 28000},
    {"name": "IST → Singapore (esnek)", "origin": "IST", "destination": "SIN",
     "departure_offset_days": 60, "stay_days": 10, "max_price_tl": 33000},
    {"name": "IST → Seoul (esnek)", "origin": "IST", "destination": "ICN",
     "departure_offset_days": 90, "stay_days": 10, "max_price_tl": 35000},
    {"name": "IST → Hong Kong (esnek)", "origin": "IST", "destination": "HKG",
     "departure_offset_days": 60, "stay_days": 10, "max_price_tl": 32000},
    {"name": "IST → Manila (esnek)", "origin": "IST", "destination": "MNL",
     "departure_offset_days": 60, "stay_days": 14, "max_price_tl": 39000},
]

UCUZAUC_URL = "https://www.ucuzauc.org/kalkis/istanbul"


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


def load_seen():
    data = _load_json_state(SEEN_FILE)
    return {s: set(ids) for s, ids in data.items() if isinstance(ids, list)}


def save_seen(seen):
    _save_json_state(SEEN_FILE, {s: sorted(list(ids)) for s, ids in seen.items()})


def load_gf_state():
    return _load_json_state(GF_STATE_FILE)


def save_gf_state(state):
    _save_json_state(GF_STATE_FILE, state)


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
# RSS KATMANI
# ============================================================
def matches_istanbul(haystack):
    text = haystack.lower()
    has_hotel = any(w in text for w in HOTEL_PACKAGE_WORDS)
    has_flight = any(w in text for w in FLIGHT_WORDS)
    if has_hotel and not has_flight:
        return False
    if any(k in text for k in KEYWORDS_SUBSTR):
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


# ============================================================
# GOOGLE FLIGHTS KATMANI
# ============================================================
def resolve_dates(route):
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


def parse_ucuzauc_main(html):
    soup = BeautifulSoup(html, "html.parser")
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


def parse_ucuzauc_detail(html):
    soup = BeautifulSoup(html, "html.parser")
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

    check_google_flights_watch()
    check_ucuzauc_all()

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

