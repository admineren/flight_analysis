import sys
print("🚀 BOT BAŞLIYOR...", flush=True)

import os
import json
import requests
from datetime import date

print("📦 Temel kütüphaneler yüklendi. Viajante yükleniyor...", flush=True)

try:
    from viajante import get_flights, RoundTrip
    print("✅ Viajante başarıyla yüklendi.", flush=True)
except Exception as e:
    print(f"❌ VIAJANTE YÜKLENEMEDİ: {e}", flush=True)
    sys.exit(1)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_READ_TOKEN = os.environ.get("TB_READ_TOKEN")

STATE_FILE = "telegram_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"last_update_id": 0}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        print(f"📤 Mesaj gönderiliyor...", flush=True)
        r = requests.post(url, json={
            "chat_id": CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=10)
        print(f"📬 Telegram yanıtı: {r.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Mesaj gönderilemedi: {e}", flush=True)

def query_tinybird_latest(origin, dest, dep_date):
    url = f"{TB_HOST}/v0/pipes/latest_price.json"
    headers = {"Authorization": f"Bearer {TB_READ_TOKEN}"}
    params = {"origin": origin, "destination": dest, "departure_date": dep_date}
    try:
        print(f"🔍 Tinybird sorgulanıyor: {params}", flush=True)
        r = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"📊 Tinybird yanıtı: {r.status_code}", flush=True)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                return data[0]
    except Exception as e:
        print(f"❌ Tinybird okuma hatası: {e}", flush=True)
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
    try:
        report = get_flights(f"{origin}-{dest}:{dep}", fetch="sweep", top=1, currency="TRY", deadline_seconds=30)
        if report.queries and report.queries[0].status == "ok" and report.queries[0].offers:
            o = report.queries[0].offers[0]
            return f"✈️ <b>{origin} → {dest}</b> ({dep})\n\n💰 Canlı Fiyat: <b>{o.price:,.0f} TRY</b>\n🛫 {o.airline} | {o.duration} | {o.stops}"
        else:
            err = getattr(report.queries[0].error, 'code', 'unknown') if report.queries else 'no_query'
            return f"⚠️ Şu an canlı fiyat çekilemedi.\nKod: {err}"
    except Exception as e:
        return f"❌ Hata: {str(e)[:100]}"

def process_command(text):
    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/")
    args = parts[1:]
    
    if cmd in ["yardim", "help", "start"]:
        return "🤖 <b>Komutlar</b>\n\n📊 <b>/gecmis</b> <code>ORIGIN DEST DATE</code>\n✈️ <b>/ara</b> <code>ORIGIN DEST DATE</code>"
    elif cmd in ["gecmis", "history"]:
        return cmd_gecmis(args)
    elif cmd in ["ara", "search"]:
        return cmd_ara(args)
    return "❓ Bilinmeyen komut. <code>/yardim</code> yazın."

def main():
    state = load_state()
    offset = state.get("last_update_id", 0) + 1
    print(f"🔄 Bot dinlemeye başlıyor... (Offset: {offset})", flush=True)
    
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        # TIMEOUT 55 SANİYE: Bot neredeyse 1 dakika boyunca mesaj bekler
        r = requests.get(url, params={"offset": offset, "timeout": 55}, timeout=65)
        print(f"📥 Telegram API yanıtı: {r.status_code}", flush=True)
        
        updates = r.json().get("result", [])
        print(f"📨 Gelen yeni mesaj sayısı: {len(updates)}", flush=True)
        
        if not updates:
            print("💤 Yeni mesaj yok, kapanıyor.", flush=True)
            return

        for upd in updates:
            state["last_update_id"] = upd["update_id"]
            msg = upd.get("message", {})
            
            incoming_chat_id = str(msg.get("chat", {}).get("id"))
            if incoming_chat_id != str(CHAT_ID):
                print(f"⚠️ Yabancı chat_id atlandı: {incoming_chat_id}", flush=True)
                continue 
            
            text = msg.get("text", "")
            print(f"💬 Komut alındı: {text}", flush=True)
            
            if text.startswith("/"):
                reply = process_command(text)
                send_message(reply)
                
        save_state(state)
    except Exception as e:
        print(f"❌ Bot ana döngü hatası: {e}", flush=True)

if __name__ == "__main__":
    main()
