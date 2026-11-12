import os
import json
import re
import time
from datetime import datetime, timedelta, timezone

from visa_helper import (
    get_visa_by_country_name, get_iso_by_country_name, get_iso_by_iata,
    get_visa_details, is_visa_acceptable, visa_priority,
    VISA_MAP, VISA_LOADED,
)

from swoop import (
    search as swoop_search,
    deals, watch_deals, set_country,
    TransportConfig,
)

SEARCH_STATE_FILE = os.path.join("data", "swoop_search_state.json")
DEALS_STATE_FILE = os.path.join("data", "swoop_deals_state.json")

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
DEALS_MAX_NOTIFY = 15          # YENİ deal limiti (yellow/eTA kabul edilince arttı)
PRICE_CHANGE_MAX_NOTIFY = 8
PRICE_DROP_MIN_PCT = 3          # %3'ten az düşüş bildirilmez
REQUEST_DELAY = 3


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def get_usd_tl():
    import requests
    try:
        r = requests.get("https://www.tcmb.gov.tr/kurlar/today.xml", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            match = re.search(
                r'<Currency[^>]*CurrencyCode="USD"[^>]*>.*?<ForexSelling>([\d.]+)</ForexSelling>',
                r.text, re.DOTALL,
            )
            if match:
                rate = float(match.group(1))
                print(f"   TCMB Kuru: {rate}")
                return rate
    except Exception:
        pass
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if r.status_code == 200:
            rate = float(r.json().get("rates", {}).get("TRY", 50.0))
            print(f"   Fallback Kur: {rate}")
            return rate
    except Exception:
        pass
    print("   Kur çekilemedi, varsayılan 50.0 kullanılıyor.")
    return 50.0


def _load_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read().strip())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def send_telegram(text):
    import requests
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:
        print("Telegram exception:", e)


def _to_tl(price, currency):
    return int(price) if not currency or currency == "TRY" else int(price * USD_TO_TL)


def _price_display(price, currency):
    return f"₺{price:,}" if not currency or currency == "TRY" else f"{price} {currency} (~₺{int(price * USD_TO_TL):,})"


def _visa_emoji(color):
    return {"green": "🟢", "yellow": "🟡", "blue": "🔵", "red": "🔴"}.get(color, "⚪")


# ============================================================
# SEARCH KATMANI (vize bilgisi eklendi)
# ============================================================
def resolve_dates(route):
    today = datetime.now(timezone.utc).date()
    depart = today + timedelta(days=route["departure_offset_days"])
    return depart, depart + timedelta(days=route["stay_days"])


