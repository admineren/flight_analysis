import os
import json
from datetime import datetime, timedelta, timezone
from curl_cffi import requests as curl_requests

WATCH_FILE = "turna_watch.json"
STATE_FILE = "turna_state.json"

API_URL = "https://www.turna.com/api/proxy/v1/analytics/cheapest/flights_to"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Origin": "https://www.turna.com",
    "Referer": "https://www.turna.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_NOTIFY = 5
MAX_SUSPICIOUS_NOTIFY = 2


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        print(f"State okunamadı: {e}")
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = curl_requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)


def build_url(route, dep, ret):
    origin_slug = route.get("origin_slug", route["origin"].lower())
    dest_slug = route.get("destination_slug", route["destination"].lower())
    combined = f"{origin_slug}-{dest_slug}"
    return (
        f"https://www.turna.com/ucak-bileti/gidis-donus/"
        f"{combined}/{dep}/{ret}?adult=1"
    )


def search_route(route):
    today = datetime.now(timezone.utc).date()
    start = today + timedelta(days=2)
    end = today + timedelta(days=route.get("lookahead_days", 120))

    body = {
        "Origins": [{"Code": route["origin"]}],
        "Destination": {"Code": route["destination"]},
        "MaxNumberOfResults": route.get("max_results", 200),
        "TripType": "RT",
        "StartDate": start.strftime("%Y-%m-%d"),
        "EndDate": end.strftime("%Y-%m-%d"),
        "FetchSegmentDetails": True,
        "Currency": "TRY",
        "Language": "TR",
        "CallerId": "saka",
        "RoundTripOptions": {
            "MinStay": route.get("min_stay", 3),
            "MaxStay": route.get("max_stay", 21),
        },
    }

    try:
        resp = curl_requests.post(API_URL, headers=HEADERS, json=body,
                                  impersonate="chrome", timeout=90)
        if resp.status_code != 200:
            print(f"[{route['name']}] HTTP {resp.status_code}")
            return None
        return resp.json()
    except Exception as e:
        print(f"[{route['name']}] fetch hata: {e}")
        return None


