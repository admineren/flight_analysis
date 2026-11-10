import sys
print("🚀 Telegram Bot başlıyor...", flush=True)

import os
import json
import requests
from datetime import date

print("📦 Kütüphaneler yükleniyor (viajante)...", flush=True)
try:
    from viajante import get_flights, search_flex
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
        print(f"📤 Mesaj gönderiliyor...", flush=True)
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
        print(f"📬 Telegram yanıtı: {r.status_code}", flush=True)
        if r.status_code != 200:
            print(f"   → {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"❌ Mesaj gönderilemedi: {e}", flush=True)


# ============================================================
# TINYBIRD SORGULARI
# ============================================================
def tb_latest_price(origin, dest, dep_date):
    """En son kaydedilen fiyat."""
    url = f"{TB_HOST}/v0/pipes/latest_price.json"
    headers = {"Authorization": f"Bearer {TB_READ_TOKEN}"}
    params = {"origin": origin, "destination": dest, "departure_date": dep_date}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            return data[0] if data else None
    except Exception as e:
        print(f"❌ TB latest_price hatası: {e}", flush=True)
    return None


def tb_trend(origin, dest, dep_date, days=7):
    """Son N günün fiyat istatistikleri."""
    url = f"{TB_HOST}/v0/pipes/price_history_trend.json"
    headers = {"Authorization": f"Bearer {TB_READ_TOKEN}"}
    params = {
        "origin": origin,
        "destination": dest,
        "departure_date": dep_date,
        "days": days,
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            return data[0] if data else None
    except Exception as e:
        print(f"❌ TB trend hatası: {e}", flush=True)
    return None


# ============================================================
# KOMUTLAR
# ============================================================
def cmd_gecmis(args):
    if len(args) < 3:
        return "❌ Kullanım: <code>/gecmis IST BKK 2027-02-15</code>"

    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    result = tb_latest_price(origin, dest, dep)
    if not result:
        return f"📭 <b>{origin} → {dest}</b> ({dep}) için kayıtlı veri yok."

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
    if len(args) < 3:
        return "❌ Kullanım: <code>/trend IST BKK 2027-02-15 [7]</code>"

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
    if len(args) < 3:
        return "❌ Kullanım: <code>/ara IST BKK 2027-02-15</code>"

    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    try:
        print(f"🔍 Canlı arama: {origin}-{dest} {dep}", flush=True)
        report = get_flights(
            f"{origin}-{dest}:{dep}",
            fetch="sweep", top=3, currency="TRY", deadline_seconds=45,
        )
        q = report.queries[0] if report.queries else None
        if not q or q.status != "ok" or not q.offers:
            err = getattr(q.error, "code", "unknown") if q and q.error else "no_query"
            return f"⚠️ Canlı fiyat çekilemedi.\nKod: {err}"

        lines = [f"✈️ <b>{origin} → {dest}</b> ({dep})\n"]
        for i, o in enumerate(q.offers[:3], 1):
            bag = " ⚠️" if o.needs_bag_verify else ""
            lines.append(
                f"{i}. <b>{o.airline}</b> — {o.price_text}{bag}\n"
                f"   {o.duration or '?'} | {o.stops or '?'}"
            )

        if q.price_insight:
            pi = q.price_insight
            lines.append(f"\n📊 Seviye: <b>{pi.level.upper()}</b>")
            if pi.lowest:
                lines.append(f"   En düşük: {pi.lowest:,.0f} TRY")
            if pi.typical_range:
                lo, hi = pi.typical_range
                lines.append(f"   Tipik: {lo:,.0f} - {hi:,.0f} TRY")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Hata: {str(e)[:120]}"


def cmd_esnek(args):
    if len(args) < 4:
        return (
            "❌ Kullanım: <code>/esnek IST BKK 2027-02-15 5</code>\n"
            "(5 = ±5 gün esneklik)"
        )

    origin, dest, dep_str, flex_str = args[0].upper(), args[1].upper(), args[2], args[3]

    try:
        flex_days = int(flex_str)
        if flex_days < 1 or flex_days > 15:
            return "❌ Esneklik 1-15 gün arasında olmalı."
        target_date = date.fromisoformat(dep_str)
    except ValueError:
        return "❌ Tarih (YYYY-MM-DD) veya gün (sayı) formatı hatalı."

    try:
        print(f"🔍 Esnek tarama: {origin}-{dest} ±{flex_days}g", flush=True)
        report = search_flex(
            origin=origin,
            destination=dest,
            around=target_date,
            flex_days=flex_days,
            currency="TRY",
            max_stops=1,
            top=3,
        )

        if not report.days:
            return "⚠️ Esnek tarama sonuç vermedi (BLOCKED olabilir)."

        priced = [
            (d.departure_date, d.price, d.airline, d.stops_count, d.vs_typical_pct)
            for d in report.days
            if d.price
        ]
        if not priced:
            return "📭 Fiyat bilgisi olan gün yok."

        priced.sort(key=lambda x: x[1])

        lines = [f"📅 <b>{origin} → {dest}</b> ({dep_str} ±{flex_days}g)\n"]
        lines.append("<b>En ucuz 3 gün:</b>")
        for i, (d_date, price, air, stops, pct) in enumerate(priced[:3], 1):
            flag = " 🎯" if pct is not None and pct <= -10 else ""
            lines.append(
                f"{i}. {d_date} — <b>{price:,.0f} TRY</b>{flag}\n"
                f"   {air or '?'} | {stops if stops is not None else '?'} aktarma"
            )

        if report.typical:
            lines.append(f"\n📊 Tipik: {report.typical:,.0f} TRY")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Esnek tarama hatası: {str(e)[:120]}"


def cmd_help():
    return (
        "🤖 <b>Uçuş Fırsat Avcısı</b>\n\n"
        "📊 <b>/gecmis</b> <code>IST BKK 2027-02-15</code>\n"
        "   <i>Tinybird'deki son kaydı gösterir</i>\n\n"
        "📈 <b>/trend</b> <code>IST BKK 2027-02-15 [gün]</code>\n"
        "   <i>Son N günün en düşük/en yüksek/ortalama fiyatı</i>\n\n"
        "✈️ <b>/ara</b> <code>IST BKK 2027-02-15</code>\n"
        "   <i>Anlık canlı fiyat (Google Flights)</i>\n\n"
        "📅 <b>/esnek</b> <code>IST BKK 2027-02-15 5</code>\n"
        "   <i>±5 gün esnek tarama, en ucuz günler</i>\n\n"
        "💡 Örnek: <code>/esnek IST BKK 2027-02-15 7</code>"
    )


# ============================================================
# ROUTER
# ============================================================
def process_command(text):
    parts = text.strip().split()
    if not parts:
        return None

    cmd = parts[0].lower().lstrip("/")
    args = parts[1:]

    handlers = {
        "yardim": cmd_help,
        "help": cmd_help,
        "start": cmd_help,
        "gecmis": lambda: cmd_gecmis(args),
        "history": lambda: cmd_gecmis(args),
        "trend": lambda: cmd_trend(args),
        "ara": lambda: cmd_ara(args),
        "search": lambda: cmd_ara(args),
        "esnek": lambda: cmd_esnek(args),
        "flex": lambda: cmd_esnek(args),
    }

    handler = handlers.get(cmd)
    if not handler:
        return f"❓ Bilinmeyen komut: /{cmd}\n<code>/yardim</code> yazın."
    return handler()


# ============================================================
# MAIN — Long Polling
# ============================================================
def main():
    state = load_state()
    offset = state.get("last_update_id", 0) + 1
    print(f"🔄 Dinleme başladı (offset: {offset}, timeout: 55s)", flush=True)

    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

    try:
        r = requests.get(
            url,
            params={"offset": offset, "timeout": 55},
            timeout=65,
        )
        print(f"📥 Telegram yanıtı: {r.status_code}", flush=True)
        updates = r.json().get("result", [])
        print(f"📨 Yeni mesaj sayısı: {len(updates)}", flush=True)

        if not updates:
            print("💤 Yeni mesaj yok.", flush=True)
            return

        for upd in updates:
            state["last_update_id"] = upd["update_id"]
            msg = upd.get("message", {})

            incoming_chat = str(msg.get("chat", {}).get("id"))
            if incoming_chat != str(CHAT_ID):
                print(f"⚠️ Yabancı chat_id: {incoming_chat}", flush=True)
                continue

            text = msg.get("text", "")
            print(f"💬 Komut: {text}", flush=True)

            if text.startswith("/"):
                reply = process_command(text)
                if reply:
                    send_message(reply)

        save_state(state)
        print(f"💾 State kaydedildi (son id: {state['last_update_id']})", flush=True)

    except Exception as e:
        print(f"❌ Bot hatası: {e}", flush=True)


if __name__ == "__main__":
    main()
