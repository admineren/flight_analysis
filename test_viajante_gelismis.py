"""
Viajante gelişmiş testler:
1. RoundTrip desteği (get_flights vs search_flights)
2. 3 aylık tarama (31 günlük dilimler)
3. Fiyat geçmişi (price_history) özelliği
"""
import os
import time
from datetime import date, timedelta

# Fiyat geçmişini etkinleştir (testten önce)
os.environ["VIAJANTE_PRICE_HISTORY"] = "1"

from viajante import get_flights, search_flights, search_dates, RoundTrip, price_history


def test_roundtrip():
    """RoundTrip nesnesinin get_flights ve search_flights ile kullanımı."""
    print("\n" + "="*70)
    print("TEST 1: RoundTrip Desteği")
    print("="*70)

    depart = date(2027, 2, 15)
    ret = date(2027, 2, 22)
    trip = RoundTrip(
        origin="IST", destination="BKK",
        departure_date=depart, return_date=ret,
        max_stops=1,
    )

    # Deneme 1: get_flights ile doğrudan Trip nesnesi
    print("\n--- 1a: get_flights(RoundTrip) ---")
    try:
        report = get_flights(trip, fetch="sweep", top=3, currency="TRY")
        for q in report.queries:
            if q.status == "ok":
                print(f"  ✅ Başarılı: {len(q.offers)} teklif")
                for o in q.offers[:2]:
                    print(f"     {o.airline} | {o.price_text} | {o.duration} | {o.stops}")
            else:
                print(f"  ❌ Hata: {getattr(q.error.code, 'value', '?')}")
    except Exception as e:
        print(f"  ❌ Exception: {type(e).__name__}: {str(e)[:150]}")

    time.sleep(5)

    # Deneme 2: search_flights ile Sequence[Trip]
    print("\n--- 1b: search_flights([RoundTrip]) ---")
    try:
        report = search_flights([trip], top=3, currency="TRY")
        for q in report.queries:
            if q.status == "ok":
                print(f"  ✅ Başarılı: {len(q.offers)} teklif")
                for o in q.offers[:2]:
                    print(f"     {o.airline} | {o.price_text} | {o.duration} | {o.stops}")
            else:
                print(f"  ❌ Hata: {getattr(q.error.code, 'value', '?')}")
    except Exception as e:
        print(f"  ❌ Exception: {type(e).__name__}: {str(e)[:150]}")


def test_three_month_scan():
    """3 aylık tarama: 31 günlük dilimlere bölerek en ucuz günleri bul."""
    print("\n" + "="*70)
    print("TEST 2: 3 Aylık Tarama (31 günlük dilimler)")
    print("="*70)

    origin, dest = "IST", "BKK"
    start = date(2027, 2, 1)
    end = date(2027, 4, 30)  # ~3 ay

    all_results = []
    current = start

    while current <= end:
        # Her dilim en fazla 31 gün
        window_end = min(current + timedelta(days=30), end)
        print(f"\n  Dilim: {current} → {window_end}")

        try:
            report = search_dates(
                origin=origin, destination=dest,
                start=current, end=window_end,
                currency="TRY", nights=7, max_stops=1,
            )
            if report.days:
                priced = [(d.departure_date, d.price) for d in report.days if d.price]
                all_results.extend(priced)
                print(f"    ✅ {len(priced)} gün fiyatlı")
            else:
                print(f"    ⚠️ Sonuç yok")
        except Exception as e:
            print(f"    ❌ Hata: {type(e).__name__}: {str(e)[:100]}")

        current = window_end + timedelta(days=1)
        time.sleep(8)  # rate limit

    # En ucuz 5 günü göster
    if all_results:
        all_results.sort(key=lambda x: x[1])
        print(f"\n  🏆 En ucuz 5 gün ({start} - {end}):")
        for d, p in all_results[:5]:
            print(f"     {d} → {p:,.0f} TRY")
    else:
        print("\n  ❌ Hiç sonuç alınamadı (Google BLOCKED olabilir).")


def test_price_history():
    """Fiyat geçmişi kaydı ve okunması."""
    print("\n" + "="*70)
    print("TEST 3: Fiyat Geçmişi (price_history)")
    print("="*70)

    # Önce birkaç arama yap (geçmişe kayıt için)
    print("\n  Önce 2 arama yapılıyor (kayıt için)...")
    for i in range(2):
        try:
            get_flights("IST-BKK:2027-02-15", fetch="sweep", top=1, currency="TRY")
            print(f"    Arama {i+1} tamam")
        except Exception:
            pass
        time.sleep(5)

    # Geçmişi oku
    print("\n  Geçmiş okunuyor...")
    try:
        hist = price_history(kind="flight", route="IST-BKK", limit=5)
        print(f"  Sonuç: {hist}")
    except Exception as e:
        print(f"  ❌ Hata: {type(e).__name__}: {str(e)[:150]}")


if __name__ == "__main__":
    test_roundtrip()
    time.sleep(10)
    test_three_month_scan()
    time.sleep(10)
    test_price_history()
    print("\n=== Tüm testler tamamlandı ===")
