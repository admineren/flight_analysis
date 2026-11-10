import sys
print("🚀 Telegram Bot başlıyor...", flush=True)

import os
import json
import time
import requests
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from visa_helper import get_visa_by_iata

print("📦 Kütüphaneler yükleniyor (viajante)...", flush=True)
try:
    from viajante import get_flights, search_flex, search_dates
    print("✅ Viajante hazır.", flush=True)
except Exception as e:
    print(f"❌ Viajante yüklenemedi: {e}", flush=True)
    sys.exit(1)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_READ_TOKEN = os.environ.get("TB_READ_TOKEN")

STATE_FILE = os.path.join("data", "telegram_state.json")

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
    return {"last_update_id": 0}

def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ State kaydedilemedi: {e}", flush=True)

# ============================================================
# TELEGRAM
# ============================================================
def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"⚠️ Telegram mesaj hatası: {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"❌ Mesaj gönderilemedi: {e}", flush=True)

# ============================================================
# TINYBIRD SORGULARI
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

# ============================================================
# ZENGİN VERİ YARDIMCILARI
# ============================================================
def format_vs_typical(pct):
    if pct is None: return ""
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
    """Segment için timezone-aware datetime döndürür."""
    if is_arrival:
        d, t, tz = seg.arrival_date, seg.arrival, seg.arrival_timezone
    else:
        d, t, tz = seg.departure_date, seg.departure, seg.departure_timezone
    if not (d and t and tz):
        return None
    try:
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
    """Gidiş yönü için: sadece uçuş süresi, toplam süre, aktarma detayları."""
    if not offer.legs:
        return None
    
    outbound = offer.legs[0]
    segs = outbound.segments or ()
    if not segs:
        return None
    
    # Sadece uçakta geçen süre (segment süreleri toplamı)
    flight_mins = sum((s.duration_minutes or 0) for s in segs) or None
    
    # Toplam süre (kalkış → son varış, bekleme dahil)
    first_dep = _seg_dt(segs[0], is_arrival=False)
    last_arr = _seg_dt(segs[-1], is_arrival=True)
    total_mins = None
    if first_dep and last_arr:
        total_mins = int((last_arr - first_dep).total_seconds() // 60)
    
    # Aktarmalar
    layovers = []
    for i in range(len(segs) - 1):
        cur_arr = _seg_dt(segs[i], is_arrival=True)
        nxt_dep = _seg_dt(segs[i + 1], is_arrival=False)
        wait_mins = None
        if cur_arr and nxt_dep:
            wait_mins = int((nxt_dep - cur_arr).total_seconds() // 60)
        layovers.append({
            "airport": segs[i].destination or "?",
            "wait_mins": wait_mins,
        })
    
    return {
        "flight_mins": flight_mins,
        "total_mins": total_mins,
        "layovers": layovers,
    }

# ============================================================
# KOMUTLAR
# ============================================================
def cmd_help():
    return (
        "🤖 <b>Uçuş Fırsat Avcısı</b>\n\n"
        "📊 <b>/gecmis</b> <code>IST BKK 2027-02-15</code>\n"
        "   Tinybird'deki son kaydı gösterir\n\n"
        "📈 <b>/trend</b> <code>IST BKK 2027-02-15 [gün]</code>\n"
        "   Son N günün en düşük/ortalama fiyatı\n\n"
        "✈️ <b>/ara</b> <code>IST BKK 2027-02-15</code>\n"
        "   Anlık canlı fiyat, saat, bagaj, aktarma\n\n"
        "📅 <b>/esnek</b> <code>IST BKK 2027-02-15 5</code>\n"
        "   ±5 gün tarama, en ucuz günler\n\n"
        "🗓️ <b>/takvim</b> <code>IST BKK 2027-02-01 2027-04-30</code>\n"
        "   Aylık tarama, hangi ay en ucuz\n\n"
        "💡 Örnek: <code>/takvim IST BKK 2027-03-01 2027-05-31</code>"
    )

def cmd_gecmis(args):
    if len(args) < 3: return "❌ Kullanım: <code>/gecmis IST BKK 2027-02-15</code>"
    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    
    result = tb_latest_price(origin, dest, dep)
    if not result: return f"📭 <b>{origin} → {dest}</b> ({dep}) için kayıtlı veri yok."

    price = result.get("price", 0)
    airline = result.get("airline", "?")
    level = result.get("price_level", "unknown")
    stops = result.get("stops", "?")
    duration = result.get("duration_hours", 0)
    observed = result.get("observed_at", "").replace("T", " ").replace("Z", "")

    level_emoji = {"low": "🟢", "typical": "🟡", "high": "🔴"}.get(level, "⚪")

    return (
        f"📊 <b>{origin} → {dest}</b> ({dep})\n\n"
        f"💰 Son kayıtlı: <b>{price:,.0f} TRY</b>\n"
        f"🛫 {airline} | {stops} aktarma | {duration:.1f}s\n"
        f"{level_emoji} Seviye: {level.upper()}\n"
        f"🕐 {observed} (UTC)"
    )

def cmd_trend(args):
    if len(args) < 3: return "❌ Kullanım: <code>/trend IST BKK 2027-02-15 [7]</code>"
    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    days = int(args[3]) if len(args) > 3 and args[3].isdigit() else 7

    result = tb_trend(origin, dest, dep, days)
    if not result or not result.get("observation_count"):
        return f"📭 <b>{origin} → {dest}</b> için son {days} günde kayıt yok."

    count = result.get("observation_count", 0)
    lowest = result.get("lowest_price", 0)
    highest = result.get("highest_price", 0)
    avg = result.get("avg_price", 0)

    return (
        f"📈 <b>{origin} → {dest}</b> ({dep})\n"
        f"📅 Son {days} gün ({count} gözlem)\n\n"
        f"🟢 En düşük: <b>{lowest:,.0f} TRY</b>\n"
        f"🔴 En yüksek: {highest:,.0f} TRY\n"
        f"📊 Ortalama: {avg:,.0f} TRY"
    )

def cmd_ara(args):
    if len(args) < 3: return "❌ Kullanım: <code>/ara IST BKK 2027-02-15</code>"
    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    
    MAX_ATTEMPTS = 3
    WAIT_SECONDS = 20
    
    q = None
    report = None
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
                break  # ✅ Başarılı
            
            err = getattr(q.error, "code", None) if q and q.error else None
            last_err = getattr(err, "value", str(err)) if err else "no_query"
            
            if "blocked" in last_err.lower() and attempt < MAX_ATTEMPTS:
                print(f"  ⚠️ BLOCKED (deneme {attempt}/{MAX_ATTEMPTS}), {WAIT_SECONDS}s bekleniyor...", flush=True)
                time.sleep(WAIT_SECONDS)
                continue
            else:
                return f"⚠️ Canlı fiyat çekilemedi.\nKod: {last_err}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt < MAX_ATTEMPTS:
                print(f"  ⚠️ Exception (deneme {attempt}/{MAX_ATTEMPTS}): {last_err}, {WAIT_SECONDS}s...", flush=True)
                time.sleep(WAIT_SECONDS)
                continue
            return f"❌ Hata: {last_err}"
    
    if not q or q.status != "ok" or not q.offers:
        return f"⚠️ {MAX_ATTEMPTS} denemede de Google BLOCKED.\n15-20 dakika sonra tekrar deneyin.\nSon hata: {last_err}"
    
    # --- Başarılı, çıktıyı üret ---
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
        if display_count >= 4: break
        if o.airline in seen_airlines: continue
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
                lay_strs = []
                for lv in details["layovers"]:
                    wait = _fmt_duration(lv["wait_mins"])
                    lay_strs.append(f"{lv['airport']} ({wait})")
                lines.append(f"   ✈️ {stops_label}: {', '.join(lay_strs)}")
            else:
                lines.append(f"   ✈️ Direkt")
        else:
            lines.append(f"   ⏱️ {o.duration or '?'} | ✈️ {o.stops or '?'}")

        bag = format_baggage(o)
        if bag: lines.append(f"   {bag}")
        vs = format_vs_typical(o.vs_typical_pct)
        if vs: lines.append(f"   {vs}")
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

def cmd_esnek(args):
    if len(args) < 4: return "❌ Kullanım: <code>/esnek IST BKK 2027-02-15 5</code>"
    origin, dest, dep_str, flex_str = args[0].upper(), args[1].upper(), args[2], args[3]
    
    try:
        flex_days = int(flex_str)
        if not (1 <= flex_days <= 15): return "❌ Esneklik 1-15 gün arasında olmalı."
        target_date = date.fromisoformat(dep_str)
    except ValueError:
        return "❌ Tarih veya gün formatı hatalı."

    MAX_ATTEMPTS = 3
    WAIT_SECONDS = 20
    report = None
    
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            report = search_flex(
                origin=origin, destination=dest,
                around=target_date, flex_days=flex_days,
                trip="rt", nights=7,
                currency="TRY", max_stops=1, top=3
            )
            priced = [(d.departure_date, d.price, d.airline, d.stops_count, d.vs_typical_pct)
                      for d in (report.days or []) if d.price]
            if priced:
                break  # ✅ Başarılı
            # priced boş -> BLOCKED olabilir, retry
            if attempt < MAX_ATTEMPTS:
                print(f"  ⚠️ Esnek: fiyatlı gün yok (deneme {attempt}/{MAX_ATTEMPTS}), {WAIT_SECONDS}s...", flush=True)
                time.sleep(WAIT_SECONDS)
        except Exception as e:
            print(f"  ⚠️ Esnek exception (deneme {attempt}/{MAX_ATTEMPTS}): {str(e)[:80]}", flush=True)
            if attempt < MAX_ATTEMPTS:
                time.sleep(WAIT_SECONDS)

    if not report or not report.days:
        return "⚠️ Esnek tarama sonuç vermedi (Google BLOCKED). 15-20 dakika sonra tekrar deneyin."

    priced = [(d.departure_date, d.price, d.airline, d.stops_count, d.vs_typical_pct)
              for d in report.days if d.price]
    if not priced:
        return "📭 Fiyat bilgisi olan gün yok (BLOCKED olabilir). 15-20 dakika sonra deneyin."
    
    priced.sort(key=lambda x: x[1])

    lines = [f"📅 <b>{origin} ⇄ {dest}</b> (7 gece gidiş-dönüş, {dep_str} ±{flex_days}g)\n", "<b>En ucuz 3 gün:</b>"]
    for i, (d_date, price, air, stops, pct) in enumerate(priced[:3], 1):
        flag = "🎯" if pct is not None and pct <= -10 else "  "
        lines.append(f"{flag} {i}. <b>{d_date}</b> — <b>{price:,.0f} TRY</b>")
        lines.append(f"     {air or '?'} | {stops} aktarma")
        vs = format_vs_typical(pct)
        if vs: lines.append(f"     {vs}")

    if report.typical:
        lines.append(f"\n📊 Tipik fiyat: {report.typical:,.0f} TRY")
    
    lines.append(f"\n🛂 <b>{get_visa_by_iata(dest)}</b>")
    return "\n".join(lines)


def cmd_takvim(args):
    if len(args) < 4: return "❌ Kullanım: <code>/takvim IST BKK 2027-02-01 2027-04-30</code>"
    origin, dest, start_str, end_str = args[0].upper(), args[1].upper(), args[2], args[3]
    
    try:
        start, end = date.fromisoformat(start_str), date.fromisoformat(end_str)
    except ValueError:
        return "❌ Tarih formatı hatalı. YYYY-MM-DD kullanın."
    if end < start: return "❌ Bitiş tarihi başlangıçtan önce olamaz."
    
    windows, current = [], start
    while current <= end:
        w_end = min(current + timedelta(days=30), end)
        windows.append((current, w_end))
        current = w_end + timedelta(days=1)
    
    if len(windows) > 6: return "❌ En fazla 6 ay (6 dilim) tarayabilirsiniz."
    
    results = []
    for i, (w_start, w_end) in enumerate(windows):
        print(f"🔍 Dilim {i+1}/{len(windows)}: {w_start} → {w_end}", flush=True)
        try:
            # Gidiş-dönüş (7 gece) aylık tarama
            report = search_dates(
                origin=origin, destination=dest,
                start=w_start, end=w_end,
                trip="rt", nights=7,
                currency="TRY", max_stops=1
            )
            if report.days:
                priced = [(d.departure_date, d.price, d.airline) for d in report.days if d.price]
                if priced:
                    priced.sort(key=lambda x: x[1])
                    best = priced[0]
                    results.append((best[0].strftime("%Y-%m"), best[1], best[0], best[2]))
        except Exception as e:
            print(f"  ❌ Hata: {str(e)[:100]}", flush=True)
        if i < len(windows) - 1:
            print(f"  ⏳ 25 saniye bekleniyor (rate limit)...", flush=True)
            time.sleep(25) # Bekleme süresini 25'e çıkardık
    
    if not results:
        return (
            "⚠️ Google rate limit (BLOCKED) nedeniyle veri alınamadı.\n\n"
            "💡 Öneriler:\n"
            "• 15-20 dakika sonra tekrar deneyin\n"
            "• Daha kısa aralık seçin (ör. tek ay: <code>/takvim IST BKK 2027-02-01 2027-02-28</code>)\n"
            "• Veya <code>/esnek IST BKK 2027-02-15 7</code> ile daha küçük pencere deneyin"
        )

    by_month = defaultdict(list)
    for m, p, d, a in results: by_month[m].append((p, d, a))
    
    lines = [f"📅 <b>{origin} ⇄ {dest}</b> (7 gece gidiş-dönüş)", f"({start_str} — {end_str})\n"]
    overall_best = None
    month_names = {"01":"Ocak","02":"Şubat","03":"Mart","04":"Nisan","05":"Mayıs","06":"Haziran","07":"Temmuz","08":"Ağustos","09":"Eylül","10":"Ekim","11":"Kasım","12":"Aralık"}

    for month_str in sorted(by_month.keys()):
        entries = sorted(by_month[month_str], key=lambda x: x[0])
        bp, bd, ba = entries[0]
        y, m = month_str.split("-")
        m_label = f"{month_names.get(m, m)} {y}"
        lines.append(f"🗓️ <b>{m_label}</b>: {bp:,.0f} TRY\n   📍 {bd} | {ba}")
        if overall_best is None or bp < overall_best[0]: overall_best = (bp, m_label, bd)
    
    if overall_best: lines.append(f"\n💡 <b>En ucuz: {overall_best[1]}</b> ({overall_best[0]:,.0f} TRY, {overall_best[2]})")
    return "\n".join(lines)

# ============================================================
# ROUTER
# ============================================================
def process_command(text):
    parts = text.strip().split()
    if not parts: return None
    cmd = parts[0].lower().lstrip("/")
    args = parts[1:]
    
    handlers = {
        "yardim": cmd_help, "help": cmd_help, "start": cmd_help,
        "gecmis": lambda: cmd_gecmis(args), "history": lambda: cmd_gecmis(args),
        "trend": lambda: cmd_trend(args),
        "ara": lambda: cmd_ara(args), "search": lambda: cmd_ara(args),
        "esnek": lambda: cmd_esnek(args), "flex": lambda: cmd_esnek(args),
        "takvim": lambda: cmd_takvim(args), "calendar": lambda: cmd_takvim(args),
    }
    handler = handlers.get(cmd)
    if not handler: return f"❓ Bilinmeyen komut: /{cmd}\n<code>/yardim</code> yazın."
    return handler()

# ============================================================
# MAIN — Long Polling
# ============================================================
def main():
    state = load_state()
    offset = state.get("last_update_id", 0) + 1
    print(f"🔄 Dinleme başladı (offset: {offset})", flush=True)

    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

    try:
        r = requests.get(
            url,
            params={"offset": offset, "timeout": 55, "limit": 10},
            timeout=65,
        )
        updates = r.json().get("result", [])
        print(f"📨 Yeni mesaj: {len(updates)}", flush=True)

        if not updates:
            print("💤 Yeni mesaj yok.", flush=True)
            return

        for upd in updates:
            state["last_update_id"] = upd["update_id"]
            msg = upd.get("message", {})
            
            if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                print(f"⚠️ Yabancı chat atlandı", flush=True)
                continue

            text = msg.get("text", "")
            if text.startswith("/"):
                print(f"💬 Komut: {text}", flush=True)
                reply = process_command(text)
                if reply:
                    send_message(reply)

        save_state(state)
        print(f"💾 State kaydedildi (son id: {state['last_update_id']})", flush=True)

    except Exception as e:
        print(f"❌ Bot hatası: {e}", flush=True)
