import time
from viajante import get_flights, search_dates

print("=" * 70)
print("VIAJANTE DETAYLI PARAMETRE VE HATA ANALİZİ")
print("=" * 70)

# 1. search_dates: Bir ay içindeki en ucuz tarihler
print("\n--- search_dates: IST-BCN, Ocak 2027 ---")
try:
    report = search_dates("IST-BCN", "2027-01-01", "2027-01-31", top=3)
    for q in report.queries:
        if q.status == "ok":
            print(f"  En ucuz tarih: {q.date} -> {q.offers[0].price} {report.currency}")
        else:
            print(f"  Sorgu hatası: status={q.status}, empty_reason={getattr(q, 'empty_reason', None)}")
except Exception as e:
    print(f"  search_dates hatası: {type(e).__name__}: {e}")

time.sleep(5)

# 2. Hata nesnesini doğru alanlarla yakalamak
print("\n--- Hata Yapısı Analizi (Bilerek BLOCKED tetikleme) ---")
try:
    report = get_flights("IST-DXB:2027-03-05", fetch="sweep", top=3, currency="EUR")
    for q in report.queries:
        if q.status != "ok":
            print(f"  Durum: {q.status}")
            print(f"  Boş sebep: {getattr(q, 'empty_reason', 'YOK')}")
            print(f"  Yeniden deneme: {getattr(q, 'retry_after', 'YOK')}")
            print(f"  Gözlem zamanı: {getattr(q, 'observed_at', 'YOK')}")
except Exception as e:
    print(f"  Beklenen hata: {type(e).__name__}: {e}")
