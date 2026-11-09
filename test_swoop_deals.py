"""
Swoop deals() + watch_deals() testi.
Telegram'a mesaj GÖNDERMEZ, sadece loglara yazar.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from swoop import deals, watch_deals, price_deal


print("=" * 80)
print(f"SWOOP DEALS TESTİ — {datetime.now(timezone.utc).isoformat()}")
print("=" * 80)


# ============================================================
# 1. BASİT DEALS ÇAĞRISI (filtresiz)
# ============================================================
print("\n" + "=" * 80)
print("1. BASİT DEALS (filtresiz — Google ne öneriyor?)")
print("=" * 80)

try:
    result = deals("IST")
    print(f"Toplam deal: {len(result.deals)}")
    print(f"Origin: {result.origin}")
    print(f"Partial: {result.partial}")

    # En yüksek indirimli ilk 10
    sorted_deals = sorted(
        [d for d in result.deals if d.discount_pct],
        key=lambda d: d.discount_pct,
        reverse=True
    )[:10]

    print(f"\n{'#':>2} {'Hedef':25s} {'Ülke':15s} {'Gidiş':12s} {'Dönüş':12s} {'Fiyat':>8s} {'Normal':>8s} {'%':>4s}")
    print("-" * 100)
    for i, d in enumerate(sorted_deals, 1):
        print(f"{i:>2} {d.destination_city[:23]:25s} {d.destination_country[:13]:15s} "
              f"{d.departure_date:12s} {d.return_date or '-':12s} "
              f"{d.price:>6} {d.typical_price or 0:>8} {d.discount_pct or 0:>3}%")

except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ============================================================
# 2. FİLTRELİ DEALS (Asya + maksimum fiyat + indirim)
# ============================================================
print("\n" + "=" * 80)
print("2. FİLTRELİ DEALS (bölge=Asya, maks=700 USD, min %15 indirim)")
print("=" * 80)

# depart_window: önümüzdeki 60 gün
today = datetime.now(timezone.utc).date()
depart_start = (today + timedelta(days=30)).strftime("%Y-%m-%d")
depart_end = (today + timedelta(days=90)).strftime("%Y-%m-%d")

try:
    result_filtered = deals(
        "IST",
        depart_window=(depart_start, depart_end),
        trip_length=(5, 14),
        max_price=700,
        min_discount_pct=15,
        region="asia",
    )
    print(f"Toplam filtered deal: {len(result_filtered.deals)}")
    print(f"Depart window: {depart_start} → {depart_end}")

    if result_filtered.deals:
        print(f"\n{'#':>2} {'Hedef':25s} {'Gidiş':12s} {'Dönüş':12s} {'Fiyat':>8s} {'Normal':>8s} {'%':>4s} {'Havayolu':20s}")
        print("-" * 110)
        for i, d in enumerate(result_filtered.deals[:15], 1):
            airlines = ",".join(d.airline_names[:2]) if d.airline_names else "?"
            print(f"{i:>2} {d.destination_city[:23]:25s} "
                  f"{d.departure_date:12s} {d.return_date or '-':12s} "
                  f"{d.price:>6} {d.typical_price or 0:>8} {d.discount_pct or 0:>3}% "
                  f"{airlines[:20]}")

        # Örnek Deal detayı
        print(f"\n--- İlk Deal detayı ---")
        first = result_filtered.deals[0]
        for field in ["origin", "destination", "destination_city", "destination_country",
                      "departure_date", "return_date", "price", "typical_price",
                      "discount_pct", "airlines", "airline_names", "duration_minutes",
                      "stops", "trip_days", "currency", "booking_url"]:
            print(f"  {field}: {getattr(first, field, '?')}")
    else:
        print("Filtreye uyan deal yok.")

except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ============================================================
# 3. WATCH_DEALS İLE STATE YÖNETİMİ
# ============================================================
print("\n" + "=" * 80)
print("3. WATCH_DEALS (cache + diff)")
print("=" * 80)

CACHE_PATH = "/tmp/swoop_deals_cache.json"

# İlk çalıştırma
print("\n--- İlk çalıştırma (cache yok) ---")
try:
    r1 = deals("IST", region="asia", max_price=700, min_discount_pct=10)
    diff1 = watch_deals(r1, cache_path=CACHE_PATH, allow_empty=True)
    print(f"Cache oluşturuldu: {CACHE_PATH}")
    print(f"  new: {len(diff1.new)}")
    print(f"  gone: {len(diff1.gone)}")
    print(f"  price_changes: {len(diff1.price_changes)}")
    print(f"  unchanged: {len(diff1.unchanged)}")
    print(f"  Cache dosya boyutu: {os.path.getsize(CACHE_PATH) / 1024:.1f} KB")
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")

# İkinci çalıştırma (aynı sorgu, değişiklik yok)
print("\n--- İkinci çalıştırma (hemen ardından, değişiklik beklenmez) ---")
try:
    r2 = deals("IST", region="asia", max_price=700, min_discount_pct=10)
    diff2 = watch_deals(r2, cache_path=CACHE_PATH)
    print(f"  new: {len(diff2.new)}")
    print(f"  gone: {len(diff2.gone)}")
    print(f"  price_changes: {len(diff2.price_changes)}")
    print(f"  unchanged: {len(diff2.unchanged)}")
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ============================================================
# 4. PRICE_DEAL İLE DOĞRULAMA
# ============================================================
print("\n" + "=" * 80)
print("4. PRICE_DEAL (bir deal'in güncel fiyatını doğrula)")
print("=" * 80)

try:
    if result_filtered.deals:
        target_deal = result_filtered.deals[0]
        print(f"Hedef: {target_deal.destination_city} ({target_deal.departure_date})")
        print(f"Deals fiyatı: {target_deal.price} {target_deal.currency or 'USD'}")

        price_result = price_deal(target_deal)
        if price_result:
            print(f"  Doğrulama başarılı!")
            print(f"  price: {price_result.price}")
            print(f"  currency: {price_result.currency}")
            print(f"  fare_brand: {price_result.fare_brand}")
            print(f"  is_estimate: {price_result.is_estimate}")
            print(f"  booking_options: {len(price_result.booking_options)}")
        else:
            print(f"  price_deal None döndü (deal expire olmuş olabilir)")
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ============================================================
# 5. ÖNERİLEN TELEGRAM BİLDİRİM FORMATI
# ============================================================
print("\n" + "=" * 80)
print("5. ÖNERİLEN TELEGRAM BİLDİRİMİ")
print("=" * 80)

if result_filtered.deals:
    for i, d in enumerate(result_filtered.deals[:3], 1):
        airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
        msg = (
            f"🎯 <b>[Swoop Deals] IST → {d.destination_city}</b>\n"
            f"📅 {d.departure_date} → {d.return_date}\n"
            f"💰 <b>${d.price}</b> (normal: ${d.typical_price}, "
            f"<b>%{d.discount_pct} indirim</b>)\n"
            f"🛫 {airlines} | {d.stops or '?'} aktarma | {d.duration_minutes or '?'}dk\n"
        )
        if d.booking_url:
            msg += f"🔗 {d.booking_url[:100]}"
        print(f"\n--- {i}. ---\n{msg}")

print("\n=== Test tamamlandı ===")
