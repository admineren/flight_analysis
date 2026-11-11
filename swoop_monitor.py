import os
import json
import re
import time
from datetime import datetime, timedelta, timezone
from visa_helper import get_visa_by_country_name

from swoop import (
    search as swoop_search,
    deals, watch_deals, set_country,
    TransportConfig,
)

SEARCH_STATE_FILE = os.path.join("data", "swoop_search_state.json")
DEALS_STATE_FILE = os.path.join("data", "swoop_deals_state.json")
VISA_DATA_FILE = os.path.join("data", "visa_data.json")

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

USD_TO_TL = 50.0

GOOGLE_FLIGHTS_WATCH = [
    {"name": "IST → Tbilisi", "origin": "IST", "destination": "TBS",
     "departure_offset_days": 60, "stay_days": 7, "max_price_tl": 11000},
    {"name": "IST → Baku", "origin": "IST", "destination": "GYD",
     "departure_offset_days": 60, "stay_days": 7, "max_price_tl": 17000},
    {"name": "IST → Belgrad", "origin": "IST", "destination": "BEG",
     "departure_offset_days": 60, "stay_days": 7, "max_price_tl": 11000},
    {"name": "IST → Minsk", "origin": "IST", "destination": "MSQ",
     "departure_offset_days": 60, "stay_days": 7, "max_price_tl": 30000},
    {"name": "IST → Saraybosna", "origin": "IST", "destination": "SJJ",
     "departure_offset_days": 60, "stay_days": 7, "max_price_tl": 8500},
]

DEALS_MIN_DISCOUNT_PCT = 40
DEALS_ASIA_MIN_DISCOUNT_PCT = 25
DEALS_MAX_PRICE_TL = 40000
MAX_NOTIFY = 5
REQUEST_DELAY = 3

# ============================================================
# VİZE VERİSİ
# ============================================================
VISA_DATA = {}
VISA_MAP = {"green": set(), "blue": set(), "yellow": set(), "red": set()}

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
        
        date_str = VISA_DATA.get('meta', {}).get('generated_at', '?')[:10]
        print(f"Vize verisi yüklendi. (Güncelleme: {date_str})")
    except Exception as e:
        print(f"Vize verisi yüklenemedi: {e}")

# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def get_usd_tl():
    import requests
    try:
        r = requests.get("https://www.tcmb.gov.tr/kurlar/today.xml", timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            match = re.search(r'<Currency[^>]*CurrencyCode="USD"[^>]*>.*?<ForexSelling>([\d.]+)</ForexSelling>', r.text, re.DOTALL)
            if match: 
                rate = float(match.group(1))
                print(f"   TCMB Kuru: {rate}")
                return rate
    except Exception: pass
    
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if r.status_code == 200:
            rate = float(r.json().get("rates", {}).get("TRY", 50.0))
            print(f"   Fallback Kur: {rate}")
            return rate
    except Exception: pass
    
    print("   Kur çekilemedi, varsayılan 50.0 kullanılıyor.")
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

def _search_roundtrip(origin, dest, depart_date, return_date):
    """Tek çağrıda gerçek gidiş-dönüş bundle fiyatı al."""
    try:
        out = swoop_search(origin, dest, depart_date, return_date=return_date)
        if not out.results:
            return None
        prices = [opt.price for opt in out.results if opt.price]
        return min(prices) if prices else None
    except Exception as e:
        print(f"    [Search Hata] {origin}->{dest}: {type(e).__name__}: {str(e)[:80]}", flush=True)
        time.sleep(5)
        try:
            out = swoop_search(origin, dest, depart_date, return_date=return_date)
            prices = [opt.price for opt in out.results if opt.price]
            return min(prices) if prices else None
        except Exception:
            print(f"    [Search Retry Hata] {origin}->{dest}", flush=True)
            return None

def check_search():
    print("--- Swoop Search Başladı ---", flush=True)
    state = _load_state(SEARCH_STATE_FILE)
    first_run = not os.path.exists(SEARCH_STATE_FILE)
    alerts = 0

    for idx, route in enumerate(GOOGLE_FLIGHTS_WATCH):
        name = route["name"]
        depart, ret_date = resolve_dates(route)
        state_key = f"{name}|{depart}|{ret_date}"

        print(f"  [{name}] kontrol ediliyor ({depart} → {ret_date})...", flush=True)

        if idx > 0:
            time.sleep(REQUEST_DELAY)

        # TEK ÇAĞRI: gerçek gidiş-dönüş bundle
        total_tl = _search_roundtrip(
            route["origin"], route["destination"],
            str(depart), str(ret_date),
        )

        if total_tl is None:
            print(f"    Sonuç yok veya hata alındı.", flush=True)
            continue

        print(f"    Bulunan Fiyat: {total_tl:,.0f} TL", flush=True)

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
    print(f"--- Swoop Search Bitti ({alerts} bildirim) ---", flush=True)
    return alerts

# ============================================================
# DEALS KATMANI
# ============================================================
def _deal_passes_filters(d):
    if not d.destination_region:
        return False, "bölge yok"
    
    visa_label = get_visa_by_country_name(d.destination_country)
    
    if "🟢" not in visa_label and "🔵" not in visa_label:
        return False, f"vize engeli ({visa_label})"
    
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

    # YENİ: Aktarma, süre, kalış günü
    stops_str = f"{d.stops} aktarma" if d.stops is not None else "?"
    if d.duration_minutes:
        h, m = divmod(int(d.duration_minutes), 60)
        dur_str = f"{h}s {m:02d}dk"
    else:
        dur_str = "?"
    days_str = f"{d.trip_days} gece" if d.trip_days is not None else "?"

    country_display = f" ({d.destination_country})" if d.destination_country else ""
    msg = (
        f"{prefix_emoji} <b>[Swoop Deals] IST → {d.destination_city}{country_display}</b>\n"
        f"📅 {d.departure_date} → {d.return_date}\n"
        f"💰 <b>{price_str}</b>{typical_str} (<b>%{d.discount_pct or 0}</b>)\n"
        f"🛫 {airlines} | {stops_str} | {dur_str} | {days_str}\n"
        f"🛂 <b>{visa_label}</b>"
    )
    if d.booking_url:
        msg += f"\n🔗 <a href='{d.booking_url}'>Rezervasyon</a>"
    if extra_info:
        msg += f"\n{extra_info}"
    msg += f"\n\n{disclaimer}"
    return msg

def check_deals():
    print("--- Swoop Deals Başladı ---")
    max_retries = 3
    
    # Cache durumunu kontrol et (ilk çalıştırma mı?)
    cache_exists = os.path.exists(DEALS_STATE_FILE) and os.path.getsize(DEALS_STATE_FILE) > 100
    print(f"  Cache durumu: {'Mevcut' if cache_exists else 'Yok (ilk çalıştırma)'}")
    
    for attempt in range(max_retries):
        try:
            print(f"  Google Flights'tan fırsatlar çekiliyor (Deneme {attempt+1}/{max_retries})...")
            result = deals("IST", transport=TransportConfig(country="TR"))
            
            if not result.deals: 
                print("  Hiç deal bulunamadı.")
                return 0

            print(f"  {len(result.deals)} adet deal alındı. Filtreleme yapılıyor...")
            
            # Cache yoksa ilk çalıştırma gibi davran (sessiz), varsa normal diff yap
            if not cache_exists:
                diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=True)
                print(f"  İlk kayıt yapıldı ({len(diff.new)} deal). Bildirim gönderilmiyor.")
                return 0
            
            diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=False)
            
            print(f"  Yeni: {len(diff.new)}, Fiyat Değişimi: {len(diff.price_changes)}")
            alerts = 0

            # 1. YENİ DEAL'LER
            for d in diff.new:
                ok, label = _deal_passes_filters(d)
                if ok and alerts < MAX_NOTIFY:
                    send_telegram(_format_deal_msg(d, label))
                    print(f"    ✅ YENİ: {d.destination_city} ({label})")
                    alerts += 1

            # 2. FİYAT DEĞİŞİMLERİ (SADECE DÜŞÜŞLER)
            for pc in diff.price_changes:
                d = getattr(pc, "deal", None) or getattr(pc, "current", None)
                if not d: continue
                
                old_p = getattr(pc, "old_price", None) or getattr(pc, "prior_price", None)
                new_p = getattr(pc, "new_price", None) or d.price
                
                # SADECE DÜŞÜŞLERİ BİLDİR (artışları yoksay)
                if not old_p or not new_p or new_p >= old_p:
                    continue
                
                ok, label = _deal_passes_filters(d)
                if ok and alerts < MAX_NOTIFY:
                    drop_pct = (old_p - new_p) / old_p * 100
                    extra = f"📉 Önceki: {_price_display(old_p, d.currency)} (%{drop_pct:.0f} düşüş)"
                    send_telegram(_format_deal_msg(d, label, prefix_emoji="📉", extra_info=extra))
                    print(f"    📉 DÜŞÜŞ: {d.destination_city} ({old_p:,} → {new_p:,})")
                    alerts += 1

            print(f"--- Swoop Deals Bitti ({alerts} bildirim) ---")
            return alerts
            
        except Exception as e:
            err_msg = str(e)
            if "gRPC status 13" in err_msg or "INTERNAL" in err_msg:
                if attempt < max_retries - 1:
                    print(f"  ⚠️ Google geçici hata. 10 saniye bekleniyor...")
                    time.sleep(10)
                else:
                    print(f"--- Swoop Deals HATA: Rate limit, atlanıyor. ---")
                    return 0
            else:
                print(f"--- Swoop Deals HATA: {err_msg} ---")
                return 0

# ============================================================
# MAIN
# ============================================================
def main():
    global USD_TO_TL
    print(f"=== Swoop Monitor Başladı ===")
    
    print("1. Vize verisi yükleniyor...")
    load_visa_data()
    
    print("2. Döviz kuru çekiliyor...")
    USD_TO_TL = get_usd_tl()
    
    set_country("TR")
    print("3. Ülke ayarlandı: TR (Fiyatlar TL cinsinden)")

    print("\n4. Arama (Search) başlıyor...")
    check_search()
    
    print("\n5. Bekleme süresi (Rate limit koruması)...")
    time.sleep(2)
    
    print("\n6. Fırsatlar (Deals) başlıyor...")
    check_deals()
    
    print("\n=== Swoop Monitor Tamamlandı ===")

if __name__ == "__main__":
    main()