def _search_roundtrip_details(origin, dest, depart_date, return_date):
    def _do_search():
        out = swoop_search(origin, dest, depart_date, return_date=return_date)
        if not out.results:
            return None
        valid = [(opt.price, opt) for opt in out.results if opt.price]
        if not valid:
            return None
        valid.sort(key=lambda x: x[0])
        min_price, min_opt = valid[0]

        details = {
            "price": min_price,
            "airline": "?",
            "duration_minutes": None,
            "stops": None,
        }
        if min_opt.legs:
            itin = min_opt.legs[0].itinerary
            if itin:
                details["airline"] = ", ".join(itin.airline_names) if itin.airline_names else "?"
                details["duration_minutes"] = itin.travel_time
                details["stops"] = itin.stop_count
        return details

    try:
        return _do_search()
    except Exception as e:
        print(f"    [Search Hata] {origin}->{dest}: {type(e).__name__}: {str(e)[:80]}", flush=True)
        time.sleep(5)
        try:
            return _do_search()
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

        details = _search_roundtrip_details(
            route["origin"], route["destination"], str(depart), str(ret_date),
        )
        if not details:
            print(f"    Sonuç yok veya hata alındı.", flush=True)
            continue

        total_tl = details["price"]
        print(f"    Bulunan Fiyat: {total_tl:,.0f} TL | {details['airline']}", flush=True)

        prev = state.get(state_key, {})
        was_below = prev.get("below_threshold", False)
        below = total_tl <= route["max_price_tl"]

        if not first_run and below and not was_below:
            airline = details["airline"]
            stops_str = "Direkt" if details["stops"] == 0 else (
                f"{details['stops']} aktarma" if details["stops"] is not None else "?"
            )
            if details["duration_minutes"]:
                h, m = divmod(int(details["duration_minutes"]), 60)
                dur_str = f"{h}s {m:02d}dk"
            else:
                dur_str = "?"

            # VİZE BİLGİSİ (Search için IATA → ISO → detay)
            iso2 = get_iso_by_iata(route["destination"])
            vd = get_visa_details(iso2, trip_days=route["stay_days"]) if iso2 else None

            visa_line = ""
            warn_lines = ""
            if vd:
                emoji = _visa_emoji(vd.get("color"))
                dur = vd.get("duration")
                visa_line = f"\n🛂 {emoji} {vd.get('name', '?')}{f' ({dur})' if dur else ''}"
                if vd.get("warnings"):
                    warn_lines = "\n" + "\n".join(vd["warnings"])
                if vd.get("link"):
                    warn_lines += f"\n🔗 <a href='{vd['link']}'>Resmi kaynak</a>"

            send_telegram(
                f"✈️ <b>[Swoop Search] {name}</b>\n"
                f"📅 {depart} → {ret_date}\n"
                f"💰 <b>{total_tl:,.0f} TL</b>\n"
                f"🛫 {airline} | {stops_str} | {dur_str}"
                f"{visa_line}{warn_lines}\n"
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
    """True ise (d, visa_details) döner. False ise (False, neden) döner."""
    if not d.destination_region:
        return False, "bölge yok"
    if not d.destination_country:
        return False, "ülke yok"

    iso2 = get_iso_by_country_name(d.destination_country)
    if not iso2:
        return False, f"bilinmeyen ülke: {d.destination_country}"

    acceptable, reason = is_visa_acceptable(iso2)
    if not acceptable:
        return False, f"vize engeli ({reason})"

    if _to_tl(d.price, getattr(d, "currency", "TRY")) > DEALS_MAX_PRICE_TL:
        return False, "fiyat yüksek"

    discount = d.discount_pct or 0
    is_asia = "ASIA" in str(d.destination_region)
    if not (discount >= DEALS_MIN_DISCOUNT_PCT or (is_asia and discount >= DEALS_ASIA_MIN_DISCOUNT_PCT)):
        return False, "indirim düşük"

    details = get_visa_details(iso2, trip_days=d.trip_days)
    return True, details


def _deal_priority_score(d, details):
    """Düşük = önce gönderilir. Vize kolaylığı + indirim."""
    iso2 = get_iso_by_country_name(d.destination_country) if d.destination_country else None
    vp = visa_priority(iso2) if iso2 else 9
    # İndirim yüzdesi yüksekse daha iyi (negatif score)
    discount = d.discount_pct or 0
    return (vp * 100) - discount  # vize öncelikli, sonra indirim


def _format_deal_msg(d, details, prefix_emoji="🎯", extra_info=""):
    airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
    price_str = _price_display(d.price, getattr(d, "currency", "TRY"))
    typical_str = f", normal {_price_display(d.typical_price, d.currency)}" if d.typical_price else ""
    disclaimer = "<i>⚠️ Resmi olmayan veri. Kurallar değişebilir; seyahatten önce teyit edin.</i>"

    stops_str = "Direkt" if d.stops == 0 else (
        f"{d.stops} aktarma" if d.stops is not None else "?"
    )
    if d.duration_minutes:
        h, m = divmod(int(d.duration_minutes), 60)
        dur_str = f"{h}s {m:02d}dk"
    else:
        dur_str = "?"
    days_str = f"{d.trip_days} gece" if d.trip_days is not None else "?"

    color = details.get("color")
    emoji = _visa_emoji(color)
    v_name = details.get("name") or "?"
    v_dur = details.get("duration")
    v_dur_str = f" ({v_dur})" if v_dur else ""
    visa_line = f"{emoji} {v_name}{v_dur_str}"

    country_display = f" ({d.destination_country})" if d.destination_country else ""
    msg = (
        f"{prefix_emoji} <b>[Swoop Deals] IST → {d.destination_city}{country_display}</b>\n"
        f"📅 {d.departure_date} → {d.return_date}\n"
        f"💰 <b>{price_str}</b>{typical_str} (<b>%{d.discount_pct or 0}</b>)\n"
        f"🛫 {airlines} | {stops_str} | {dur_str} | {days_str}\n"
        f"🛂 <b>{visa_line}</b>\n"
    )

    # Secondary rule (varsa alt seçenek)
    sec = details.get("secondary")
    if sec and sec.get("name"):
        sec_line = f"   ↳ Alternatif: {sec['name']}"
        if sec.get("duration"):
            sec_line += f" ({sec['duration']})"
        msg += f"{sec_line}\n"

    # Uyarılar (süre yetersiz, pasaport, zorunlu kayıt)
    for w in details.get("warnings", []):
        msg += f"{w}\n"

    # İstisna (ilk 1 tanesi)
    for ex in (details.get("exceptions") or [])[:1]:
        msg += f"ℹ️ <i>İstisna: {ex.get('name')} ({ex.get('exception_type_name', '?')})</i>\n"

    if details.get("link"):
        msg += f"🔗 <a href='{details['link']}'>Resmi kaynak</a>\n"
    if d.booking_url:
        msg += f"🔗 <a href='{d.booking_url}'>Rezervasyon</a>\n"
    if extra_info:
        msg += f"{extra_info}\n"
    msg += f"\n{disclaimer}"
    return msg

def _process_price_changes(diff):
    """
    Fiyat değişimlerini işle. Sadece DÜŞÜŞLER, minimum %PRICE_DROP_MIN_PCT eşikli.
    
    Returns:
        (alerts_sent, passed_list, rejected_dict)
        - alerts_sent: gönderilen bildirim sayısı
        - passed_list: [(d, details, old_p, new_p, drop_pct), ...] geçenler
        - rejected_dict: {sebep: sayı} reddedilenler
    """
    passed = []
    rejected = {}

    for pc in diff.price_changes:
        d = pc.current                      # API: PriceChange.prior / .current
        if not d:
            rejected["boş deal"] = rejected.get("boş deal", 0) + 1
            continue

        old_p = pc.prior.price              # ESKİ fiyat
        new_p = pc.current.price            # YENİ fiyat

        # 1) Fiyat düşmemişse atla
        if not old_p or not new_p or new_p >= old_p:
            rejected["fiyat düşmedi"] = rejected.get("fiyat düşmedi", 0) + 1
            continue

        # 2) Vize + bölge + fiyat + indirim filtreleri
        ok, detail_or_reason = _deal_passes_filters(d)
        if not ok:
            reason_key = (
                detail_or_reason.split(":")[0].split("(")[0].strip()
                if detail_or_reason else "bilinmiyor"
            )
            rejected[reason_key] = rejected.get(reason_key, 0) + 1
            print(f"    ❌ Price change elendi: {d.destination_city} — {detail_or_reason}", flush=True)
            continue

        # 3) Minimum düşüş eşiği (%3)
        drop_pct = (old_p - new_p) / old_p * 100
        if drop_pct < PRICE_DROP_MIN_PCT:
            key = f"düşüş <%{PRICE_DROP_MIN_PCT}"
            rejected[key] = rejected.get(key, 0) + 1
            print(f"    ↪️  Düşüş çok küçük: {d.destination_city} (%{drop_pct:.1f})", flush=True)
            continue

        passed.append((d, detail_or_reason, old_p, new_p, drop_pct))
        print(f"    📊 Price change geçti: {d.destination_city} "
              f"({old_p:,} → {new_p:,}, %{drop_pct:.1f})", flush=True)

    # En yüksek düşüş yüzdesine göre sırala
    passed.sort(key=lambda x: -x[4])

    # Bildirimleri gönder (limitli)
    alerts = 0
    for d, details, old_p, new_p, drop_pct in passed[:PRICE_CHANGE_MAX_NOTIFY]:
        extra = f"📉 Önceki: {_price_display(old_p, d.currency)} (%{drop_pct:.0f} düşüş)"
        send_telegram(_format_deal_msg(d, details, prefix_emoji="📉", extra_info=extra))
        print(f"    📉 DÜŞÜŞ: {d.destination_city} "
              f"({old_p:,} → {new_p:,})", flush=True)
        alerts += 1

    # Limit aşıldıysa özet
    if len(passed) > PRICE_CHANGE_MAX_NOTIFY:
        kalan = len(passed) - PRICE_CHANGE_MAX_NOTIFY
        en_iyi = passed[PRICE_CHANGE_MAX_NOTIFY:][:3]
        liste = "\n".join(
            f"   • {d.destination_city} (%{drop:.0f}) — ₺{int(new_p):,}"
            for d, _, _, new_p, drop in en_iyi
        )
        send_telegram(
            f"ℹ️ <b>Swoop Deals — Fiyat Düşüşleri</b>\n"
            f"Toplam <b>{len(passed)}</b> düşüş; en iyi <b>{PRICE_CHANGE_MAX_NOTIFY}</b> tanesi gönderildi.\n"
            f"Kalan {kalan} arasında öne çıkanlar:\n{liste}"
        )
        print(f"    ⚠️ {kalan} düşüş limit nedeniyle gösterilmedi", flush=True)

    return alerts, passed, rejected

def check_deals():
    print("--- Swoop Deals Başladı ---", flush=True)
    if not VISA_LOADED:
        send_telegram(
            "🚨 <b>Swoop Deals DURDURULDU</b>\n"
            "visa_data.json boş/eksik. Lütfen update_visa_data workflow'unu çalıştırın."
        )
        return 0

    max_retries = 3
    cache_exists = os.path.exists(DEALS_STATE_FILE) and os.path.getsize(DEALS_STATE_FILE) > 100
    print(f"  Cache durumu: {'Mevcut' if cache_exists else 'Yok (ilk çalıştırma)'}", flush=True)

    for attempt in range(max_retries):
        try:
            print(f"  Google Flights'tan fırsatlar çekiliyor (Deneme {attempt+1}/{max_retries})...", flush=True)
            result = deals("IST", transport=TransportConfig(country="TR"))

            if not result.deals:
                print("  Hiç deal bulunamadı.", flush=True)
                return 0

            print(f"  {len(result.deals)} adet deal alındı. Filtreleme yapılıyor...", flush=True)

            if not cache_exists:
                diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=True)
                print(f"  İlk kayıt yapıldı ({len(diff.new)} deal). Bildirim gönderilmiyor.", flush=True)
                return 0

            diff = watch_deals(result, cache_path=DEALS_STATE_FILE, allow_empty=False)
            print(f"  Yeni: {len(diff.new)}, Fiyat Değişimi: {len(diff.price_changes)}", flush=True)

            # ============================================================
            # 1. YENİ DEAL'LER
            # ============================================================
            passed_new = []
            rejected_new = {}

            for d in diff.new:
                ok, detail_or_reason = _deal_passes_filters(d)
                if ok:
                    passed_new.append((d, detail_or_reason))
                else:
                    reason_key = (
                        detail_or_reason.split(":")[0].split("(")[0].strip()
                        if detail_or_reason else "bilinmiyor"
                    )
                    rejected_new[reason_key] = rejected_new.get(reason_key, 0) + 1
                    print(f"    ❌ YENİ elendi: {d.destination_city} — {detail_or_reason}", flush=True)

            print(f"  Yeni filtreden geçen: {len(passed_new)} / {len(diff.new)}", flush=True)
            if rejected_new:
                print(f"  Yeni eleme sebepleri: {rejected_new}", flush=True)

            passed_new.sort(key=lambda x: _deal_priority_score(x[0], x[1]))

            alerts_new = 0
            for d, details in passed_new[:DEALS_MAX_NOTIFY]:
                send_telegram(_format_deal_msg(d, details))
                print(f"    ✅ YENİ: {d.destination_city} (%{d.discount_pct}) — {details.get('name')}", flush=True)
                alerts_new += 1

            if len(passed_new) > DEALS_MAX_NOTIFY:
                kalan = len(passed_new) - DEALS_MAX_NOTIFY
                en_iyi = passed_new[DEALS_MAX_NOTIFY:][:3]
                liste = "\n".join(
                    f"   • {d.destination_city} (%{d.discount_pct}) — ₺{int(d.price):,}"
                    for d, _ in en_iyi
                )
                send_telegram(
                    f"ℹ️ <b>Swoop Deals — Özet</b>\n"
                    f"Toplam <b>{len(passed_new)}</b> yeni fırsat; en iyi <b>{DEALS_MAX_NOTIFY}</b> tanesi gönderildi.\n"
                    f"Kalan {kalan} arasında öne çıkanlar:\n{liste}"
                )
                print(f"    ⚠️ {kalan} fırsat limit nedeniyle gösterilmedi", flush=True)

            # ============================================================
            # 2. FİYAT DEĞİŞİMLERİ — ayrı fonksiyon
            # ============================================================
            print(f"  Price change işleniyor ({len(diff.price_changes)} toplam)...", flush=True)
            alerts_drop, passed_changes, rejected_changes = _process_price_changes(diff)

            if rejected_changes:
                print(f"  Price change eleme sebepleri: {rejected_changes}", flush=True)
            print(f"  Price change: {len(passed_changes)} geçti / {len(diff.price_changes)} toplam", flush=True)

            toplam = alerts_new + alerts_drop
            print(f"--- Swoop Deals Bitti ({alerts_new} yeni + {alerts_drop} düşüş = {toplam}) ---", flush=True)
            return toplam

        except Exception as e:
            err_msg = str(e)
            if "gRPC status 13" in err_msg or "INTERNAL" in err_msg:
                if attempt < max_retries - 1:
                    print(f"  ⚠️ Google geçici hata. 10sn bekleniyor (deneme {attempt+1}/{max_retries})...", flush=True)
                    time.sleep(10)
                else:
                    print(f"--- Swoop Deals HATA: Rate limit, atlanıyor. ---", flush=True)
                    return 0
            else:
                print(f"--- Swoop Deals HATA: {err_msg} ---", flush=True)
                return 0

# ============================================================
# MAIN
# ============================================================
def main():
    global USD_TO_TL
    print(f"=== Swoop Monitor Başladı ===")

    if not VISA_LOADED:
        print("🚨 Vize verisi yüklenemedi, deals katmanı duracak.")
    else:
        print(f"✅ Vize verisi yüklendi ({len(VISA_MAP['green'])} green, {len(VISA_MAP['blue'])} blue, "
              f"{len(VISA_MAP['yellow'])} yellow, {len(VISA_MAP['red'])} red)")

    print("Döviz kuru çekiliyor...")
    USD_TO_TL = get_usd_tl()

    set_country("TR")
    print("Ülke ayarlandı: TR")

    print("\n4. Arama (Search) başlıyor...")
    check_search()

    print("\n5. Bekleme süresi...")
    time.sleep(2)

    print("\n6. Fırsatlar (Deals) başlıyor...")
    check_deals()

    print("\n=== Swoop Monitor Tamamlandı ===")


if __name__ == "__main__":
    main()
