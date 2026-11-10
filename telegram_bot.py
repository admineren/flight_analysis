import os
import json
import requests
from datetime import datetime
from viajante import get_flights, RoundTrip
from datetime import date

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_READ_TOKEN = os.environ["TB_READ_TOKEN"]

STATE_FILE = "telegram_state.json"

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        print(f"Mesaj gönderilemedi: {e}")

def query_tinybird_latest(origin, dest, dep_date):
    """Tinybird'deki latest_price endpoint'ine sorar."""
    url = f"{TB_HOST}/v0/pipes/latest_price.json"
    headers = {"Authorization": f"Bearer {TB_READ_TOKEN}"}
    params = {"origin": origin, "destination": dest, "departure_date": dep_date}
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                return data[0] # En son kaydı döndür
    except Exception as e:
        print(f"Tinybird okuma hatası: {e}")
    return None

def cmd_gecmis(args):
    if len(args) < 3:
        return "❌ Kullanım: <code>/gecmis IST BKK 2027-02-15</code>"
    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    
    result = query_tinybird_latest(origin, dest, dep)
    if not result:
        return f"📭 Tinybird'de <b>{origin} → {dest}</b> ({dep}) için henüz kayıtlı veri yok."
        
    price = result.get("price")
    airline = result.get("airline")
    observed = result.get("observed_at", "").replace("T", " ").replace("Z", "")
    
    return (
        f"📊 <b>{origin} → {dest}</b> ({dep})\n\n"
        f"💰 Son kaydedilen fiyat: <b>{price:,.0f} TRY</b>\n"
        f"🛫 Havayolu: {airline}\n"
        f"🕐 Gözlem zamanı: {observed} (UTC)"
    )

def cmd_ara(args):
    if len(args) < 3:
        return "❌ Kullanım: <code>/ara IST BKK 2027-02-15</code>"
    origin, dest, dep = args[0].upper(), args[1].upper(), args[2]
    
    trip = RoundTrip(
        origin=origin, destination=dest,
        departure_date=date.fromisoformat(dep),
        return_date=date.fromisoformat(dep), # Geçici, tek yön gibi davranır
        max_stops=1,
    )
    
    try:
        # Sadece anlık fiyatı çek (canlı)
        report = get_flights(f"{origin}-{dest}:{dep}", fetch="sweep", top=1, currency="TRY", deadline_seconds=30)
        if report.queries and report.queries[0].status == "ok" and report.queries[0].offers:
            o = report.queries[0].offers[0]
            return f"✈️ <b>{origin} → {dest}</b> ({dep})\n\n💰 Canlı Fiyat: <b>{o.price:,.0f} TRY</b>\n🛫 {o.airline} | {o.duration} | {o.stops}"
        else:
            err = getattr(report.queries[0].error, 'code', 'unknown') if report.queries else 'no_query'
            return f"⚠️ Şu an canlı fiyat çekilemedi (Google BLOCKED veya sonuç yok).\nKod: {err}"
    except Exception as e:
        return f"❌ Hata: {str(e)[:100]}"

def process_command(text):
    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/")
    args = parts[1:]
    
    if cmd in ["yardim", "help", "start"]:
        return (
            "🤖 <b>Komutlar</b>\n\n"
            "📊 <b>/gecmis</b> <code>ORIGIN DEST DATE</code>\n"
            "   <i>Tinybird'deki son kaydı gösterir.</i>\n\n"
            "✈️ <b>/ara</b> <code>ORIGIN DEST DATE</code>\n"
            "   <i>Anlık canlı fiyatı gösterir.</i>"
        )
    elif cmd in ["gecmis", "history"]:
        return cmd_gecmis(args)
    elif cmd in ["ara", "search"]:
        return cmd_ara(args)
    return "❓ Bilinmeyen komut. <code>/yardim</code> yazın."

def main():
    print("Telegram Bot çalışıyor...", flush=True)
    # Telegram'dan son mesajları çek (long polling)
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 10}, timeout=15)
        updates = r.json().get("result", [])
        
        for upd in updates:
            msg = upd.get("message", {})
            if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                continue # Sadece size cevap ver
            
            text = msg.get("text", "")
            if text.startswith("/"):
                print(f"Gelen komut: {text}", flush=True)
                reply = process_command(text)
                send_message(reply)
                
                # Bu mesajı işaretle (bir daha okunmasın)
                offset = upd["update_id"] + 1
                requests.get(url, params={"offset": offset}, timeout=5)
    except Exception as e:
        print(f"Bot döngü hatası: {e}")

if __name__ == "__main__":
    main()
