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
VISA_DATA_FILE = "visa_data.json"

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

USD_TO_TL = 50.0

GOOGLE_FLIGHTS_WATCH = [
    {"name": "IST → Tbilisi", "origin": "IST", "destination": "TBS",
     "departure_offset_days": 60, "stay_days": 5, "max_price_tl": 11000},
    {"name": "IST → Baku", "origin": "IST", "destination": "GYD",
     "departure_offset_days": 60, "stay_days": 5, "max_price_tl": 17000},
]

DEALS_MIN_DISCOUNT_PCT = 40
DEALS_ASIA_MIN_DISCOUNT_PCT = 25
DEALS_MAX_PRICE_TL = 40000
MAX_NOTIFY = 5
REQUEST_DELAY = 3

# ============================================================
# VİZE VERİSİ (Kapsamlı Sözlük)
# ============================================================
VISA_DATA = {}
VISA_MAP = {"green": set(), "blue": set(), "yellow": set(), "red": set()}

# Google Flights'ın döndürdüğü İngilizce ülke isimlerini ISO 3166-1 alpha-2 kodlarına çeviren sözlük
COUNTRY_NAME_TO_ISO = {
    "Afghanistan": "AF", "Albania": "AL", "Algeria": "DZ", "Andorra": "AD", "Angola": "AO",
    "Antigua and Barbuda": "AG", "Argentina": "AR", "Armenia": "AM", "Australia": "AU",
    "Austria": "AT", "Azerbaijan": "AZ", "Bahamas": "BS", "Bahrain": "BH", "Bangladesh": "BD",
    "Barbados": "BB", "Belarus": "BY", "Belgium": "BE", "Belize": "BZ", "Benin": "BJ",
    "Bhutan": "BT", "Bolivia": "BO", "Bosnia and Herzegovina": "BA", "Botswana": "BW",
    "Brazil": "BR", "Brunei": "BN", "Bulgaria": "BG", "Burkina Faso": "BF", "Burundi": "BI",
    "Cambodia": "KH", "Cameroon": "CM", "Canada": "CA", "Cape Verde": "CV",
    "Central African Republic": "CF", "Chad": "TD", "Chile": "CL", "China": "CN",
    "Colombia": "CO", "Comoros": "KM", "Congo": "CG", "Congo (Dem. Rep.)": "CD",
    "Costa Rica": "CR", "Cote d'Ivoire": "CI", "Croatia": "HR", "Cuba": "CU", "Cyprus": "CY",
    "Czech Republic": "CZ", "Czechia": "CZ", "Denmark": "DK", "Djibouti": "DJ",
    "Dominica": "DM", "Dominican Republic": "DO", "Ecuador": "EC", "Egypt": "EG",
    "El Salvador": "SV", "Equatorial Guinea": "GQ", "Eritrea": "ER", "Estonia": "EE",
    "Eswatini": "SZ", "Ethiopia": "ET", "Fiji": "FJ", "Finland": "FI", "France": "FR",
    "Gabon": "GA", "Gambia": "GM", "Georgia": "GE", "Germany": "DE", "Ghana": "GH",
    "Greece": "GR", "Grenada": "GD", "Guatemala": "GT", "Guinea": "GN", "Guinea-Bissau": "GW",
    "Guyana": "GY", "Haiti": "HT", "Honduras": "HN", "Hong Kong": "HK", "Hungary": "HU",
    "Iceland": "IS", "India": "IN", "Indonesia": "ID", "Iran": "IR", "Iraq": "IQ",
    "Ireland": "IE", "Israel": "IL", "Italy": "IT", "Jamaica": "JM", "Japan": "JP",
    "Jordan": "JO", "Kazakhstan": "KZ", "Kenya": "KE", "Kiribati": "KI", "Kosovo": "XK",
    "Kuwait": "KW", "Kyrgyzstan": "KG", "Laos": "LA", "Latvia": "LV", "Lebanon": "LB",
    "Lesotho": "LS", "Liberia": "LR", "Libya": "LY", "Liechtenstein": "LI",
    "Lithuania": "LT", "Luxembourg": "LU", "Macau": "MO", "Madagascar": "MG",
    "Malawi": "MW", "Malaysia": "MY", "Maldives": "MV", "Mali": "ML", "Malta": "MT",
    "Marshall Islands": "MH", "Mauritania": "MR", "Mauritius": "MU", "Mexico": "MX",
    "Micronesia": "FM", "Moldova": "MD", "Monaco": "MC", "Mongolia": "MN",
    "Montenegro": "ME", "Morocco": "MA", "Mozambique": "MZ", "Myanmar": "MM",
    "Namibia": "NA", "Nauru": "NR", "Nepal": "NP", "Netherlands": "NL",
    "New Zealand": "NZ", "Nicaragua": "NI", "Niger": "NE", "Nigeria": "NG",
    "North Korea": "KP", "North Macedonia": "MK", "Norway": "NO", "Oman": "OM",
    "Pakistan": "PK", "Palau": "PW", "Palestinian Territories": "PS", "Panama": "PA",
    "Papua New Guinea": "PG", "Paraguay": "PY", "Peru": "PE", "Philippines": "PH",
    "Poland": "PL", "Portugal": "PT", "Qatar": "QA", "Romania": "RO", "Russia": "RU",
    "Russian Federation": "RU", "Rwanda": "RW", "Saint Kitts and Nevis": "KN",
    "Saint Lucia": "LC", "Saint Vincent and the Grenadines": "VC", "Samoa": "WS",
    "San Marino": "SM", "Sao Tome and Principe": "ST", "Saudi Arabia": "SA",
    "Senegal": "SN", "Serbia": "RS", "Seychelles": "SC", "Sierra Leone": "SL",
    "Singapore": "SG", "Slovakia": "SK", "Slovenia": "SI", "Solomon Islands": "SB",
    "Somalia": "SO", "South Africa": "ZA", "South Korea": "KR", "South Sudan": "SS",
    "Spain": "ES", "Sri Lanka": "LK", "Sudan": "SD", "Suriname": "SR", "Sweden": "SE",
    "Switzerland": "CH", "Syria": "SY", "Taiwan": "TW", "Tajikistan": "TJ",
    "Tanzania": "TZ", "Thailand": "TH", "Timor-Leste": "TL", "Togo": "TG",
    "Tonga": "TO", "Trinidad and Tobago": "TT", "Tunisia": "TN", "Turkey": "TR",
    "Türkiye": "TR", "Turkmenistan": "TM", "Tuvalu": "TV", "Uganda": "UG",
    "Ukraine": "UA", "United Arab Emirates": "AE", "United Kingdom": "GB",
    "United States": "US", "United States of America": "US", "Uruguay": "UY",
    "Uzbekistan": "UZ", "Vanuatu": "VU", "Vatican City": "VA", "Venezuela": "VE",
    "Vietnam": "VN", "Viet Nam": "VN", "Yemen": "YE", "Zambia": "ZM", "Zimbabwe": "ZW",
}

