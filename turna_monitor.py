import os
import json
import time
from datetime import datetime, timedelta, timezone
from curl_cffi import requests as curl_requests

WATCH_FILE = "turna_watch.json"
STATE_FILE = "turna_state.json"
API_URL = "https://www.turna.com/api/proxy/v1/analytics/cheapest/flights_to"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

COOLDOWN_HOURS = 24    # Aynı rotaya 24 saat boyunca tekrar bildirim yok
PRICE_DROP_PCT = 5     # 24 saat sonra fiyat %5 düşerse tekrar bildir

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Origin": "https://www.turna.com",
    "Referer": "https://www.turna.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content: return {}
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return {}

def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        curl_requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=15)
    except Exception as e:
        print("Telegram exception:", e)

def search_route(route):
    today = datetime.now(timezone.utc).date()
    start = today + timedelta(days=2)
    end = today + timedelta(days=120)
    
    body = {
        "Origins": [{"Code": route["origin"]}],
        "Destination": {"Code": route["destination"]},
        "MaxNumberOfResults": 200,
        "TripType": "RT",
        "StartDate": start.strftime("%Y-%m-%d"),
        "EndDate": end.strftime("%Y-%m-%d"),
        "FetchSegmentDetails": True,
        "Currency": "TRY",
        "Language": "TR",
        "CallerId": "saka",
        "RoundTripOptions": {"MinStay": 3, "MaxStay": 21},
    }
    
    try:
        resp = curl_requests.post(API_URL, headers=HEADERS, json=body, impersonate="chrome", timeout=90)
        if resp.status_code != 200: return None
        return resp.json()
    except Exception:
        return None

def find_best_deal(route, data):
    flights = data if isinstance(data, list) else (data.get("Flights") or data.get("Results") or data.get("Data") or [])
    if not flights: return None
    
    by_pair = {}
    for f in flights:
        dep = f.get("OutboundDepartureDate", "")[:10]
        ret = f.get("InboundDepartureDate", "")[:10]
        key = (dep, ret)
        if key not in by_pair or f["AdultNetFare"] < by_pair[key]["AdultNetFare"]:
            by_pair[key] = f
    
    max_price = route.get("max_price", float("inf"))
    max_stops = route.get("max_stops", 99)
    
    filtered = []
    for (dep, ret), f in by_pair.items():
        if f["AdultNetFare"] > max_price: continue
        if f.get("NumStops", 0) > max_stops: continue
        filtered.append((dep, ret, f))
    
    if not filtered: return None
    filtered.sort(key=lambda x: x[2]["AdultNetFare"])
    return filtered[0] # En ucuz olanı döndür

def format_notification(route, dep, ret, flight):
    airline = flight.get("Airline", {}).get("AirlineName", "?")
    price = flight["AdultNetFare"]
    stops = flight.get("NumStops", 0)
    dur_min = flight.get("DurationInMinutes", 0)
    dur_h, dur_m = divmod(int(dur_min), 60)
    seats = flight.get("AvailableSeats", "?")
    
    return (
        f"✈️ <b>[Turna] {route['name']}</b>\n"
        f"📅 {dep} → {ret}\n"
        f"💰 <b>{price:,.0f} TL</b> (eşik: {route['max_price']:,})\n"
        f"🛫 {airline} | {stops} aktarma | {dur_h}s {dur_m:02d}dk | 💺 {seats}\n"
        f"🔗 https://www.turna.com/ucak-bileti/gidis-donus/"
        f"{route.get('origin_slug', 'istanbul-ist-havalimani')}-"
        f"{route.get('destination_slug', route['destination'].lower())}/"
        f"{dep}/{ret}?adult=1"
    )

def main():
    with open(WATCH_FILE, "r", encoding="utf-8") as f:
        watch = json.load(f)
    
    state = load_state()
    first_run = not os.path.exists(STATE_FILE)
    now = datetime.now(timezone.utc)
    alerts = 0
    
    print(f"--- Turna Monitor ---")
    
    for route in watch["routes"]:
        name = route["name"]
        print(f"  [{name}] kontrol ediliyor...")
        
        data = search_route(route)
        if not data:
            print(f"    sonuç yok")
            continue
        
        best = find_best_deal(route, data)
        if not best:
            print(f"    eşik altında deal yok")
            state.setdefault(name, {})["last_checked"] = now.isoformat()
            continue
        
        dep, ret, flight = best
        best_price = flight["AdultNetFare"]
        
        print(f"    en iyi: {dep}→{ret} {best_price:,.0f} TL")
        
        prev = state.get(name, {})
        prev_notified_at = prev.get("last_notified_at")
        last_notified_price = prev.get("last_notified_price")
        
        if first_run:
            state[name] = {"last_checked": now.isoformat(), "last_price": best_price}
            print(f"    ilk kayıt (sessiz)")
            continue
        
        # Cooldown kontrolü
        cooldown_ok = True
        if prev_notified_at:
            last_dt = datetime.fromisoformat(prev_notified_at.replace("Z", "+00:00"))
            hours_since = (now - last_dt).total_seconds() / 3600
            cooldown_ok = hours_since >= COOLDOWN_HOURS
        
        should_notify = False
        reason = ""
        
        if last_notified_price is None:
            should_notify = cooldown_ok
            reason = "ilk fırsat"
        elif best_price < last_notified_price * (1 - PRICE_DROP_PCT / 100):
            should_notify = cooldown_ok
            reason = f"fiyat düştü ({last_notified_price:,.0f} → {best_price:,.0f})"
        
        if should_notify:
            send_telegram(format_notification(route, dep, ret, flight))
            print(f"    🎯 BİLDİRİM: {reason}")
            alerts += 1
            state[name] = {"last_checked": now.isoformat(), "last_price": best_price, "last_notified_price": best_price, "last_notified_at": now.isoformat()}
        else:
            if not cooldown_ok: print(f"    ⏸️ cooldown (24 saat dolmadı)")
            else: print(f"    sessiz (fiyat düşmedi)")
            state[name] = {"last_checked": now.isoformat(), "last_price": best_price, "last_notified_price": last_notified_price, "last_notified_at": prev_notified_at}
    
    save_state(state)
    print(f"--- Toplam: {alerts} bildirim ---")

if __name__ == "__main__":
    main()
