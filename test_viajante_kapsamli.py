import time
from viajante import get_flights

def search_flight_safe(route, fetch="sweep", top=5, max_retries=3, **params):
    """
    viajante get_flights için güvenli arama fonksiyonu.
    BLOCKED hatası durumunda retry_after_seconds kadar bekleyip tekrar dener.
    """
    for attempt in range(max_retries):
        try:
            report = get_flights(route, fetch=fetch, top=top, **params)
            
            for query in report.queries:
                if query.status == "ok":
                    return report, query  # Başarılı, teklifleri döndür
                
                # Hata durumu
                error = getattr(query, 'error', None)
                if error:
                    error_code = str(getattr(error, 'code', '')).upper()
                    if 'BLOCKED' in error_code or 'RATE_LIMITED' in error_code:
                        wait = getattr(query, 'retry_after_seconds', 15) or 15
                        print(f"  ⚠️ Google engeli (deneme {attempt+1}/{max_retries}). {wait}sn bekleniyor...")
                        time.sleep(wait)
                        break  # Dış döngüde tekrar dene
                    else:
                        print(f"  ❌ Farklı hata: {error_code} - {getattr(error, 'message', '')}")
                        return report, query
            else:
                # QueryFailure ama error objesi yok
                print(f"  ❌ Sorgu hatası: {query.status}")
                return report, query
                
        except Exception as e:
            print(f"  ❌ Beklenmeyen hata: {type(e).__name__}: {e}")
            time.sleep(5)
    
    return None, None  # Tüm denemeler tükendi