def load_visa_data():
    global VISA_DATA, VISA_MAP
    if not os.path.exists(VISA_DATA_FILE):
        print("UYARI: visa_data.json bulunamadı. Vize filtresi devre dışı.")
        return

    try:
        with open(VISA_DATA_FILE, "r", encoding="utf-8") as f:
            VISA_DATA = json.load(f)
        
        colors = VISA_DATA.get("data", {}).get("colors", {})
        for color, codes_str in colors.items():
            if codes_str:
                VISA_MAP[color] = set(c.strip() for c in codes_str.split(",") if c.strip())
        
        print(f"Vize verisi yüklendi. (Güncelleme: {VISA_DATA.get('fetched_at', '?')[:10]})")
    except Exception as e:
        print(f"Vize verisi yüklenemedi: {e}")

def get_visa_status(country_name):
    if not country_name:
        return False, "bilinmiyor"
    
    # Testte çıkan "United States" gibi isimleri doğrudan sözlükten çekiyoruz
    iso = COUNTRY_NAME_TO_ISO.get(country_name)
    if not iso:
        return False, f"bilinmiyor ({country_name})"
    
    if iso in VISA_MAP.get("green", set()):
        return True, "Vizesiz (Yeşil)"
    if iso in VISA_MAP.get("blue", set()):
        return True, "Kapıda Vize / e-Vize (Mavi)"
    if iso in VISA_MAP.get("yellow", set()):
        return True, "eTA (Sarı)"
    if iso in VISA_MAP.get("red", set()):
        return False, "Vize Gerekli (Kırmızı)"
    return False, "bilinmiyor"

# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def get_usd_tl():
    import requests
    try:
        r = requests.get("https://www.tcmb.gov.tr/kurlar/today.xml", timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            match = re.search(r'<Currency[^>]*CurrencyCode="USD"[^>]*>.*?<ForexSelling>([\d.]+)</ForexSelling>', r.text, re.DOTALL)
            if match: return float(match.group(1))
    except Exception: pass
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if r.status_code == 200: return float(r.json().get("rates", {}).get("TRY", 50.0))
    except Exception: pass
    return 50.0

def _load_state(path):
    if not os.path.exists(path): return {}
    try:
        with open(path, "r", encoding="utf-8") as f: return json.loads(f.read().strip())
    except (json.JSONDecodeError, OSError): return {}

def _save_state(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)

def send_telegram(text):
    import requests
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=15)
    except Exception as e:
        print("Telegram exception:", e)

def _to_tl(price, currency):
    return int(price) if not currency or currency == "TRY" else int(price * USD_TO_TL)

def _price_display(price, currency):
    return f"₺{price:,}" if not currency or currency == "TRY" else f"{price} {currency} (~₺{int(price * USD_TO_TL):,})"

