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

# Global kur — main() içinde doldurulur (TCMB'den veya fallback)
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
    """TCMB'den USD/TRY çeker. Başarısızsa fallback API'ye, o da olmazsa 50.0 döner."""
    import requests

    # 1. TCMB (resmi)
    try:
        r = requests.get(
            "https://www.tcmb.gov.tr/kurlar/today.xml",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            match = re.search(
                r'<Currency[^>]*CurrencyCode="USD"[^>]*>.*?'
                r'<ForexSelling>([\d.]+)</ForexSelling>',
                r.text, re.DOTALL
            )
            if match:
                rate = float(match.group(1))
                print(f"  TCMB USD/TRY: {rate}")
                return rate
    except Exception as e:
        print(f"  TCMB hata: {type(e).__name__}")

    # 2. Fallback: exchangerate-api
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if r.status_code == 200:
            data = r.json()
            rate = data.get("rates", {}).get("TRY")
            if rate:
                print(f"  Fallback USD/TRY: {rate}")
                return float(rate)
    except Exception as e:
        print(f"  Fallback hata: {type(e).__name__}")

    print(f"  Kur çekilemedi, varsayılan: 50.0")
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
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
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
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)


# ============================================================
# YARDIMCI: Değeri TL'ye çevir
# ============================================================
def _to_tl(price, currency):
    """Fiyatı TL'ye çevir. TRY ise dokunma, değilse kur ile çarp."""
    if not currency or currency == "TRY":
        return int(price)
    return int(price * USD_TO_TL)


def _price_display(price, currency):
    """Bildirim için fiyat metni."""
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
        err = str(e)
        if "gRPC status 13" in err or "INTERNAL" in err:
            print(f"    geçici hata, 5sn sonra tekrar...")
            time.sleep(5)
            try:
                out = swoop_search(origin, dest, date_str)
                if not out.results:
                    return None
                prices = [opt.price for opt in out.results if opt.price]
                return min(prices) if prices else None
            except Exception as e2:
                print(f"    tekrar hata: {type(e2).__name__}")
                return None
        print(f"    hata: {type(e).__name__}")
        return None


def check_search():
    state = _load_state(SEARCH_STATE_FILE)
    first_run = not os.path.exists(SEARCH_STATE_FILE)
    today = datetime.now(timezone.utc).date()

    print("\n--- Swoop Search (2 vizesiz rota) ---")
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

        print(f"  [{name}] {depart}→{ret_date} | "
              f"{total_tl:,.0f} TL | eşik {route['max_price_tl']:,} | "
              f"altında: {below}{trend}")

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
    removed = 0
    for k in list(state.keys()):
        parts = k.split("|")
        if len(parts) == 3 and parts[1] < today_str:
            del state[k]
            removed += 1
    if removed:
        print(f"  🗑️ {removed} eski state temizlendi")

    _save_state(SEARCH_STATE_FILE, state)
    print(f"  Search: {alerts} alert")
    return alerts


# ============================================================
# DEALS KATMANI (fallback currency-aware)
# ============================================================
def _deal_passes_filters(d):
    if not d.destination_region:
        return False, "bölge yok"
    if not is_visa_free(d.destination_country):
        return False, f"vize gerekli ({d.destination_country})"

    region = str(d.destination_region).replace("Region.", "")
    discount = d.discount_pct or 0
    is_asia = "ASIA" in region
    is_high_discount = discount >= DEALS_MIN_DISCOUNT_PCT
    is_asia_deal = is_asia and discount >= DEALS_ASIA_MIN_DISCOUNT_PCT

    # Currency-aware fiyat kontrolü (USD veya TRY olabilir)
    currency = getattr(d, "currency", "TRY") or "TRY"
    price_tl = _to_tl(d.price, currency)
    if price_tl > DEALS_MAX_PRICE_TL:
        return False, f"fiyat yüksek (~{price_tl:,} TL)"

    if not (is_high_discount or is_asia_deal):
        return False, f"indirim düşük (%{discount})"

    return True, region


