import sys
print("🚀 Telegram Bot başlıyor...", flush=True)

import os
import json
import time
import requests
from datetime import datetime, timezone, date, timedelta
from collections import defaultdict

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

STATE_FILE = "telegram_state.json"

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

def format_layovers(offer):
    if not getattr(offer, "layover_city", None):
        return ""
    hours = getattr(offer, "layover_hours", 0) or 0
    return f"📍 {offer.layover_city} ({hours:.1f}s bekleme)"

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
    
    try:
        report = get_flights(f"{origin}-{dest}:{dep}", fetch="sweep", top=3, currency="TRY", deadline_seconds=45)
        q = report.queries[0] if report.queries else None
        
        if not q or q.status != "ok" or not q.offers:
            err = getattr(q.error, "code", "unknown") if q and q.error else "no_query"
            return f"⚠️ Canlı fiyat çekilemedi (Google BLOCKED olabilir).\nKod: {err}"

        level_emoji = "⚪"
        level_text = "BİLİNMİYOR"
        if q.price_insight:
            level = q.price_insight.level
            level_emoji = {"low": "🟢", "typical": "🟡", "high": "🔴"}.get(level, "⚪")
            level_text = level.upper()

        lines = [f"✈️ <b>{origin} → {dest}</b> ({dep})\n"]

        for i, o in enumerate(q.offers[:3], 1):
            lines.append(f"<b>{i}. {o.airline}</b> — <b>{o.price_text}</b>")
            dep_t, arr_t, dur = o.departure or "?", o.arrival or "?", o.duration or "?"
            lines.append(f"   🕐 {dep_t} → {arr_t} | {dur}")

            stops_label = o.stops or "?"
            layover_info = format_layovers(o)
            lines.append(f"   ✈️ {stops_label}" + (f" | {layover_info}" if layover_info else ""))

            bag = format_baggage(o)
            if bag: lines.append(f"   {bag}")

            vs = format_vs_typical(o.vs_typical_pct)
            if vs: lines.append(f"   {vs}")

            if o.google_flights_url:
                lines.append(f"   🔗 <a href='{o.google_flights_url}'>Google Flights'ta Aç</a>")
            lines.append("")

        if q.price_insight:
            pi = q.price_insight
            lines.append(f"{level_emoji} <b>Seviye: {level_text}</b>")
            if pi.lowest: lines.append(f"   💰 En düşük: {pi.lowest:,.0f} TRY")
            if pi.typical_range:
                lo, hi = pi.typical_range
                lines.append(f"   📊 Tipik aralık: {lo:,.0f} - {hi:,.0f} TRY")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Hata: {str(e)[:120]}"

def cmd_esnek(args):
    if len(args) < 4: return "❌ Kullanım: <code>/esnek IST BKK 2027-02-15 5</code>"
    origin, dest, dep_str, flex_str = args[0].upper(), args[1].upper(), args[2], args[3]
    
    try:
        flex_days = int(flex_str)
        if not (1 <= flex_days <= 15): return "❌ Esneklik 1-15 gün arasında olmalı."
        target_date = date.fromisoformat(dep_str)
    except ValueError:
        return "❌ Tarih veya gün formatı hatalı."

    try:
        report = search_flex(origin=origin, destination=dest, around=target_date, flex_days=flex_days, currency="TRY", max_stops=1, top=3)
        if not report.days: return "⚠️ Esnek tarama sonuç vermedi (BLOCKED olabilir)."

        priced = [(d.departure_date, d.price, d.airline, d.stops_count, d.vs_typical_pct) for d in report.days if d.price]
        if not priced: return "📭 Fiyat bilgisi olan gün yok."
        priced.sort(key=lambda x: x[1])

        lines = [f"📅 <b>{origin} → {dest}</b> ({dep_str} ±{flex_days}g)\n", "<b>En ucuz 3 gün:</b>"]
        for i, (d_date, price, air, stops, pct) in enumerate(priced[:3], 1):
            flag = "🎯" if pct is not None and pct <= -10 else "  "
            lines.append(f"{flag} {i}. <b>{d_date}</b> — <b>{price:,.0f} TRY</b>")
            lines.append(f"     {air or '?'} | {stops} aktarma")
            vs = format_vs_typical(pct)
            if vs: lines.append(f"     {vs}")

        if report.typical: lines.append(f"\n📊 Tipik fiyat: {report.typical:,.0f} TRY")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Esnek tarama hatası: {str(e)[:120]}"

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
            report = search_dates(origin=origin, destination=dest, start=w_start, end=w_end, currency="TRY", nights=7, max_stops=1)
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
            time.sleep(25)  # 10 → 25 saniye
    
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
    
    lines = [f"📅 <b>{origin} → {dest}</b>", f"({start_str} — {end_str})\n"]
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
    
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", params={"offset": offset, "timeout": 55}, timeout=65)
        updates = r.json().get("result", [])
        print(f"📨 Yeni mesaj: {len(updates)}", flush=True)
        
        if not updates:
            print("💤 Yeni mesaj yok.", flush=True)
            return

        for upd in updates:
            state["last_update_id"] = upd["update_id"]
            msg = upd.get("message", {})
            
            if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                continue # Yabancı mesajları yoksay
            
            text = msg.get("text", "")
            if text.startswith("/"):
                print(f"💬 Komut: {text}", flush=True)
                reply = process_command(text)
                if reply: send_message(reply)
                
        save_state(state)
    except Exception as e:
        print(f"❌ Bot hatası: {e}", flush=True)

if __name__ == "__main__":
    main()
