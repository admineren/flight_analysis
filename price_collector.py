import os
import json
import requests
import time
from datetime import datetime, timezone
from viajante import get_flights

# Tinybird Ayarları
TB_HOST = os.environ.get("TINYBIRD_HOST", "https://api.tinybird.co")
TB_INGEST_TOKEN = os.environ["TB_INGEST_TOKEN"]
TB_DATASOURCE = "price_history"

STATE_FILE = "price_collector_state.json"

# İzlenecek Rotalar
WATCHLIST = [
    {"origin": "IST", "dest": "BKK", "depart": "2027-02-15", "ret": "2027-02-22"},
    {"origin": "IST", "dest": "DPS", "depart": "2027-03-10", "ret": "2027-03-17"},
    {"origin": "IST", "dest": "KUL", "depart": "2027-03-01", "ret": "2027-03-08"},
]

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_to_tinybird(payloads):
    """Events API'ye NDJSON formatında veri gönderir."""
    if not payloads:
        return
    
    url = f"{TB_HOST}/v0/events?name={TB_DATASOURCE}"
    headers = {
        "Authorization": f"Bearer {TB_INGEST_TOKEN}",
        "Content-Type": "application/x-ndjson"
    }
    # Tinybird NDJSON bekler (her satır bir JSON objesi)
    data = "\n".join(json.dumps(p) for p in payloads)
    
    try:
        r = requests.post(url, headers=headers, data=data, timeout=15)
        if r.status_code == 202:
            print(f"✅ {len(payloads)} fiyat Tinybird'e gönderildi.")
        else:
            print(f"❌ Tinybird Hatası: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"❌ Tinybird bağlantı hatası: {e}")

def main():
    print(f"=== Price Collector Başladı: {datetime.now(timezone.utc).isoformat()} ===")
    state = load_state()
    payloads = []
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") # Tinybird DateTime formatı

    for route in WATCHLIST:
        route_id = f"{route['origin']}-{route['dest']}-{route['depart']}"
        print(f"[{route_id}] Sorgulanıyor...")
        
        try:
            # Gidiş-dönüş arama (RoundTrip)
            query = f"{route['origin']}-{route['dest']}:{route['depart']}"
            report = get_flights(
                query, 
                trip="rt", # Gidiş dönüş
                return_date=route['ret'],
                fetch="sweep", 
                top=1, 
                currency="TRY"
            )
            
            if report.queries and report.queries[0].status == "ok" and report.queries[0].offers:
                best_offer = report.queries[0].offers[0]
                price = best_offer.price
                airline = best_offer.airline
                
                # Duplicate kontrolü (Eğer fiyat aynıysa DB'ye yazma)
                last_price = state.get(route_id, {}).get("price")
                if price == last_price:
                    print(f"  ⏭️ Fiyat değişmedi ({price} TRY). Kaydedilmedi.")
                    continue
                
                # Yeni kayıt oluştur
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
                state[route_id] = {"price": price, "updated_at": now_str}
                print(f"  📉 Yeni fiyat: {price} TRY ({airline})")
                
            else:
                err = getattr(report.queries[0].error, 'code', 'unknown') if report.queries else 'no_query'
                print(f"  ⚠️ Sonuç yok/Hata: {err}")
                
        except Exception as e:
            print(f"  ❌ Viajante hatası: {str(e)[:100]}")
            
        time.sleep(5) # Rate limit koruması

    # Tinybird'e gönder
    if payloads:
        send_to_tinybird(payloads)
        save_state(state)
    else:
        print("\nGönderilecek yeni veri yok.")

if __name__ == "__main__":
    main()
