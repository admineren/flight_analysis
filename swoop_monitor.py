import os
import json
from datetime import datetime, timedelta, timezone

from swoop import search as swoop_search, deals, watch_deals

SEARCH_STATE_FILE = "swoop_search_state.json"
DEALS_STATE_FILE = "swoop_deals_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

USD_TO_TL = 50.0

# --- Sabit tarihli arama (search) rotaları ---
GOOGLE_FLIGHTS_WATCH = [
    {"name": "IST → Bangkok", "origin": "IST", "destination": "BKK",
     "departure_offset_days": 90, "stay_days": 7, "max_price_tl": 29000},
    {"name": "IST → Kuala Lumpur", "origin": "IST", "destination": "KUL",
     "departure_offset_days": 60, "stay_days": 14, "max_price_tl": 28000},
    {"name": "IST → Singapore", "origin": "IST", "destination": "SIN",
     "departure_offset_days": 60, "stay_days": 10, "max_price_tl": 33000},
    {"name": "IST → Seoul", "origin": "IST", "destination": "ICN",
     "departure_offset_days": 120, "stay_days": 10, "max_price_tl": 35000},
    {"name": "IST → Hong Kong", "origin": "IST", "destination": "HKG",
     "departure_offset_days": 60, "stay_days": 10, "max_price_tl": 32000},
    {"name": "IST → Manila", "origin": "IST", "destination": "MNL",
     "departure_offset_days": 60, "stay_days": 14, "max_price_tl": 39000},
]

# --- Deals filtre kuralları (lokal) ---
DEALS_MIN_DISCOUNT_PCT = 40          # %40+ → her bölgeden bildir
DEALS_ASIA_MIN_DISCOUNT_PCT = 25     # Asya %25+ → bildir
DEALS_MAX_PRICE_USD = 800            # $800 üstü deal'leri ele

MAX_NOTIFY = 5
REQUEST_DELAY = 2  # swoop çağrıları arasında saniye


# ============================================================
# STATE
# ============================================================
def _load_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(text):
    import requests
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
# SEARCH KATMANI (6 rota, sabit tarih)
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

    if "stay_days" in route:
        ret = depart + timedelta(days=route["stay_days"])
    else:
        ret = datetime.strptime(route["return_date"], "%Y-%m-%d").date()
        if ret < depart + timedelta(days=1):
            ret = depart + timedelta(days=7)

    return depart, ret


def _search_leg(origin, dest, date_str):
    try:
        out = swoop_search(origin, dest, date_str)
        if not out.results:
            return None
        prices = [opt.price for opt in out.results if opt.price]
        return min(prices) if prices else None
    except Exception as e:
        err = str(e)
        if "gRPC status 13" in err or "INTERNAL" in err:
            print(f"    geçici hata, 3sn sonra tekrar...")
            import time
            time.sleep(3)
            try:
                out = swoop_search(origin, dest, date_str)
                if not out.results:
                    return None
                prices = [opt.price for opt in out.results if opt.price]
                return min(prices) if prices else None
            except Exception as e2:
                print(f"    tekrar hata: {type(e2).__name__}: {str(e2)[:80]}")
                return None
        print(f"    hata: {type(e).__name__}: {err[:80]}")
        return None


