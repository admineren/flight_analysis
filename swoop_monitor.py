import os
import json
import re
import time
from datetime import datetime, timedelta, timezone

from swoop import (
    search as swoop_search,
    deals, watch_deals, set_country,
    TransportConfig,
)

SEARCH_STATE_FILE = "swoop_search_state.json"
DEALS_STATE_FILE = "swoop_deals_state.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

USD_TO_TL = 50.0

# --- Sadece vizesiz rotalar ---
GOOGLE_FLIGHTS_WATCH = [
    {"name": "IST → Tbilisi", "origin": "IST", "destination": "TBS",
     "departure_offset_days": 60, "stay_days": 5, "max_price_tl": 11000},
    {"name": "IST → Baku", "origin": "IST", "destination": "GYD",
     "departure_offset_days": 60, "stay_days": 5, "max_price_tl": 17000},
]

# --- Deals filtre kuralları ---
DEALS_MIN_DISCOUNT_PCT = 40
DEALS_ASIA_MIN_DISCOUNT_PCT = 25
DEALS_MAX_PRICE_TL = 40000

MAX_NOTIFY = 5
REQUEST_DELAY = 3


# ============================================================
# KUR ÇEKME (TCMB + fallback)
# ============================================================
def get_usd_tl():
    import requests
    try:
        r = requests.get("https://www.tcmb.gov.tr/kurlar/today.xml", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            match = re.search(
                r'<Currency[^>]*CurrencyCode="USD"[^>]*>.*?'
                r'<ForexSelling>([\d.]+)</ForexSelling>',
                r.text, re.DOTALL
            )
            if match:
                return float(match.group(1))
    except Exception:
        pass

    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if r.status_code == 200:
            return float(r.json().get("rates", {}).get("TRY", 50.0))
    except Exception:
        pass

    return 50.0


# ============================================================
# VİZE FİLTRESİ
# ============================================================
VISA_FREE_COUNTRIES = {
    "Georgia", "Azerbaijan", "Serbia", "Bosnia and Herzegovina",
    "Albania", "North Macedonia", "Montenegro", "Kosovo",
    "Moldova", "Belarus", "Ukraine", "Russia",
    "Kazakhstan", "Kyrgyzstan", "Uzbekistan", "Tajikistan",
    "Qatar", "Oman", "Bahrain", "Jordan", "Lebanon", "Iran",
    "Thailand", "Malaysia", "Singapore", "Indonesia",
    "Philippines", "Maldives", "Sri Lanka", "Vietnam",
    "Cambodia", "Laos", "Nepal",
    "Morocco", "Tunisia", "Kenya", "Tanzania", "Ethiopia",
    "South Africa",
    "Türkiye", "Turkey", "Cyprus",
}

VISA_REQUIRED_COUNTRIES = {
    "Germany", "France", "Netherlands", "Greece", "Italy", "Spain",
    "Portugal", "Finland", "Norway", "Sweden", "Denmark", "Austria",
    "Belgium", "Switzerland", "Poland", "Czechia", "Czech Republic",
    "Hungary", "Croatia", "Slovenia", "Slovakia", "Estonia", "Latvia",
    "Lithuania", "Luxembourg", "Malta", "Iceland", "Liechtenstein",
    "United Kingdom", "United States", "Canada", "Australia",
    "New Zealand", "Japan", "South Korea", "Taiwan", "Israel",
    "United Arab Emirates", "Egypt",
}


def is_visa_free(country_name):
    if not country_name:
        return False
    if country_name in VISA_REQUIRED_COUNTRIES:
        return False
    return country_name in VISA_FREE_COUNTRIES


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
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def send_telegram(text):
    import requests
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=15)
    except Exception as e:
        print("Telegram exception:", e)


# ============================================================
# YARDIMCI: Değeri TL'ye çevir
# ============================================================
def _to_tl(price, currency):
    if not currency or currency == "TRY":
        return int(price)
    return int(price * USD_TO_TL)


def _price_display(price, currency):
    if not currency or currency == "TRY":
        return f"₺{price:,}"
    tl_value = int(price * USD_TO_TL)
    return f"{price} {currency} (~₺{tl_value:,})"


# ============================================================
# SEARCH KATMANI
# ============================================================
def resolve_dates(route):
    today = datetime.now(timezone.utc).date()
    depart = today + timedelta(days=route["departure_offset_days"])
    ret = depart + timedelta(days=route["stay_days"])
    return depart, ret


def _search_leg(origin, dest, date_str):
    try:
        out = swoop_search(origin, dest, date_str)
        if not out.results:
            return None
        prices = [opt.price for opt in out.results if opt.price]
        return min(prices) if prices else None
    except Exception as e:
        if "gRPC status 13" in str(e) or "INTERNAL" in str(e):
            time.sleep(5)
            try:
                out = swoop_search(origin, dest, date_str)
                if not out.results:
                    return None
                prices = [opt.price for opt in out.results if opt.price]
                return min(prices) if prices else None
            except Exception:
                return None
        return None


