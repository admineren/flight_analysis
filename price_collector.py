import os
import json
import requests
import time
from datetime import datetime, timezone, date
from viajante import get_flights, RoundTrip

TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_INGEST_TOKEN = os.environ["TB_INGEST_TOKEN"]
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
        return False
    
    url = f"{TB_HOST}/v0/events?name={TB_DATASOURCE}"
    headers = {
        "Authorization": f"Bearer {TB_INGEST_TOKEN}",
        "Content-Type": "application/x-ndjson"
    }
    data = "\n".join(json.dumps(p) for p in payloads)
    
    try:
        r = requests.post(url, headers=headers, data=data, timeout=15)
        if r.status_code == 202:
            print(f"✅ {len(payloads)} fiyat Tinybird'e gönderildi.")
            return True
        else:
            print(f"❌ Tinybird Hatası: {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Tinybird bağlantı hatası: {e}")
        return False

def main():
    print(f"=== Price Collector Başladı: {datetime.now(timezone.utc).isoformat()} ===")
    state = load_state()
    payloads = []
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for route in WATCHLIST:
        route_id = f"{route['origin']}-{route['dest']}-{route['depart']}"
        print(f"[{route_id}] Sorgulanıyor...")
        
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
                report = get_flights(trip, fetch="sweep", top=1, currency="TRY")
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
                        # state güncellemesini buradan kaldırdık! (Aşağıda yapacağız)
                        print(f"  📉 Yeni fiyat: {price} TRY ({airline})")
                    success = True
                    break 
                    
                else:
                    err = getattr(report.queries[0].error, 'code', 'unknown') if report.queries else 'no_query'
                    print(f"  ⚠️ Sonuç yok/Hata (Deneme {attempt+1}/3): {err}")
                    if err == "blocked":
                        time.sleep(30)
            except Exception as e:
                print(f"  ❌ Viajante hatası (Deneme {attempt+1}/3): {str(e)[:100]}")
                time.sleep(10)
        
        if not success:
            print(f"  ❌ {route_id} atlandı (3 denemede başarısız).")
            
        time.sleep(10)

    # Tinybird'e gönder ve BAŞARILI OLURSA state'i güncelle
    if payloads:
        if send_to_tinybird(payloads):
            # Sadece başarılıysa state'i güncelle
            for p in payloads:
                r_id = f"{p['origin']}-{p['destination']}-{p['departure_date']}"
                state[r_id] = {"price": p["price"], "updated_at": p["observed_at"]}
            save_state(state)
    else:
        print("\nGönderilecek yeni veri yok.")
        
    print("=== İşlem Tamamlandı ===")