def check_google_flights_watch():
    import time
    state = _load_state(SEARCH_STATE_FILE)
    first_run = not os.path.exists(SEARCH_STATE_FILE)
    today = datetime.now(timezone.utc).date()

    print("\n--- Google Flights Search ---")
    alerts = 0
    failed = 0

    for idx, route in enumerate(GOOGLE_FLIGHTS_WATCH):
        name = route["name"]
        depart, ret_date = resolve_dates(route)
        state_key = f"{name}|{depart}|{ret_date}"

        if idx > 0:
            time.sleep(REQUEST_DELAY)

        out_min = _search_leg(route["origin"], route["destination"], str(depart))
        time.sleep(0.5)
        ret_min = _search_leg(route["destination"], route["origin"], str(ret_date))

        if out_min is None or ret_min is None:
            failed += 1
            print(f"  [{name}] {depart}→{ret_date}: sonuç yok/başarısız")
            continue

        total_usd = out_min + ret_min
        total_tl = total_usd * USD_TO_TL

        prev = state.get(state_key, {})
        prev_tl = prev.get("last_tl")
        was_below = prev.get("below_threshold", False)
        below = total_tl <= route["max_price_tl"]

        trend = ""
        if prev_tl and prev_tl > total_tl:
            pct = (prev_tl - total_tl) / prev_tl * 100
            if pct >= 3:
                trend = f" (↓ %{pct:.0f})"

        print(f"  [{name}] {depart}→{ret_date} | "
              f"${total_usd} = {total_tl:,.0f} TL | "
              f"eşik {route['max_price_tl']:,} | altında: {below}{trend}")

        if first_run:
            pass
        elif below and not was_below:
            send_telegram(
                f"✈️ <b>[Google Flights] {name}</b>\n"
                f"📅 {depart} → {ret_date}\n"
                f"💰 ~<b>{total_tl:,.0f} TL</b>{trend}\n"
                f"⚠️ <i>USD bazlı tahmin, doğrula</i>"
            )
            alerts += 1
        elif below and was_below and trend:
            send_telegram(
                f"📉 <b>[Google Flights] {name}</b> daha da düştü\n"
                f"📅 {depart} → {ret_date}\n"
                f"💰 ~<b>{total_tl:,.0f} TL</b>{trend}"
            )
            alerts += 1

        state[state_key] = {"last_tl": total_tl, "below_threshold": below}

    # Eski kayıtları temizle
    today_str = str(today)
    for k in list(state.keys()):
        parts = k.split("|")
        if len(parts) == 3 and parts[1] < today_str:
            del state[k]

    _save_state(SEARCH_STATE_FILE, state)
    print(f"  Search: {alerts} alert, {failed} başarısız rota")
    return alerts


# ============================================================
# DEALS KATMANI (tek çağrı + lokal filtre)
# ============================================================
def check_swoop_deals():
    print("\n--- Swoop Deals ---")

    try:
        result = deals("IST")
        if not result.deals:
            print("  deal yok")
            return 0

        print(f"  {len(result.deals)} deal alındı")

        diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=True)
        print(f"  new: {len(diff.new)} | gone: {len(diff.gone)} | "
              f"price_changes: {len(diff.price_changes)}")

        alerts = 0
        for d in diff.new:
            if not d.destination_region:
                continue
            region = str(d.destination_region).replace("Region.", "")
            discount = d.discount_pct or 0
            is_asia = "ASIA" in region
            is_high_discount = discount >= DEALS_MIN_DISCOUNT_PCT
            is_asia_deal = is_asia and discount >= DEALS_ASIA_MIN_DISCOUNT_PCT

            if d.price > DEALS_MAX_PRICE_USD:
                continue
            if not (is_high_discount or is_asia_deal):
                continue

            if alerts >= MAX_NOTIFY:
                break

            airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
            msg = (
                f"🎯 <b>[Swoop Deals] IST → {d.destination_city}</b> ({region})\n"
                f"📅 {d.departure_date} → {d.return_date}\n"
                f"💰 <b>${d.price}</b> (normal ${d.typical_price}, <b>%{discount}</b>)\n"
                f"🛫 {airlines}"
            )
            if d.stops is not None:
                msg += f" | {d.stops} aktarma"
            if d.booking_url:
                msg += f"\n🔗 {d.booking_url[:100]}"

            send_telegram(msg)
            print(f"    🎯 {d.destination_city} ${d.price} (%{discount})")
            alerts += 1

        print(f"  Deals: {alerts} bildirim")
        return alerts

    except Exception as e:
        print(f"  hata: {type(e).__name__}: {str(e)[:100]}")
        return 0


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print(f"Swoop Monitor — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    search_alerts = check_google_flights_watch()
    deals_alerts = check_swoop_deals()

    print("\n" + "=" * 60)
    print(f"Toplam: {search_alerts} search + {deals_alerts} deals")
    print("=" * 60)


if __name__ == "__main__":
    main()