def check_search():
    state = _load_state(SEARCH_STATE_FILE)
    first_run = not os.path.exists(SEARCH_STATE_FILE)
    today = datetime.now(timezone.utc).date()

    print("\n--- Swoop Search ---")
    alerts = 0

    for idx, route in enumerate(GOOGLE_FLIGHTS_WATCH):
        name = route["name"]
        depart, ret_date = resolve_dates(route)
        state_key = f"{name}|{depart}|{ret_date}"

        if idx > 0:
            time.sleep(REQUEST_DELAY)

        out_min = _search_leg(route["origin"], route["destination"], str(depart))
        time.sleep(1)
        ret_min = _search_leg(route["destination"], route["origin"], str(ret_date))

        if out_min is None or ret_min is None:
            print(f"  [{name}] {depart}→{ret_date}: başarısız")
            continue

        total_tl = out_min + ret_min

        prev = state.get(state_key, {})
        prev_tl = prev.get("last_tl")
        was_below = prev.get("below_threshold", False)
        below = total_tl <= route["max_price_tl"]

        trend = ""
        if prev_tl and prev_tl > total_tl:
            pct = (prev_tl - total_tl) / prev_tl * 100
            if pct >= 3:
                trend = f" (↓ %{pct:.0f})"

        print(f"  [{name}] {depart}→{ret_date} | {total_tl:,.0f} TL | "
              f"eşik {route['max_price_tl']:,} | altında: {below}{trend}")

        if first_run:
            pass
        elif below and not was_below:
            send_telegram(
                f"✈️ <b>[Swoop Search] {name}</b>\n"
                f"📅 {depart} → {ret_date}\n"
                f"💰 <b>{total_tl:,.0f} TL</b>{trend}\n"
                f"⚠️ <i>Google TR fiyatı, doğrula</i>"
            )
            alerts += 1
        elif below and was_below and trend:
            send_telegram(
                f"📉 <b>[Swoop Search] {name}</b> daha da düştü\n"
                f"📅 {depart} → {ret_date}\n"
                f"💰 <b>{total_tl:,.0f} TL</b>{trend}"
            )
            alerts += 1

        state[state_key] = {"last_tl": total_tl, "below_threshold": below}

    today_str = str(today)
    for k in list(state.keys()):
        parts = k.split("|")
        if len(parts) == 3 and parts[1] < today_str:
            del state[k]

    _save_state(SEARCH_STATE_FILE, state)
    print(f"  Search: {alerts} alert")
    return alerts


# ============================================================
# DEALS KATMANI
# ============================================================
def _deal_passes_filters(d):
    if not d.destination_region:
        return False, "bölge yok"
    if not is_visa_free(d.destination_country):
        return False, "vize gerekli"

    region = str(d.destination_region).replace("Region.", "")
    discount = d.discount_pct or 0
    is_asia = "ASIA" in region

    currency = getattr(d, "currency", "TRY") or "TRY"
    price_tl = _to_tl(d.price, currency)
    if price_tl > DEALS_MAX_PRICE_TL:
        return False, "fiyat yüksek"

    if not (discount >= DEALS_MIN_DISCOUNT_PCT or (is_asia and discount >= DEALS_ASIA_MIN_DISCOUNT_PCT)):
        return False, "indirim düşük"

    return True, region


def _format_deal_msg(d, region, prefix_emoji="🎯", extra_info=""):
    airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
    currency = getattr(d, "currency", "TRY") or "TRY"
    
    price_str = _price_display(d.price, currency)
    typical_str = f", normal {_price_display(d.typical_price, currency)}" if d.typical_price else ""

    # TEMİZLİK: URL kısmı kaldırıldı, mesaj daha kısa ve net.
    msg = (
        f"{prefix_emoji} <b>[Swoop Deals] IST → {d.destination_city}</b> ({region})\n"
        f"📅 {d.departure_date} → {d.return_date}\n"
        f"💰 <b>{price_str}</b>{typical_str} (<b>%{d.discount_pct or 0}</b>)\n"
        f"🛫 {airlines}"
    )
    if d.stops is not None:
        msg += f" | {d.stops} aktarma"
    if extra_info:
        msg += f"\n{extra_info}"
    
    return msg


def check_deals():
    print("\n--- Swoop Deals ---")
    try:
        result = deals("IST", transport=TransportConfig(country="TR"))
        if not result.deals:
            return 0

        diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=True)
        print(f"  new: {len(diff.new)} | price_changes: {len(diff.price_changes)}")

        alerts = 0
        for d in diff.new:
            ok, info = _deal_passes_filters(d)
            if ok and alerts < MAX_NOTIFY:
                send_telegram(_format_deal_msg(d, info))
                alerts += 1

        for pc in diff.price_changes:
            d = getattr(pc, "deal", None) or getattr(pc, "current", None)
            if not d:
                continue
            ok, info = _deal_passes_filters(d)
            if ok and alerts < MAX_NOTIFY:
                old_p = getattr(pc, "old_price", None)
                extra = ""
                if old_p and old_p > d.price:
                    pct = (old_p - d.price) / old_p * 100
                    extra = f"📉 Önceki: {_price_display(old_p, d.currency)} (%{pct:.0f} düşüş)"
                
                send_telegram(_format_deal_msg(d, info, prefix_emoji="📉", extra_info=extra))
                alerts += 1

        print(f"  Deals: {alerts} bildirim")
        return alerts
    except Exception as e:
        print(f"  hata: {str(e)[:100]}")
        return 0


# ============================================================
# MAIN
# ============================================================
def main():
    global USD_TO_TL
    print(f"=== Swoop Monitor — {datetime.now(timezone.utc).isoformat()} ===")
    
    USD_TO_TL = get_usd_tl()
    set_country("TR")
    
    search_alerts = check_search()
    time.sleep(2)
    deals_alerts = check_deals()

    print(f"=== Toplam: {search_alerts} search + {deals_alerts} deals ===")

if __name__ == "__main__":
    main()
