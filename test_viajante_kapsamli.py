"""
Viajante kapsamlı test dosyası.
Farklı rotalar, para birimleri, aktarma limitleri ve filtreler ile testler yapar.
Ayrıca rate limit ve hata toleransını gözlemler.
"""
import time
from viajante import get_flights

# Test senaryoları
SCENARIOS = [
    {
        "name": "IST-BCN Try (Temel)",
        "route": "IST-BCN:2027-01-15",
        "fetch": "sweep",
        "top": 5,
        "params": {},
    },
    {
        "name": "IST-BCN USD, Sadece Direkt (max_stops=0)",
        "route": "IST-BCN:2027-01-15",
        "fetch": "sweep",
        "top": 5,
        "params": {"currency": "USD", "max_stops": 0},
    },
    {
        "name": "IST-JFK USD (Uzun Mesafe)",
        "route": "IST-JFK:2027-02-10",
        "fetch": "sweep",
        "top": 5,
        "params": {"currency": "USD"},
    },
    {
        "name": "IST-DXB EUR, En Fazla 1 Aktarma",
        "route": "IST-DXB:2027-03-05",
        "fetch": "sweep",
        "top": 5,
        "params": {"currency": "EUR", "max_stops": 1},
    },
    {
        "name": "IST-BKK TRY, Sadece THY (airlines=['TK'])",
        "route": "IST-BKK:2027-04-10",
        "fetch": "sweep",
        "top": 5,
        "params": {"currency": "TRY", "airlines": ["TK"]},
    },
]

def run_scenario(scenario):
    print(f"\n{'='*60}")
    print(f"SENARYO: {scenario['name']}")
    print(f"Rota: {scenario['route']}")
    print(f"Parametreler: {scenario['params']}")
    print('='*60)
    
    start = time.time()
    try:
        report = get_flights(
            scenario["route"],
            fetch=scenario["fetch"],
            top=scenario["top"],
            **scenario["params"]
        )
        elapsed = time.time() - start
        
        print(f"Yanıt süresi: {elapsed:.2f}s")
        print(f"Para birimi: {report.currency}")
        
        for query in report.queries:
            if query.status == "ok":
                print(f"\n  Sorgu durumu: OK")
                print(f"  Toplam teklif: {len(query.offers)}")
                
                # Fiyat analizi
                if query.price_insight:
                    pi = query.price_insight
                    print(f"  Fiyat seviyesi: {pi.level}")
                    print(f"  En düşük: {pi.lowest} {report.currency}")
                    if pi.typical_range:
                        print(f"  Tipik aralık: {pi.typical_range[0]} - {pi.typical_range[1]} {report.currency}")
                
                # İlk 3 teklif
                for i, offer in enumerate(query.offers[:3], 1):
                    print(f"\n  Teklif {i}:")
                    print(f"    Havayolu: {offer.airline}")
                    print(f"    Fiyat: {offer.price} {report.currency}")
                    print(f"    Süre: {offer.duration}")
                    print(f"    Aktarma: {offer.stops}")
                    if offer.layover_city:
                        print(f"    Aktarma şehri: {offer.layover_city}")
                    if offer.needs_bag_verify:
                        print(f"    ⚠️ Bagaj ücreti doğrulanmalı")
            else:
                print(f"\n  Sorgu hatası: {query.error}")
                print(f"  Hata kodu: {query.error_code}")
                if query.retry_after_seconds:
                    print(f"  Yeniden deneme: {query.retry_after_seconds}s")
    
    except Exception as e:
        elapsed = time.time() - start
        print(f"  ❌ HATA ({elapsed:.2f}s): {type(e).__name__}: {e}")

def main():
    print("Viajante kapsamlı test başlıyor...")
    print(f"Toplam senaryo: {len(SCENARIOS)}")
    
    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"\n[{i}/{len(SCENARIOS)}] {scenario['name']}")
        run_scenario(scenario)
        
        # Rate limit için bekle
        if i < len(SCENARIOS):
            print("\n  Rate limit koruması: 5 saniye bekleniyor...")
            time.sleep(5)
    
    print("\n" + "="*60)
    print("Tüm senaryolar tamamlandı.")
    print("="*60)

if __name__ == "__main__":
    main()
