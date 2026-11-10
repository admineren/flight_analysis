import os
import sys
import json
import requests
import time
from datetime import datetime, timezone, date
from viajante import get_flights, RoundTrip

print("🚀 Price Collector başlıyor...", flush=True)

TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_INGEST_TOKEN = os.environ.get("TB_INGEST_TOKEN")
TB_DATASOURCE = "price_history"

STATE_FILE = "price_collector_state.json"

# ============================================================
# WATCHLIST
# ============================================================
WATCHLIST = [
    {"origin": "IST", "dest": "BKK", "depart": "2027-02-15", "ret": "2027-02-22"},  # Bangkok
    {"origin": "IST", "dest": "DPS", "depart": "2027-03-10", "ret": "2027-03-17"},  # Bali
    {"origin": "IST", "dest": "KUL", "depart": "2027-03-01", "ret": "2027-03-08"},  # Kuala Lumpur
    {"origin": "IST", "dest": "SIN", "depart": "2027-03-15", "ret": "2027-03-22"},  # Singapur (yeni)
    {"origin": "IST", "dest": "HKG", "depart": "2027-04-10", "ret": "2027-04-17"},  # Hong Kong (yeni)
    {"origin": "IST", "dest": "HAN", "depart": "2027-04-20", "ret": "2027-04-27"},  # Hanoi (yeni)
    {"origin": "IST", "dest": "MNL", "depart": "2027-05-05", "ret": "2027-05-12"},  # Manila (yeni)
    {"origin": "IST", "dest": "TBS", "depart": "2027-05-20", "ret": "2027-05-27"},  # Tiflis (yeni)
]


def get_todays_routes():
    """Bugünün gün numarasına göre bir grubu seç (round-robin)."""
    from datetime import datetime
    day_of_year = datetime.now(timezone.utc).timetuple().tm_yday
    group = day_of_year % 2
    
    half = len(WATCHLIST) // 2
    if group == 0:
        routes = WATCHLIST[:half]
    else:
        routes = WATCHLIST[half:]
    
    print(f"📅 Gün {day_of_year} → Grup {group} ({len(routes)} rota)", flush=True)
    return routes

# ============================================================
# STATE
# ============================================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ State kaydedilemedi: {e}", flush=True)


# ============================================================
# TINYBIRD
# ============================================================
def send_to_tinybird(payloads):
    if not payloads:
        print("📭 Tinybird'e gönderilecek yeni veri yok.", flush=True)
        return True  # Boş gönderim "başarı" sayılır

    print(f"📤 Tinybird'e {len(payloads)} adet veri gönderiliyor...", flush=True)
    url = f"{TB_HOST}/v0/events?name={TB_DATASOURCE}"
    headers = {
        "Authorization": f"Bearer {TB_INGEST_TOKEN}",
        "Content-Type": "application/x-ndjson",
    }
    data = "\n".join(json.dumps(p) for p in payloads)

    try:
        r = requests.post(url, headers=headers, data=data, timeout=15)
        if r.status_code == 202:
            print(f"✅ {len(payloads)} fiyat Tinybird'e başarıyla gönderildi.", flush=True)
            return True
        print(f"❌ Tinybird Hatası: {r.status_code} - {r.text[:200]}", flush=True)
        return False
    except Exception as e:
        print(f"❌ Tinybird bağlantı hatası: {e}", flush=True)
        return False