def _format_deal_msg(d, region, prefix_emoji="🎯", extra_info=""):
    airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
    currency = getattr(d, "currency", "TRY") or "TRY"
    price_str = _price_display(d.price, currency)

    typical_str = ""
    if d.typical_price:
        typical_str = f", normal {_price_display(d.typical_price, currency)}"

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
    if d.booking_url:
        msg += f"\n🔗 {d.booking_url[:100]}"
    return msg


def check_deals():
    print("\n--- Swoop Deals (vize filtresi, TL dönüşüm) ---")

    try:
        # set_country("TR") global ayar + explicit TransportConfig
        result = deals("IST", transport=TransportConfig(country="TR"))

        if not result.deals:
            print("  deal yok")
            return 0

        print(f"  {len(result.deals)} deal alındı")

        # İlk deal'in para birimi — set_country çalışıyor mu kontrolü
        first_currency = getattr(result.deals[0], "currency", "?")
        first_price = result.deals[0].price
        first_tl = _to_tl(first_price, first_currency)
        print(f"  Örnek: {result.deals[0].destination_city} — "
              f"{first_price} {first_currency} (~{first_tl:,} TL)")

        diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=True)
        print(f"  new: {len(diff.new)} | gone: {len(diff.gone)} | "
              f"price_changes: {len(diff.price_changes)}")

        alerts = 0
        skipped_visa = 0
        skipped_price = 0
        skipped_discount = 0

        # --- YENİ DEAL'LER ---
        for d in diff.new:
            ok, info = _deal_passes_filters(d)
            if not ok:
                if "vize" in info:
                    skipped_visa += 1
                elif "fiyat" in info:
                    skipped_price += 1
                elif "indirim" in info:
                    skipped_discount += 1
                continue

            if alerts >= MAX_NOTIFY:
                break

            msg = _format_deal_msg(d, info)
            send_telegram(msg)
            currency = getattr(d, "currency", "TRY") or "TRY"
            print(f"    🎯 {d.destination_city} ({d.destination_country}) "
                  f"{_price_display(d.price, currency)} (%{d.discount_pct})")
            alerts += 1

        # --- FİYAT DEĞİŞİMLERİ ---
        for pc in diff.price_changes:
            d = getattr(pc, "deal", None) or getattr(pc, "current", None)
            if not d:
                continue

            old_price = getattr(pc, "old_price", None) or getattr(pc, "prior_price", None)
            new_price = getattr(pc, "new_price", None) or d.price

            ok, info = _deal_passes_filters(d)
            if not ok:
                if "vize" in info:
                    skipped_visa += 1
                continue

            if alerts >= MAX_NOTIFY:
                break

            extra = ""
            currency = getattr(d, "currency", "TRY") or "TRY"
            if old_price and new_price and old_price > new_price:
                pct = (old_price - new_price) / old_price * 100
                old_str = _price_display(old_price, currency)
                new_str = _price_display(new_price, currency)
                extra = f"📉 Önceki: {old_str} → {new_str} (%{pct:.0f} düşüş)"

            msg = _format_deal_msg(d, info, prefix_emoji="📉", extra_info=extra)
            send_telegram(msg)
            print(f"    📉 {d.destination_city} ({d.destination_country}) "
                  f"{_price_display(d.price, currency)} (fiyat değişimi)")
            alerts += 1

        print(f"  Deals: {alerts} bildirim")
        print(f"    atlanan → vize: {skipped_visa}, fiyat: {skipped_price}, indirim: {skipped_discount}")
        return alerts

    except Exception as e:
        print(f"  hata: {type(e).__name__}: {str(e)[:150]}")
        return 0


# ============================================================
# MAIN
# ============================================================
def main():
    global USD_TO_TL

    print("=" * 60)
    print(f"Swoop Monitor — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # Kur çek (fallback mekanizması ile)
    print("\n--- Kur ---")
    USD_TO_TL = get_usd_tl()

    # Türkiye lokasyonu
    set_country("TR")
    print("Ülke: TR (arama fiyatları TL, deals fallback ile TL'ye çevrilir)")

    search_alerts = check_search()
    time.sleep(2)
    deals_alerts = check_deals()

    print("\n" + "=" * 60)
    print(f"Toplam: {search_alerts} search + {deals_alerts} deals")
    print(f"Kullanılan kur: 1 USD = {USD_TO_TL} TL")
    print("=" * 60)


if __name__ == "__main__":
    main()
