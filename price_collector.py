import os
import sys
import json
import requests
import time
from datetime import datetime, timezone, date

from viajante import get_flights, RoundTrip
from swoop import search as swoop_search, TransportConfig
from visa_helper import get_visa_details, get_iso_by_iata

print("🚀 Price Collector başlıyor...", flush=True)

TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_INGEST_TOKEN = os.environ.get("TB_INGEST_TOKEN")
TB_DATASOURCE = "price_history"

STATE_FILE = os.path.join("data", "price_collector_state.json")

WATCHLIST = [
    {"origin": "IST", "dest": "BKK", "depart": "2027-02-15", "ret": "2027-02-22"},
    {"origin": "IST", "dest": "DPS", "depart": "2027-03-10", "ret": "2027-03-17"},
    {"origin": "IST", "dest": "KUL", "depart": "2027-03-01", "ret": "2027-03-08"},
    {"origin": "IST", "dest": "SIN", "depart": "2027-03-15", "ret": "2027-03-22"},
    {"origin": "IST", "dest": "HKG", "depart": "2027-04-10", "ret": "2027-04-17"},
    {"origin": "IST", "dest": "HAN", "depart": "2027-04-20", "ret": "2027-04-27"},
    {"origin": "IST", "dest": "MNL", "depart": "2027-05-05", "ret": "2027-05-12"},
    {"origin": "IST", "dest": "TBS", "depart": "2027-05-20", "ret": "2027-05-27"},
]

VIAJANTE_RETRY_DELAYS = [30, 90]
ROUTE_DELAY = 5

_blocked_this_run = False


def get_routes_for_current_slot():
    now = datetime.now(timezone.utc)
    RUNS_PER_DAY = 6                          # 4 saatlik cron
    run_index = (now.hour // 4) % RUNS_PER_DAY

    total = len(WATCHLIST)
    if total == 0:
        return []

    # Modüler dağıtım: i % 6 == run_index olanları seç
    routes = [WATCHLIST[i] for i in range(total) if i % RUNS_PER_DAY == run_index]

    print(
        f"🕐 Saat {now.hour:02d}:00 UTC → Grup {run_index + 1}/{RUNS_PER_DAY} "
        f"({len(routes)}/{total} rota)", flush=True
    )
    return routes


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
        os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"❌ State kaydedilemedi: {e}", flush=True)


def send_to_tinybird(payloads):
    if not payloads:
        print("📭 Tinybird'e gönderilecek yeni veri yok.", flush=True)
        return True
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
            print(f"✅ {len(payloads)} fiyat Tinybird'e gönderildi.", flush=True)
            return True
        print(f"❌ Tinybird Hatası: {r.status_code} - {r.text[:200]}", flush=True)
        return False
    except Exception as e:
        print(f"❌ Tinybird bağlantı hatası: {e}", flush=True)
        return False


# ============================================================
# TEK ROTA TARAMA
# ============================================================
def scan_route(route, now_str):
    global _blocked_this_run
    route_id = f"{route['origin']}-{route['dest']}-{route['depart']}"
    print(f"\n[{route_id}] taranıyor...", flush=True)

    dest_iso = get_iso_by_iata(route["dest"])
    visa = get_visa_details(dest_iso) if dest_iso else None
    visa_color = visa.get("color") if visa else ""
    visa_name = visa.get("name") if visa else ""
    visa_duration = visa.get("duration") if visa else ""

    print(
        f"  🔍 Vize: IATA={route['dest']} → ISO={dest_iso or 'YOK'} → "
        f"color={visa_color or 'YOK'}, name={visa_name or 'YOK'}",
        flush=True,
    )