# ============================================================
# TEK ROTA TARAMA
# ============================================================
def scan_route(route, today_str, now_str):
    """Bir rotayı tarar, kaydedilecekse payload döndürür."""
    route_id = f"{route['origin']}-{route['dest']}-{route['depart']}"
    print(f"\n[{route_id}] taranıyor...", flush=True)

    trip = RoundTrip(
        origin=route["origin"],
        destination=route["dest"],
        departure_date=date.fromisoformat(route["depart"]),
        return_date=date.fromisoformat(route["ret"]),
        max_stops=1,
    )

    for attempt in range(3):
        try:
            print(f"  → Google Flights isteği (Deneme {attempt + 1}/3)", flush=True)
            report = get_flights(
                trip, fetch="sweep", top=1, currency="TRY", deadline_seconds=60
            )

            if not report.queries:
                print(f"  ⚠️ Sorgu yok", flush=True)
                return None

            q = report.queries[0]
            if q.status != "ok" or not q.offers:
                err_code = getattr(q.error, "code", "unknown") if q.error else "no_query"
                print(f"  ⚠️ Sonuç yok (Deneme {attempt + 1}/3): {err_code}", flush=True)
                if err_code == "blocked":
                    time.sleep(20)
                    continue
                return None

            best = q.offers[0]
            price = best.price
            airline = best.airline
            duration = best.duration_hours or 0.0
            stops = best.stops_count if best.stops_count is not None else 0

            price_level = "unknown"
            if q.price_insight and q.price_insight.level:
                price_level = q.price_insight.level

            print(
                f"  📊 {price:,.0f} TRY | {airline} | "
                f"{duration:.1f}s | {stops} akt | level: {price_level}",
                flush=True,
            )

            return {
                "origin": route["origin"],
                "destination": route["dest"],
                "departure_date": route["depart"],
                "return_date": route["ret"],
                "airline": airline or "?",
                "price": price,
                "currency": "TRY",
                "price_level": price_level,
                "duration_hours": duration,
                "stops": stops,
                "source": "viajante",
                "observed_at": now_str,
                "_route_id": route_id,
                "_today": today_str,
            }

        except Exception as e:
            print(f"  ❌ Viajante hatası (Deneme {attempt + 1}/3): {str(e)[:120]}", flush=True)
            time.sleep(5)

    print(f"  ❌ {route_id} 3 denemede başarısız, atlandı.", flush=True)
    return None


# ============================================================
# KARAR: Kaydedilmeli mi?
# ============================================================
def should_save(candidate, last_state):
    """Yeni gün veya fiyat değişimi varsa kaydet."""
    if not last_state:
        return True, "ilk kayıt"

    if last_state.get("last_date") != candidate["_today"]:
        return True, "yeni gün"

    if last_state.get("price") != candidate["price"]:
        old = last_state.get("price", 0)
        return True, f"fiyat değişti ({old:,.0f} → {candidate['price']:,.0f})"

    return False, "değişiklik yok"


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"=== Başladı: {datetime.now(timezone.utc).isoformat()} ===", flush=True)

    state = load_state()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payloads = []
    pending_state_updates = {}  # Gönderim başarılıysa uygulanacak

    routes_today = get_todays_routes()

    for route in routes_today:
        candidate = scan_route(route, today_str, now_str)
        if not candidate:
            continue

        route_id = candidate.pop("_route_id")
        today = candidate.pop("_today")

        last_state = state.get(route_id, {})
        save, reason = should_save(
            {**candidate, "_today": today, "_route_id": route_id},
            last_state,
        )

        if save:
            print(f"  ✅ Kaydedilecek: {reason}", flush=True)
            payloads.append(candidate)
            # State güncellemesini gönderim başarılıysa uygula
            pending_state_updates[route_id] = {
                "price": candidate["price"],
                "last_date": today,
                "updated_at": now_str,
            }
        else:
            print(f"  ⏭️ Atlanıyor: {reason}", flush=True)

        time.sleep(5)  # Rotalar arası bekleme

    # Tinybird'e gönder
    print(f"\n--- Tinybird gönderimi ---", flush=True)
    if send_to_tinybird(payloads):
        # Başarılıysa state'i güncelle
        for rid, data in pending_state_updates.items():
            state[rid] = data
        save_state(state)
        print(f"💾 State güncellendi ({len(pending_state_updates)} rota)", flush=True)
    else:
        print(f"⚠️ Gönderim başarısız, state güncellenmedi (bir sonraki turda tekrar denenecek)", flush=True)

    print("=== Tamamlandı ===", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ KRİTİK HATA: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)