def process_route(route, data):
    flights = data if isinstance(data, list) else (
        data.get("Flights") or data.get("Results") or data.get("Data") or []
    )
    if not flights:
        return [], [], 0

    by_pair = {}
    for f in flights:
        dep = f.get("OutboundDepartureDate", "")[:10]
        ret = f.get("InboundDepartureDate", "")[:10]
        key = (dep, ret)
        if key not in by_pair or f["AdultNetFare"] < by_pair[key]["AdultNetFare"]:
            by_pair[key] = f

    prices = sorted(f["AdultNetFare"] for f in by_pair.values())
    if not prices:
        return [], [], 0

    median = prices[len(prices) // 2]
    suspicious_threshold = median * 0.30

    max_price = route.get("max_price", float("inf"))
    max_stops = route.get("max_stops", 99)
    min_seats = route.get("min_seats", 1)

    normal, suspicious = [], []

    for (dep, ret), f in by_pair.items():
        price = f["AdultNetFare"]
        if price > max_price:
            continue
        if f.get("NumStops", 0) > max_stops:
            continue
        if f.get("AvailableSeats", 0) < min_seats:
            continue

        if price < suspicious_threshold:
            suspicious.append((dep, ret, f))
        else:
            normal.append((dep, ret, f))

    normal.sort(key=lambda x: x[2]["AdultNetFare"])
    suspicious.sort(key=lambda x: x[2]["AdultNetFare"])

    return normal, suspicious, median


def deal_id(dep, ret, flight):
    airline = flight.get("Airline", {}).get("AirlineName", "?")
    return f"{dep}|{ret}|{airline}|{flight['AdultNetFare']:.0f}"


def format_normal(route, dep, ret, f):
    airline = f.get("Airline", {}).get("AirlineName", "?")
    price = f["AdultNetFare"]
    stops = f.get("NumStops", 0)
    dur_h, dur_m = divmod(int(f.get("DurationInMinutes", 0)), 60)
    seats = f.get("AvailableSeats", "?")
    url = build_url(route, dep, ret)

    return (
        f"✈️ <b>{route['name']}</b>\n"
        f"📅 {dep} → {ret}\n"
        f"💰 ~<b>{price:,.0f} TL</b> (eşik: {route.get('max_price', 0):,.0f})\n"
        f"🛫 {airline} | {stops} aktarma | {dur_h}s {dur_m:02d}dk | 💺 {seats}\n"
        f"⚠️ <i>API tahmini — Turna.com'da +1-3K fark olabilir, doğrula</i>\n"
        f"🔗 {url}"
    )


def format_suspicious(route, dep, ret, f, median):
    airline = f.get("Airline", {}).get("AirlineName", "?")
    price = f["AdultNetFare"]
    url = build_url(route, dep, ret)

    return (
        f"⚠️ <b>ŞÜPHELİ — {route['name']}</b>\n"
        f"📅 {dep} → {ret}\n"
        f"🛫 {airline}\n"
        f"💰 API: {price:,.0f} TL | rotadaki medyan: {median:,.0f} TL\n"
        f"<i>Bu fiyat normalin çok altında. API glitch'i VEYA gerçek error fare olabilir. MUTLAKA manuel kontrol et.</i>\n"
        f"🔗 {url}"
    )


def main():
    first_run = not os.path.exists(STATE_FILE)
    state = load_state()

    with open(WATCH_FILE, "r", encoding="utf-8") as f:
        watch = json.load(f)

    total_new = 0
    total_suspicious = 0

    for route in watch["routes"]:
        name = route["name"]
        print(f"\n[{name}] taranıyor...")

        data = search_route(route)
        if not data:
            continue

        normal, suspicious, median = process_route(route, data)
        print(f"  normal: {len(normal)} | şüpheli: {len(suspicious)} | medyan: {median:,.0f}")

        if first_run:
            ids = {deal_id(dep, ret, f) for dep, ret, f in normal}
            state[name] = sorted(ids)
            print(f"  ilk kayıt: {len(ids)} fırsat")
            if suspicious:
                print(f"  ilk çalıştırmada {len(suspicious)} şüpheli (bildirim yok)")
            continue

        route_seen = set(state.get(name, []))

        if suspicious:
            print(f"  ⚠️ {len(suspicious)} şüpheli:")
            for dep, ret, f in suspicious[:MAX_SUSPICIOUS_NOTIFY]:
                airline = f.get("Airline", {}).get("AirlineName", "?")
                print(f"    {dep}→{ret} {airline} {f['AdultNetFare']:,.0f} TL")
                send_telegram(format_suspicious(route, dep, ret, f, median))
            total_suspicious += len(suspicious)

        new_normal = [(dep, ret, f) for dep, ret, f in normal
                      if deal_id(dep, ret, f) not in route_seen]

        if new_normal:
            print(f"  {len(new_normal)} YENİ normal fırsat:")
            for dep, ret, f in new_normal[:MAX_NOTIFY]:
                airline = f.get("Airline", {}).get("AirlineName", "?")
                print(f"    {dep}→{ret} {airline} {f['AdultNetFare']:,.0f} TL")
                send_telegram(format_normal(route, dep, ret, f))

            if len(new_normal) > MAX_NOTIFY:
                send_telegram(
                    f"ℹ️ <b>{name}</b>: {len(new_normal)} yeni fırsat, "
                    f"ilk {MAX_NOTIFY} gösterildi."
                )

            total_new += len(new_normal)
            for dep, ret, f in new_normal:
                route_seen.add(deal_id(dep, ret, f))
            state[name] = sorted(route_seen)
        elif not suspicious:
            print("  yeni fırsat yok.")

    save_state(state)
    print(f"\n=== Toplam: {total_new} normal, {total_suspicious} şüpheli ===")


if __name__ == "__main__":
    main()
