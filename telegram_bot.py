import sys
import os
import json
import time
import requests
from datetime import date, timedelta, datetime

from viajante import get_flights, search_flex, search_dates
from visa_helper import (
    get_visa_by_iata, get_iso_by_iata, get_visa_details,
    get_iso_by_country_name, COUNTRIES,
)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_READ_TOKEN = os.environ.get("TB_READ_TOKEN")

STATE_FILE = "data/telegram_state.json"
DEALS_CACHE_FILE = "data/swoop_deals_state.json"

_TB_CACHE = {}
_TB_CACHE_TTL = 300


# ============================================================
# YARDIMCILAR
# ============================================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_update_id": 0}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code == 200:
            print(f"📤 Mesaj gönderildi ({len(text)} karakter)", flush=True)
        else:
            print(f"⚠️ Telegram hatası: {r.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Mesaj gönderilemedi: {e}", flush=True)


# ============================================================
# TINYBIRD (cache'li)
# ============================================================
def tb_latest_price(origin, dest, dep_date):
    url = f"{TB_HOST}/v0/pipes/latest_price.json"
    headers = {"Authorization": f"Bearer {TB_READ_TOKEN}"}
    params = {"origin": origin, "destination": dest, "departure_date": dep_date}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            return data[0] if data else None
    except Exception:
        pass
    return None


def tb_trend(origin, dest, dep_date, days=7):
    url = f"{TB_HOST}/v0/pipes/price_history_trend.json"
    headers = {"Authorization": f"Bearer {TB_READ_TOKEN}"}
    params = {"origin": origin, "destination": dest, "departure_date": dep_date, "days": days}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            return data[0] if data else None
    except Exception:
        pass
    return None


def tb_latest_cached(origin, dest, dep):
    key = f"latest|{origin}|{dest}|{dep}"
    now = time.time()
    if key in _TB_CACHE and now - _TB_CACHE[key]["at"] < _TB_CACHE_TTL:
        return _TB_CACHE[key]["data"]
    data = tb_latest_price(origin, dest, dep)
    _TB_CACHE[key] = {"at": now, "data": data}
    return data


def tb_trend_cached(origin, dest, dep, days=7):
    key = f"trend|{origin}|{dest}|{dep}|{days}"
    now = time.time()
    if key in _TB_CACHE and now - _TB_CACHE[key]["at"] < _TB_CACHE_TTL:
        return _TB_CACHE[key]["data"]
    data = tb_trend(origin, dest, dep, days)
    _TB_CACHE[key] = {"at": now, "data": data}
    return data


# ============================================================
# FORMAT YARDIMCILARI
# ============================================================
def _visa_emoji(color):
    return {"green": "🟢", "yellow": "🟡", "blue": "🔵", "red": "🔴"}.get(color, "⚪")


def format_vs_typical(pct):
    if pct is None:
        return ""
    if pct <= -15: return f"🟢 Tipikten %{abs(pct)} ucuz (SÜPER FIRSAT)"
    if pct <= -5: return f"🟢 Tipikten %{abs(pct)} ucuz"
    if pct <= 5: return f"🟡 Tipik seviyede"
    if pct <= 20: return f"🟠 Tipikten %{pct} pahalı"
    return f"🔴 Tipikten %{pct} pahalı (BEKLE)"


def format_baggage(offer):
    if getattr(offer, "needs_bag_verify", False):
        return "⚠️ Bagaj ücreti doğrulanmalı"
    if getattr(offer, "checked_bags", None) is not None:
        return f"🎒 {offer.checked_bags} kg bagaj dahil"
    if getattr(offer, "carry_on", None) is not None:
        return f"🎒 {offer.carry_on} kg kabin"
    return ""


def _seg_dt(seg, is_arrival):
    if is_arrival:
        d, t, tz = seg.arrival_date, seg.arrival, seg.arrival_timezone
    else:
        d, t, tz = seg.departure_date, seg.departure, seg.departure_timezone
    if not (d and t and tz):
        return None
    try:
        from zoneinfo import ZoneInfo
        naive = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=ZoneInfo(tz))
    except Exception:
        return None


