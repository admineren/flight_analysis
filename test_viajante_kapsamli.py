import time
from viajante import get_flights

SCENARIOS = [
    {"name": "IST-BCN TRY", "route": "IST-BCN:2027-01-15", "params": {}},
    {"name": "IST-JFK USD", "route": "IST-JFK:2027-02-10", "params": {"currency": "USD"}},
    {"name": "IST-BKK TRY, THY", "route": "IST-BKK:2027-04-10", "params": {"currency": "TRY", "airlines": ["TK"]}},
]

def safe_get_flights(route, params, max_retries=3):
    """Hata durumunda bekleyip tekrar deneyen güvenli arama fonksiyonu."""
    for attempt in range(max_retries):
        try:
            report = get_flights(route, fetch="sweep", top=5, **params)
            
            for query in report.queries:
                if query.status == "ok":
                    return report, query # Başarılı
                
                # Hata durumunu yakala (BLOCKED, RATE_LIMITED vb.)
                error_info = getattr(query, 'error', query)
                status = getattr(error_info, 'status', 'unknown')
                message = getattr(error_info, 'message', str(error_info))
                
                if "BLOCKED" in status.upper() or "BLOCKED" in message.upper() or "rate_limited" in message.lower():
                    print(f"  ⚠️ Google engeli (Deneme {attempt+1}/{max_retries}). 15 saniye bekleniyor...")
                    time.sleep(15)
                    break # Dış döngüde tekrar denemek için iç döngüden çık
                else:
                    print(f"  ❌ Farklı bir hata: {status} - {message}")
                    return report, query
                    
        except Exception as e:
            print(f"  ❌ Beklenmeyen Hata: {type(e).__name__}: {e}")
            time.sleep(5)
            
    return None, None # Tüm denemeler tükendi

print("=== Viajante Gelişmiş Test ===")

for s in SCENARIOS:
    print(f"\n--- {s['name']} ---")
    report, query = safe_get_flights(s["route"], s["params"])
    
    if query and query.status == "ok":
        print(f"  ✅ Başarılı | Para Birimi: {report.currency}")
        if query.price_insight:
            print(f"  📊 Fiyat Seviyesi: {query.price_insight.level.upper()} | En Düşük: {query.price_insight.lowest}")
        
        for i, offer in enumerate(query.offers[:2], 1):
            print(f"    {i}. {offer.airline} | {offer.price} {report.currency} | {offer.stops} | {offer.duration}")
    else:
        print(f"  ❌ İşlem Başarısız (Google Engelini Geçemedik)")
    
    time.sleep(5) # Senaryolar arası bekleme
