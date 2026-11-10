import os
import json
import requests
import time
from datetime import datetime, timezone, date
from viajante import get_flights, RoundTrip

print("1. Importlar başarılı, değişkenler ayarlanıyor...", flush=True)

TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_INGEST_TOKEN = os.environ.get("TB_INGEST_TOKEN")
TB_DATASOURCE = "price_history"

STATE_FILE = "price_collector_state.json"

WATCHLIST = [
    {"origin": "IST", "dest": "BKK", "depart": "2027-02-15", "ret": "2027-02-22"},
    {"origin": "IST", "dest": "DPS", "depart": "2027-03-10", "ret": "2027-03-17"},
    {"origin": "IST", "dest": "KUL", "depart": "2027-03-01", "ret": "2027-03-08"},
]

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"State kaydedilemedi: {e}")

def send_to_tinybird(payloads):
    if not payloads:
        print("Tinybird'e gönderilecek yeni veri yok.")
        return False
    
    print(f"Tinybird'e {len(payloads)} adet veri gönderiliyor...", flush=True)
    url = f"{TB_HOST}/v0/events?name={TB_DATASOURCE}"
    headers = {
        "Authorization": f"Bearer {TB_INGEST_TOKEN}",
        "Content-Type": "application/x-ndjson"
    }
    data = "\n".join(json.dumps(p) for p in payloads)
    
    try:
        r = requests.post(url, headers=headers, data=data, timeout=15)
        if r.status_code == 202:
            print(f"✅ {len(payloads)} fiyat Tinybird'e başarıyla gönderildi.")
            return True
        else:
            print(f"❌ Tinybird Hatası: {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Tinybird bağlantı hatası: {e}")
        return False

def main():
    print("2. main() fonksiyonu başladı...", flush=True)
    state = load_state()
    payloads = []
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for route in WATCHLIST:
        route_id = f"{route['origin']}-{route['dest']}-{route['depart']}"
        print(f"3. [{route_id}] için Trip nesnesi oluşturuluyor...", flush=True)
        
        trip = RoundTrip(
            origin=route["origin"],
            destination=route["dest"],
            departure_date=date.fromisoformat(route["depart"]),
            return_date=date.fromisoformat(route["ret"]),
            max_stops=1,
        )
        
        success = False
        for attempt in range(3):
            try:
                print(f"4. [{route_id}] Google Flights'a istek atılıyor (Deneme {attempt+1}/3)...", flush=True)
                # KRİTİK EKLEME: deadline_seconds=60 eklendi. 60 saniye içinde yanıt gelmezse iptal eder.
                report = get_flights(trip, fetch="sweep", top=1, currency="TRY", deadline_seconds=60)
                print(f"5. [{route_id}] İstek tamamlandı, yanıt işleniyor...", flush=True)
                
                if report.queries and report.queries[0].status == "ok" and report.queries[0].offers:
                    best = report.queries[0].offers[0]
                    price = best.price
                    airline = best.airline
                    
                    last_price = state.get(route_id, {}).get("price")
                    if price == last_price:
                        print(f"  ⏭️ Fiyat değişmedi ({price} TRY).")
                    else:
                        payloads.append({
                            "origin": route["origin"],
                            "destination": route["dest"],
                            "departure_date": route["depart"],
                            "return_date": route["ret"],
                            "airline": airline,
                            "price": price,
                            "currency": "TRY",
                            "source": "viajante",
                            "observed_at": now_str
                        })
                        print(f"  📉 Yeni fiyat bulundu: {price} TRY ({airline})")
                    success = True
                    break 
                else:
                    err_code = getattr(report.queries[0].error, 'code', 'unknown') if report.queries else 'no_query'
                    print(f"  ⚠️ Sonuç yok/Hata (Deneme {attempt+1}/3): {err_code}")
                    if err_code == "blocked":
                        time.sleep(20)
            except Exception as e:
                print(f"  ❌ Viajante hatası (Deneme {attempt+1}/3): {str(e)[:100]}")
                time.sleep(5)
        
        if not success:
            print(f"  ❌ {route_id} atlandı (3 denemede başarısız).")
            
        time.sleep(5)

    print("6. Tüm rotalar tarandı, Tinybird'e gönderim aşamasına geçiliyor...", flush=True)
    if send_to_tinybird(payloads):
        for p in payloads:
            r_id = f"{p['origin']}-{p['destination']}-{p['departure_date']}"
            state[r_id] = {"price": p["price"], "updated_at": p["observed_at"]}
        save_state(state)
    
    print("=== İşlem Tamamlandı ===", flush=True)

if __name__ == "__main__":
    main()