def _enrich(result, source):
    if not result:
        return None
    result["source"] = source
    result["passport"] = "TR"
    if visa_color:
        result["visa_color"] = visa_color
    if visa_name:
        result["visa_name"] = visa_name
    if visa_duration:
        result["visa_duration"] = visa_duration
    return result

    if not _blocked_this_run:
        result, was_blocked = _try_viajante(route, route_id, now_str)
        if result:
            return _enrich(result, "viajante")
        if was_blocked:
            _blocked_this_run = True
            print(f"  🚫 Bu run'da BLOCKED tespit edildi, sonraki rotalar Swoop'a geçecek", flush=True)
    else:
        print(f"  ⏭️  Viajante atlanıyor (bu run'da BLOCKED)", flush=True)

    print(f"  🔄 Swoop fallback deneniyor...", flush=True)
    result = _try_swoop(route, route_id, now_str)
    if result:
        return _enrich(result, "swoop")

    print(f"  ❌ {route_id} her iki kaynakta da başarısız.", flush=True)
    return None


def _try_viajante(route, route_id, now_str):
    trip = RoundTrip(
        origin=route["origin"],
        destination=route["dest"],
        departure_date=date.fromisoformat(route["depart"]),
        return_date=date.fromisoformat(route["ret"]),
        max_stops=1,
    )
    for attempt, delay in enumerate([0] + VIAJANTE_RETRY_DELAYS):
        if delay:
            print(f"  ⏳ {delay}s bekleniyor...", flush=True)
            time.sleep(delay)
        try:
            print(f"  → Viajante (Deneme {attempt+1}/{1 + len(VIAJANTE_RETRY_DELAYS)})", flush=True)
            report = get_flights(trip, fetch="sweep", top=1, currency="TRY", deadline_seconds=60)
            if not report.queries:
                return None, False
            q = report.queries[0]
            if q.status != "ok" or not q.offers:
                err = getattr(q.error, "code", "unknown") if q.error else "no_query"
                print(f"    ⚠️ {err}", flush=True)
                if "BLOCKED" in str(err):
                    continue
                return None, False

            best = q.offers[0]
            airline = ", ".join(dict.fromkeys(best.airline.split(", "))) if best.airline else "?"
            price_level = q.price_insight.level if q.price_insight and q.price_insight.level else "unknown"
            typical_price = None
            if q.price_insight and q.price_insight.typical_range:
                typical_price = sum(q.price_insight.typical_range) / 2

            # Layover: önce üst seviye, yoksa legs'ten çıkar
            layover_city = getattr(best, "layover_city", None) or ""
            layover_hours = getattr(best, "layover_hours", None)

            if not layover_city and best.legs:
                leg = best.legs[0]
                if leg.layovers:
                    first_layover = leg.layovers[0]
                    layover_city = first_layover.city or ""
                    layover_hours = first_layover.hours

            layover_dbg = (
                f" | {layover_city} {layover_hours:.1f}h"
                if layover_city and layover_hours else ""
            )
            print(
                f"    📊 {best.price:,.0f} TRY | {airline} | {best.duration_hours:.1f}h | "
                f"{best.stops_count} akt | level: {price_level}{layover_dbg}",
                flush=True,
            )

            return {
                "origin": route["origin"],
                "destination": route["dest"],
                "departure_date": route["depart"],
                "return_date": route["ret"],
                "airline": airline or "?",
                "price": round(float(best.price), 2),
                "currency": "TRY",
                "price_level": price_level,
                "typical_price": round(typical_price, 2) if typical_price else None,
                "vs_typical_pct": best.vs_typical_pct,
                "duration_hours": round(best.duration_hours, 2) if best.duration_hours else 0.0,
                "stops": best.stops_count if best.stops_count is not None else 0,
                "layover_city": layover_city,
                "layover_hours": round(layover_hours, 2) if layover_hours else None,
                "booking_url": best.google_flights_url or "",
                "observed_at": now_str,
            }, False
        except Exception as e:
            print(f"    ❌ Hata: {str(e)[:100]}", flush=True)
            continue

    return None, True