# ============================================================
# SEARCH KATMANI
# ============================================================
def resolve_dates(route):
    today = datetime.now(timezone.utc).date()
    depart = today + timedelta(days=route["departure_offset_days"])
    return depart, depart + timedelta(days=route["stay_days"])

def _search_leg(origin, dest, date_str):
    try:
        out = swoop_search(origin, dest, date_str)
        if not out.results: return None
        prices = [opt.price for opt in out.results if opt.price]
        return min(prices) if prices else None
    except Exception:
        time.sleep(5)
        try:
            out = swoop_search(origin, dest, date_str)
            prices = [opt.price for opt in out.results if opt.price]
            return min(prices) if prices else None
        except Exception: return None

def check_search():
    state = _load_state(SEARCH_STATE_FILE)
    first_run = not os.path.exists(SEARCH_STATE_FILE)
    alerts = 0

    for idx, route in enumerate(GOOGLE_FLIGHTS_WATCH):
        name = route["name"]
        depart, ret_date = resolve_dates(route)
        state_key = f"{name}|{depart}|{ret_date}"

        if idx > 0: time.sleep(REQUEST_DELAY)

        out_min = _search_leg(route["origin"], route["destination"], str(depart))
        time.sleep(1)
        ret_min = _search_leg(route["destination"], route["origin"], str(ret_date))

        if out_min is None or ret_min is None: continue

        total_tl = out_min + ret_min
        prev = state.get(state_key, {})
        was_below = prev.get("below_threshold", False)
        below = total_tl <= route["max_price_tl"]

        if not first_run and below and not was_below:
            send_telegram(
                f"✈️ <b>[Swoop Search] {name}</b>\n"
                f"📅 {depart} → {ret_date}\n"
                f"💰 <b>{total_tl:,.0f} TL</b>\n"
                f"⚠️ <i>Google TR fiyatı, doğrula</i>"
            )
            alerts += 1

        state[state_key] = {"last_tl": total_tl, "below_threshold": below}

    _save_state(SEARCH_STATE_FILE, state)
    return alerts

# ============================================================
# DEALS KATMANI
# ============================================================
def _deal_passes_filters(d):
    if not d.destination_region: return False, "bölge yok"
    
    is_ok, visa_label = get_visa_status(d.destination_country)
    if not is_ok: return False, visa_label

    discount = d.discount_pct or 0
    is_asia = "ASIA" in str(d.destination_region)
    
    if _to_tl(d.price, getattr(d, "currency", "TRY")) > DEALS_MAX_PRICE_TL:
        return False, "fiyat yüksek"

    if not (discount >= DEALS_MIN_DISCOUNT_PCT or (is_asia and discount >= DEALS_ASIA_MIN_DISCOUNT_PCT)):
        return False, "indirim düşük"

    return True, visa_label

def _format_deal_msg(d, visa_label, prefix_emoji="🎯", extra_info=""):
    airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
    price_str = _price_display(d.price, getattr(d, "currency", "TRY"))
    typical_str = f", normal {_price_display(d.typical_price, d.currency)}" if d.typical_price else ""
    disclaimer = "<i>⚠️ Resmi olmayan veri. Kurallar değişebilir; seyahatten önce resmi makamlardan teyit edin.</i>"

    msg = (
        f"{prefix_emoji} <b>[Swoop Deals] IST → {d.destination_city}</b>\n"
        f"📅 {d.departure_date} → {d.return_date}\n"
        f"💰 <b>{price_str}</b>{typical_str} (<b>%{d.discount_pct or 0}</b>)\n"
        f"🛫 {airlines}\n"
        f"🛂 <b>{visa_label}</b>"
    )
    if extra_info: msg += f"\n{extra_info}"
    msg += f"\n\n{disclaimer}"
    return msg

def check_deals():
    try:
        result = deals("IST", transport=TransportConfig(country="TR"))
        if not result.deals: return 0

        diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=True)
        alerts = 0

        for d in diff.new:
            ok, label = _deal_passes_filters(d)
            if ok and alerts < MAX_NOTIFY:
                send_telegram(_format_deal_msg(d, label))
                alerts += 1

        for pc in diff.price_changes:
            d = getattr(pc, "deal", None) or getattr(pc, "current", None)
            if not d: continue
            ok, label = _deal_passes_filters(d)
            if ok and alerts < MAX_NOTIFY:
                old_p = getattr(pc, "old_price", None)
                extra = f"📉 Önceki: {_price_display(old_p, d.currency)}" if old_p and old_p > d.price else ""
                send_telegram(_format_deal_msg(d, label, prefix_emoji="📉", extra_info=extra))
                alerts += 1

        return alerts
    except Exception as e:
        print(f"Deals hata: {e}")
        return 0

# ============================================================
# MAIN
# ============================================================
def main():
    global USD_TO_TL
    print(f"=== Swoop Monitor ===")
    load_visa_data()
    USD_TO_TL = get_usd_tl()
    set_country("TR")
    check_search()
    time.sleep(2)
    check_deals()

if __name__ == "__main__":
    main()