def _fmt_duration(mins):
    if mins is None or mins < 0:
        return "?"
    h, m = divmod(int(mins), 60)
    return f"{h}s {m:02d}dk"


def flight_details(offer):
    if not offer.legs:
        return None
    outbound = offer.legs[0]
    segs = outbound.segments or ()
    if not segs:
        return None
    flight_mins = sum((s.duration_minutes or 0) for s in segs) or None
    first_dep = _seg_dt(segs[0], is_arrival=False)
    last_arr = _seg_dt(segs[-1], is_arrival=True)
    total_mins = None
    if first_dep and last_arr:
        total_mins = int((last_arr - first_dep).total_seconds() // 60)
    layovers = []
    for i in range(len(segs) - 1):
        cur_arr = _seg_dt(segs[i], is_arrival=True)
        nxt_dep = _seg_dt(segs[i + 1], is_arrival=False)
        wait_mins = None
        if cur_arr and nxt_dep:
            wait_mins = int((nxt_dep - cur_arr).total_seconds() // 60)
        layovers.append({"airport": segs[i].destination or "?", "wait_mins": wait_mins})
    return {"flight_mins": flight_mins, "total_mins": total_mins, "layovers": layovers}


# ============================================================
# /vize
# ============================================================
def cmd_vize(args):
    if len(args) < 1:
        return "❌ Kullanım: <code>/vize TH</code> veya <code>/vize BKK</code>"

    code = args[0].upper()
    if len(code) == 3:
        iso2 = get_iso_by_iata(code)
        if not iso2:
            return f"❌ <b>{code}</b> havalimanı bulunamadı."
    elif len(code) == 2:
        iso2 = code
    else:
        return "❌ 2 harfli ISO (TH) veya 3 harfli IATA (BKK) girin."

    country_name = COUNTRIES.get(iso2, "")
    title = f"<b>{country_name}</b> ({iso2})" if country_name else f"<b>{iso2}</b>"

    detail = get_visa_details(iso2)
    if not detail:
        return (
            f"🛂 {title}\n"
            f"⚪ Detay yok\n\n"
            f"⚠️ Bu ülkenin vize detayı henüz çekilmedi."
        )

    emoji = _visa_emoji(detail.get("color"))
    lines = [f"🛂 {title}", f"{emoji} <b>{detail.get('name', '?')}</b>"]
    if detail.get("duration"):
        lines.append(f"⏱️ Süre: {detail['duration']}")

    sec = detail.get("secondary") or {}
    if sec.get("name"):
        sec_str = f"   ↳ Alternatif: {sec['name']}"
        if sec.get("duration"):
            sec_str += f" ({sec['duration']})"
        lines.append(sec_str)

    for w in detail.get("warnings", []):
        lines.append(w)

    for ex in (detail.get("exceptions") or [])[:2]:
        lines.append(f"ℹ️ <i>İstisna: {ex.get('name')} ({ex.get('exception_type_name', '?')})</i>")

    if detail.get("link"):
        lines.append(f"🔗 <a href='{detail['link']}'>Resmi kaynak</a>")

    return "\n".join(lines)


# ============================================================
# /detay — Latest + Trend + Vize (tek komut)
# ============================================================
def cmd_detay(args):
    if len(args) < 3:
        return "❌ Kullanım: <code>/detay IST BKK 2027-02-15 [gün]</code>"

    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    days = int(args[3]) if len(args) > 3 and args[3].isdigit() else 30

    lines = [f"📊 <b>{origin} → {dest}</b> ({dep})\n"]

    # 1. Son kayıtlı fiyat
    latest = tb_latest_cached(origin, dest, dep)
    if latest:
        price = latest.get("price", 0)
        airline = latest.get("airline", "?")
        level = latest.get("price_level", "unknown")
        level_emoji = {"low": "🟢", "typical": "🟡", "high": "🔴"}.get(level, "⚪")
        observed = (latest.get("observed_at", "") or "").replace("T", " ").replace("Z", "")[:16]
        lines.append(f"💰 Son: <b>{price:,.0f} TRY</b> {level_emoji} {level.upper()}")
        lines.append(
            f"🛫 {airline} | {latest.get('stops', '?')} akt | "
            f"{latest.get('duration_hours', 0):.1f}s"
        )
        if latest.get("layover_city"):
            lines.append(
                f"   ↳ {latest['layover_city']} "
                f"{latest.get('layover_hours', 0):.1f}s bekleme"
            )
        if observed:
            lines.append(f"🕐 {observed} UTC")
    else:
        lines.append("📭 Tinybird'de kayıt yok")

    # 2. Trend
    trend = tb_trend_cached(origin, dest, dep, days)
    if trend and trend.get("observation_count"):
        count = trend["observation_count"]
        lowest = trend.get("lowest_price", 0)
        highest = trend.get("highest_price", 0)
        avg = trend.get("avg_price", 0)
        lines.append(f"\n📈 <b>Son {days} gün</b> ({count} gözlem)")
        lines.append(f"   🟢 En düşük: <b>{lowest:,.0f} TRY</b>")
        lines.append(f"   🔴 En yüksek: {highest:,.0f} TRY")
        lines.append(f"   📊 Ortalama: {avg:,.0f} TRY")
        if latest and avg > 0:
            diff = (latest["price"] - avg) / avg * 100
            if diff < -5:
                lines.append(f"   📉 Ortalamanın %{abs(diff):.0f} altında ✅")
            elif diff > 5:
                lines.append(f"   📈 Ortalamanın %{diff:.0f} üstünde ⚠️")

        # Latest trend'de yok mu?
        last_latest = (latest.get("observed_at") or "")[:19] if latest else ""
        last_trend = (trend.get("last_seen") or "")[:19]
        if last_latest and last_trend and last_latest > last_trend:
            lines.append(f"\nℹ️ Son ölçüm henüz trend'e kaydedilmedi")

    # 3. Vize
    iso2 = get_iso_by_iata(dest)
    if iso2:
        vd = get_visa_details(iso2)
        if vd:
            emoji = _visa_emoji(vd.get("color"))
            dur = f" ({vd['duration']})" if vd.get("duration") else ""
            lines.append(f"\n🛂 {emoji} {vd.get('name', '?')}{dur}")
            for w in (vd.get("warnings") or [])[:2]:
                lines.append(f"   {w}")
            if vd.get("link"):
                lines.append(f"   🔗 <a href='{vd['link']}'>Resmi kaynak</a>")
        else:
            lines.append(f"\n🛂 ⚪ Vize detayı yok ({iso2})")

    lines.append(f"\n✈️ Canlı fiyat: <code>/ara {origin} {dest} {dep}</code>")
    return "\n".join(lines)


# ============================================================
# /firsatlar — Vize emoji + tarih filtresi
# ============================================================
def cmd_firsatlar(args):
    if not os.path.exists(DEALS_CACHE_FILE):
        return "📭 Deal cache henüz oluşmadı."

    try:
        with open(DEALS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"❌ Cache okunamadı: {e}"

    # Toleranslı parsing
    deals = []
    if isinstance(data, dict):
        if "deals" in data and isinstance(data["deals"], list):
            deals = data["deals"]
        else:
            for v in data.values():
                if isinstance(v, dict) and ("origin" in v or "destination" in v):
                    deals.append(v)
    elif isinstance(data, list):
        deals = data

    if not deals:
        return "📭 Cache boş."

    # Geçmiş tarih filtresi
    today_str = datetime.now().strftime("%Y-%m-%d")
    valid = []
    for d in deals:
        if not isinstance(d, dict):
            continue
        if d.get("discount_pct") is None:
            continue
        dep = d.get("departure_date", "")
        if dep and dep < today_str:
            continue
        valid.append(d)

    if not valid:
        return "📭 Geçerli deal yok (hepsi geçmiş tarihli)."

    valid.sort(key=lambda x: -(x.get("discount_pct") or 0))
    top = valid[:10]

    lines = [f"🎯 <b>Son Swoop Fırsatları</b> ({len(valid)} aktif)\n"]
    for i, d in enumerate(top, 1):
        city = d.get("destination_city", "?")
        country = d.get("destination_country", "")
        country_str = f" ({country})" if country else ""
        price = d.get("price", 0)
        discount = d.get("discount_pct", 0)
        days = d.get("trip_days", "?")
        currency = d.get("currency", "TRY")
        price_str = f"₺{price:,}" if currency == "TRY" else f"{price} {currency}"

        # Vize emoji
        iso2 = get_iso_by_country_name(country) if country else None
        v_emoji = "⚪"
        if iso2:
            vd = get_visa_details(iso2)
            if vd:
                v_emoji = _visa_emoji(vd.get("color"))

        lines.append(f"{i}. {v_emoji} <b>IST → {city}{country_str}</b>")
        lines.append(f"   💰 {price_str} (<b>%{discount}</b>) | {days} gece")

    if len(valid) > 10:
        lines.append(f"\n... ve {len(valid) - 10} fırsat daha")

    return "\n".join(lines)


# ============================================================
# /ara — Akıllı mod algılama (3 mod tek komut)
# ============================================================
def cmd_ara(args):
    """
    /ara IST BKK 2027-02-15              → tek gün canlı arama
    /ara IST BKK 2027-02-15 ±5           → esnek (±5 gün)
    /ara IST BKK 2027-02-01 2027-04-30   → tarih aralığı
    """
    if len(args) < 3:
        return (
            "❌ Kullanım:\n"
            "<code>/ara IST BKK 2027-02-15</code> — tek gün\n"
            "<code>/ara IST BKK 2027-02-15 ±5</code> — esnek\n"
            "<code>/ara IST BKK 2027-02-01 2027-04-30</code> — aralık"
        )

    origin, dest = args[0].upper(), args[1].upper()
    arg2 = args[2]

    # Mod algıla
    if len(args) >= 4:
        arg3 = args[3]
        # Esnek mod: ±5 veya +/-5
        if arg3.startswith("±") or arg3.startswith("+/-") or arg3.startswith("+-"):
            try:
                flex = int(arg3.lstrip("±+/-"))
                return _ara_flex(origin, dest, arg2, flex)
            except ValueError:
                return "❌ Esneklik sayı olmalı: <code>±5</code> gibi"
        # Aralık mod: iki tarih
        else:
            return _ara_range(origin, dest, arg2, arg3)

    # Tek gün mod
    return _ara_single(origin, dest, arg2)


def _ara_single(origin, dest, dep):
    """Tek gün canlı fiyat."""
    MAX_ATTEMPTS, WAIT_SECONDS = 3, 20
    q = None
    last_err = "unknown"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            from viajante import RoundTrip
            trip = RoundTrip(
                origin=origin, destination=dest,
                departure_date=date.fromisoformat(dep),
                return_date=date.fromisoformat(dep) + timedelta(days=7),
                max_stops=1,
            )
            report = get_flights(trip, fetch="sweep", top=10, currency="TRY", deadline_seconds=45)
            q = report.queries[0] if report.queries else None
            if q and q.status == "ok" and q.offers:
                break
            err = getattr(q.error, "code", None) if q and q.error else None
            last_err = getattr(err, "value", str(err)) if err else "no_query"
            if "blocked" in last_err.lower() and attempt < MAX_ATTEMPTS:
                time.sleep(WAIT_SECONDS)
                continue
            else:
                return f"⚠️ Canlı fiyat çekilemedi.\nKod: {last_err}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(WAIT_SECONDS)
                continue
            return f"❌ Hata: {last_err}"
    if not q or q.status != "ok" or not q.offers:
        return (
            f"⚠️ Google BLOCKED ({MAX_ATTEMPTS} denemede)\n\n"
            f"💡 20-30 dk sonra tekrar dene veya:\n"
            f"<code>/detay {origin} {dest} {dep}</code>"
        )

    level_emoji = "⚪"
    level_text = "BİLİNMİYOR"
    if q.price_insight:
        level = q.price_insight.level
        level_emoji = {"low": "🟢", "typical": "🟡", "high": "🔴"}.get(level, "⚪")
        level_text = level.upper()

    lines = [f"✈️ <b>{origin} ⇄ {dest}</b> (7 gece gidiş-dönüş)\n📅 {dep}\n"]
    seen_airlines = set()
    display_count = 0
    for o in q.offers:
        if display_count >= 4:
            break
        if o.airline in seen_airlines:
            continue
        seen_airlines.add(o.airline)
        display_count += 1
        lines.append(f"<b>{display_count}. {o.airline}</b> — <b>{o.price_text}</b>")
        lines.append(f"   🕐 {o.departure or '?'} → {o.arrival or '?'}")
        details = flight_details(o)
        if details:
            flight_s = _fmt_duration(details["flight_mins"])
            total_s = _fmt_duration(details["total_mins"])
            if details["flight_mins"] and details["total_mins"]:
                wait_total = details["total_mins"] - details["flight_mins"]
                if wait_total > 30:
                    lines.append(f"   ⏱️ Uçuş: {flight_s} | Toplam: {total_s} (bekleme dahil)")
                else:
                    lines.append(f"   ⏱️ {total_s}")
            else:
                lines.append(f"   ⏱️ {o.duration or '?'}")
            if details["layovers"]:
                stops_label = o.stops or f"{len(details['layovers'])} aktarma"
                lay_strs = [f"{lv['airport']} ({_fmt_duration(lv['wait_mins'])})" for lv in details["layovers"]]
                lines.append(f"   ✈️ {stops_label}: {', '.join(lay_strs)}")
            else:
                lines.append(f"   ✈️ Direkt")
        else:
            lines.append(f"   ⏱️ {o.duration or '?'} | ✈️ {o.stops or '?'}")
        bag = format_baggage(o)
        if bag:
            lines.append(f"   {bag}")
        vs = format_vs_typical(o.vs_typical_pct)
        if vs:
            lines.append(f"   {vs}")
        if o.google_flights_url:
            lines.append(f"   🔗 <a href='{o.google_flights_url}'>Google Flights</a>")
        lines.append("")

    if q.price_insight:
        pi = q.price_insight
        lines.append(f"{level_emoji} <b>Seviye: {level_text}</b>")
        if pi.lowest:
            lines.append(f"   💰 En düşük: {pi.lowest:,.0f} TRY")
        if pi.typical_range:
            lo, hi = pi.typical_range
            lines.append(f"   📊 Tipik aralık: {lo:,.0f} - {hi:,.0f} TRY")

    lines.append(f"\n🛂 <b>{get_visa_by_iata(dest)}</b>")
    return "\n".join(lines)


def _ara_flex(origin, dest, dep, flex_days):
    """Esnek tarih (±N gün)."""
    if not (1 <= flex_days <= 15):
        return "❌ Esneklik 1-15 gün arasında olmalı."

    try:
        target_date = date.fromisoformat(dep)
    except ValueError:
        return "❌ Tarih formatı hatalı (YYYY-MM-DD)."

    MAX_ATTEMPTS, WAIT_SECONDS = 2, 30
    report = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            report = search_flex(
                origin=origin, destination=dest,
                around=target_date, flex_days=flex_days,
                trip="rt", nights=7, currency="TRY", max_stops=1, top=3,
            )
            priced = [(d.departure_date, d.price, d.airline, d.stops_count, d.vs_typical_pct)
                      for d in (report.days or []) if d.price]
            if priced:
                break
            if attempt < MAX_ATTEMPTS:
                time.sleep(WAIT_SECONDS)
        except Exception:
            if attempt < MAX_ATTEMPTS:
                time.sleep(WAIT_SECONDS)

    if not report or not report.days:
        return (
            f"⚠️ Esnek tarama BLOCKED\n\n"
            f"💡 Alternatifler:\n"
            f"• <code>/ara {origin} {dest} {dep}</code> (tek gün)\n"
            f"• <code>/detay {origin} {dest} {dep}</code> (cache)\n"
            f"• 20 dk sonra tekrar dene"
        )

    priced = [(d.departure_date, d.price, d.airline, d.stops_count, d.vs_typical_pct)
              for d in report.days if d.price]
    if not priced:
        return "📭 Fiyat bilgisi olan gün yok (BLOCKED)."

    priced.sort(key=lambda x: x[1])
    lines = [
        f"📅 <b>{origin} ⇄ {dest}</b> (7 gece, {dep} ±{flex_days}g)\n",
        "<b>En ucuz 3 gün:</b>",
    ]
    for i, (d_date, price, air, stops, pct) in enumerate(priced[:3], 1):
        flag = "🎯" if pct is not None and pct <= -10 else "  "
        lines.append(f"{flag} {i}. <b>{d_date}</b> — <b>{price:,.0f} TRY</b>")
        lines.append(f"     {air or '?'} | {stops} aktarma")
        vs = format_vs_typical(pct)
        if vs:
            lines.append(f"     {vs}")
    if report.typical:
        lines.append(f"\n📊 Tipik fiyat: {report.typical:,.0f} TRY")
    lines.append(f"\n🛂 <b>{get_visa_by_iata(dest)}</b>")
    return "\n".join(lines)


def _ara_range(origin, dest, start_str, end_str):
    """Tarih aralığı (ay ay tarama)."""
    try:
        start, end = date.fromisoformat(start_str), date.fromisoformat(end_str)
    except ValueError:
        return "❌ Tarih formatı hatalı (YYYY-MM-DD)."
    if end < start:
        return "❌ Bitiş tarihi başlangıçtan önce olamaz."

    windows, current = [], start
    while current <= end:
        w_end = min(current + timedelta(days=30), end)
        windows.append((current, w_end))
        current = w_end + timedelta(days=1)

    if len(windows) > 3:
        return (
            f"❌ En fazla 3 ay taranabilir.\n"
            f"İstediğin: {len(windows)} pencere.\n\n"
            f"💡 Daha kısa aralık seç veya <code>/ara {origin} {dest} {start_str} ±5</code>"
        )

    results = []
    for i, (w_start, w_end) in enumerate(windows):
        try:
            report = search_dates(
                origin=origin, destination=dest,
                start=w_start, end=w_end,
                trip="rt", nights=7, currency="TRY", max_stops=1,
            )
            if report.days:
                priced = [(d.departure_date, d.price, d.airline) for d in report.days if d.price]
                if priced:
                    priced.sort(key=lambda x: x[1])
                    best = priced[0]
                    results.append((best[0].strftime("%Y-%m"), best[1], best[0], best[2]))
        except Exception:
            pass
        if i < len(windows) - 1:
            time.sleep(25)

    if not results:
        return (
            f"⚠️ Google BLOCKED\n\n"
            f"💡 Alternatifler:\n"
            f"• 20-30 dk sonra tekrar dene\n"
            f"• <code>/detay {origin} {dest} {start_str}</code> (cache)\n"
            f"• Daha kısa aralık"
        )

    by_month = {}
    for m, p, d, a in results:
        by_month.setdefault(m, []).append((p, d, a))

    lines = [f"📅 <b>{origin} ⇄ {dest}</b> (7 gece gidiş-dönüş)", f"({start_str} — {end_str})\n"]
    overall_best = None
    month_names = {
        "01": "Ocak", "02": "Şubat", "03": "Mart", "04": "Nisan",
        "05": "Mayıs", "06": "Haziran", "07": "Temmuz", "08": "Ağustos",
        "09": "Eylül", "10": "Ekim", "11": "Kasım", "12": "Aralık",
    }
    for month_str in sorted(by_month.keys()):
        entries = sorted(by_month[month_str], key=lambda x: x[0])
        bp, bd, ba = entries[0]
        y, m = month_str.split("-")
        m_label = f"{month_names.get(m, m)} {y}"
        lines.append(f"🗓️ <b>{m_label}</b>: {bp:,.0f} TRY\n   📍 {bd} | {ba}")
        if overall_best is None or bp < overall_best[0]:
            overall_best = (bp, m_label, bd)

    # Eksik aylar kontrolü
    expected_months = set()
    for w_start, w_end in windows:
        cur = w_start
        while cur <= w_end:
            expected_months.add(cur.strftime("%Y-%m"))
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1, day=1)
            else:
                cur = cur.replace(month=cur.month + 1, day=1)
    got_months = {m for m, _, _, _ in results}
    missing = expected_months - got_months

    if overall_best:
        lines.append(
            f"\n💡 <b>En ucuz: {overall_best[1]}</b> "
            f"({overall_best[0]:,.0f} TRY, {overall_best[2]})"
        )
    if missing:
        missing_str = ", ".join(sorted(missing))
        lines.append(f"\n⚠️ Eksik aylar (BLOCKED): {missing_str}")

    return "\n".join(lines)


# ============================================================
# /yardim
# ============================================================
def cmd_help():
    return (
        "🤖 <b>Uçuş Fırsat Avcısı</b>\n\n"
        "📊 <b>/detay</b> <code>IST BKK 2027-02-15</code>\n"
        "   Geçmiş + trend + vize\n\n"
        "✈️ <b>/ara</b> <code>IST BKK 2027-02-15</code>\n"
        "   Canlı fiyat (tek gün)\n"
        "   <code>/ara IST BKK 2027-02-15 ±5</code> — esnek\n"
        "   <code>/ara IST BKK 2027-02-01 2027-04-30</code> — aralık\n\n"
        "🛂 <b>/vize</b> <code>TH</code> veya <code>BKK</code>\n"
        "🎯 <b>/firsatlar</b> — son Swoop fırsatları"
    )


# ============================================================
# KOMUT YÖNLENDİRİCİ
# ============================================================
def process_command(text):
    parts = text.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower().lstrip("/")
    args = parts[1:]
    handlers = {
        "yardim": cmd_help, "help": cmd_help, "start": cmd_help,
        "detay": lambda: cmd_detay(args), "detail": lambda: cmd_detay(args),
        "vize": lambda: cmd_vize(args), "visa": lambda: cmd_vize(args),
        "firsatlar": lambda: cmd_firsatlar(args), "deals": lambda: cmd_firsatlar(args),
        "ara": lambda: cmd_ara(args), "search": lambda: cmd_ara(args),
    }
    handler = handlers.get(cmd)
    if not handler:
        return f"❓ Bilinmeyen komut: /{cmd}\n<code>/yardim</code> yazın."
    return handler()


# ============================================================
# MAIN
# ============================================================
def main():
    print("🎯 Bot başlıyor...", flush=True)
    state = load_state()
    offset = state.get("last_update_id", 0) + 1
    print(f"🔄 Dinleme (offset: {offset})", flush=True)

    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

    try:
        r = requests.get(url, params={"offset": offset, "timeout": 55, "limit": 10}, timeout=65)
        updates = r.json().get("result", [])
        print(f"📨 Yeni mesaj: {len(updates)}", flush=True)

        if not updates:
            print("💤 Yeni mesaj yok.", flush=True)
            return

        processed_texts = set()

        for upd in updates:
            state["last_update_id"] = upd["update_id"]
            msg = upd.get("message", {})

            if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                print("⚠️ Yabancı chat atlandı", flush=True)
                continue

            text = msg.get("text", "")
            if text.startswith("/"):
                if text in processed_texts:
                    continue
                processed_texts.add(text)
                print(f"💬 {text}", flush=True)
                reply = process_command(text)
                if reply:
                    send_message(reply)

        save_state(state)
        print(f"💾 State: id={state['last_update_id']}", flush=True)

    except Exception as e:
        print(f"❌ Bot hatası: {e}", flush=True)


if __name__ == "__main__":
    main()