def _try_swoop(route, route_id, now_str):
    try:
        print(f"  → Swoop", flush=True)
        out = swoop_search(
            route["origin"], route["dest"], route["depart"],
            return_date=route["ret"],
            transport=TransportConfig(country="TR"),
        )
        if not out.results:
            print(f"    ⚠️ Sonuç yok", flush=True)
            return None
        valid = [(opt.price, opt) for opt in out.results if opt.price]
        if not valid:
            return None
        valid.sort(key=lambda x: x[0])
        price, best = valid[0]

        airline = "?"
        duration = 0.0
        stops = 0
        layover_city = ""
        layover_hours = None
        if best.legs:
            itin = best.legs[0].itinerary
            if itin:
                airline = ", ".join(itin.airline_names) if itin.airline_names else "?"
                duration = itin.travel_time / 60 if itin.travel_time else 0.0
                stops = itin.stop_count or 0
                # YENİ: Swoop'ta ilk layover'ı al
                if itin.layovers:
                    first_layover = itin.layovers[0]
                    layover_city = first_layover.arrival_airport_city or first_layover.arrival_airport_code or ""
                    layover_hours = first_layover.minutes / 60 if first_layover.minutes else None

        print(f"    📊 {price:,.0f} TRY | {airline} | {duration:.1f}h | {stops} akt (swoop)"
              f"{f' | {layover_city} {layover_hours:.1f}h' if layover_city and layover_hours else ''}", flush=True)

        return {
            "origin": route["origin"],
            "destination": route["dest"],
            "departure_date": route["depart"],
            "return_date": route["ret"],
            "airline": airline,
            "price": round(float(price), 2),
            "currency": "TRY",
            "price_level": "unknown",
            "typical_price": None,
            "vs_typical_pct": None,
            "duration_hours": round(duration, 2) if duration else 0.0,
            "stops": stops,
            "layover_city": layover_city,
            "layover_hours": round(layover_hours, 2) if layover_hours else None,
            "booking_url": "",
            "observed_at": now_str,
        }
    except Exception as e:
        print(f"    ❌ Swoop hatası: {str(e)[:100]}", flush=True)
        return None


def should_save(candidate, last_state):
    if not last_state:
        return True, "ilk kayıt"
    if last_state.get("last_date") != candidate["_today"]:
        return True, "yeni gün"
    if last_state.get("price") != candidate["price"]:
        old = last_state.get("price", 0)
        return True, f"fiyat değişti ({old:,.0f} → {candidate['price']:,.0f})"
    return False, "değişiklik yok"


def main():
    global _blocked_this_run
    _blocked_this_run = False

    print(f"=== Başladı: {datetime.now(timezone.utc).isoformat()} ===", flush=True)
    state = load_state()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payloads = []
    pending_state_updates = {}

    routes_today = get_routes_for_current_slot()

    for route in routes_today:
        candidate = scan_route(route, now_str)
        if not candidate:
            continue

        route_id = f"{route['origin']}-{route['dest']}-{route['depart']}"
        last_state = state.get(route_id, {})
        save, reason = should_save({**candidate, "_today": today_str}, last_state)

        if save:
            print(f"  ✅ Kaydedilecek: {reason}", flush=True)
            payloads.append(candidate)
            pending_state_updates[route_id] = {
                "price": candidate["price"],
                "last_date": today_str,
                "updated_at": now_str,
            }
        else:
            print(f"  ⏭️ Atlanıyor: {reason}", flush=True)

        time.sleep(ROUTE_DELAY)

    print(f"\n--- Tinybird gönderimi ---", flush=True)
    if send_to_tinybird(payloads):
        for rid, data in pending_state_updates.items():
            state[rid] = data
        save_state(state)
        print(f"💾 State güncellendi ({len(pending_state_updates)} rota)", flush=True)
    else:
        print(f"⚠️ Gönderim başarısız, state güncellenmedi", flush=True)

    print("=== Tamamlandı ===", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ KRİTİK HATA: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)
