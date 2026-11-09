"""
Swoop deals() + watch_deals() + price_deal() testi.
airportsdata kurulu olduğunda region filtreleri çalışır.
Telegram'a mesaj GÖNDERMEZ, sadece loglara yazar.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

from swoop import deals, watch_deals, price_deal


print("=" * 80)
print(f"SWOOP DEALS TESTİ — {datetime.now(timezone.utc).isoformat()}")
print("=" * 80)

# airportsdata kurulu mu?
try:
    import airportsdata
    print("✅ airportsdata kurulu — region filtreleri çalışacak")
except ImportError:
    print("❌ airportsdata KURULU DEĞİL — region filtreleri boş dönecek")


# ============================================================
# 1. BASİT DEALS (filtresiz — Google ne öneriyor?)
# ============================================================
print("\n" + "=" * 80)
print("1. BASİT DEALS (filtresiz)")
print("=" * 80)

try:
    result = deals("IST")
    print(f"Toplam deal: {len(result.deals)} | Partial: {result.partial}")

    sorted_deals = sorted(
        [d for d in result.deals if d.discount_pct],
        key=lambda d: d.discount_pct,
        reverse=True
    )[:15]

    print(f"\n{'#':>2} {'Hedef':22s} {'Ülke':14s} {'Gidiş':11s} {'Dönüş':11s} {'Fiyat':>7s} {'Normal':>7s} {'%':>4s} {'Bölge':12s}")
    print("-" * 115)
    for i, d in enumerate(sorted_deals, 1):
        region = str(d.destination_region) if d.destination_region else "-"
        print(f"{i:>2} {d.destination_city[:20]:22s} {d.destination_country[:12]:14s} "
              f"{d.departure_date:11s} {d.return_date or '-':11s} "
              f"{d.price:>5} {d.typical_price or 0:>7} {d.discount_pct or 0:>3}% {region[:12]:12s}")
    time.sleep(2)  # rate limit
except Exception as e:
    print(f"HATA: {type(e).__name__}: {str(e)[:200]}")


# ============================================================
# 2. HER BÖLGE İÇİN DEALS
# ============================================================
print("\n" + "=" * 80)
print("2. BÖLGE BAZINDA DEALS (maks $800, min %15 indirim)")
print("=" * 80)

region_results = {}
for region in ["europe", "asia", "americas", "africa", "oceania"]:
    try:
        time.sleep(1.5)
        r = deals("IST", region=region, max_price=800, min_discount_pct=15)
        region_results[region] = r
        print(f"\n🌍 {region.upper()}: {len(r.deals)} deal")
        for d in r.deals[:5]:
            print(f"  • {d.destination_city} ({d.destination_country}) — "
                  f"${d.price} (%{d.discount_pct}) {d.departure_date}→{d.return_date}")
    except Exception as e:
        region_results[region] = None
        print(f"\n🌍 {region.upper()}: HATA — {type(e).__name__}: {str(e)[:100]}")


# ============================================================
# 3. FİLTRELİ ASYA DEALS (detaylı)
# ============================================================
print("\n" + "=" * 80)
print("3. ASYA DEALS (detaylı tablo)")
print("=" * 80)

asia_deals = region_results.get("asia")
if asia_deals and asia_deals.deals:
    print(f"\n{'#':>2} {'Hedef':22s} {'Gidiş':11s} {'Dönüş':11s} {'Fiyat':>7s} {'Normal':>7s} {'%':>4s} {'Süre':>6s} {'Akt':>3s} {'Havayolu':20s}")
    print("-" * 115)
    for i, d in enumerate(asia_deals.deals[:15], 1):
        airlines = ",".join(d.airline_names[:2]) if d.airline_names else "?"
        dur = f"{d.duration_minutes}dk" if d.duration_minutes else "?"
        print(f"{i:>2} {d.destination_city[:20]:22s} "
              f"{d.departure_date:11s} {d.return_date or '-':11s} "
              f"{d.price:>5} {d.typical_price or 0:>7} {d.discount_pct or 0:>3}% "
              f"{dur:>6} {d.stops if d.stops is not None else '?':>3} {airlines[:20]}")

    # İlk deal detayı
    print(f"\n--- İlk Asya Deal detayı ---")
    first = asia_deals.deals[0]
    for field in ["origin", "destination", "destination_city", "destination_country",
                  "departure_date", "return_date", "price", "typical_price",
                  "discount_pct", "airlines", "airline_names", "duration_minutes",
                  "stops", "trip_days", "currency", "booking_url", "destination_region"]:
        val = getattr(first, field, '?')
        if field == "booking_url" and val:
            val = str(val)[:100]
        print(f"  {field}: {val}")
else:
    print("Asya deal yok (region filtresi veya upstream sorunu)")


# ============================================================
# 4. WATCH_DEALS (cache + diff)
# ============================================================
print("\n" + "=" * 80)
print("4. WATCH_DEALS (cache + diff)")
print("=" * 80)

CACHE_PATH = "/tmp/swoop_deals_cache.json"

# İlk çalıştırma
print("\n--- İlk çalıştırma (cache yok) ---")
try:
    r1 = deals("IST", region="asia", max_price=800, min_discount_pct=15)
    diff1 = watch_deals(r1, cache_path=CACHE_PATH, allow_empty=True)
    print(f"Cache: {CACHE_PATH}")
    print(f"  new: {len(diff1.new)}")
    print(f"  gone: {len(diff1.gone)}")
    print(f"  price_changes: {len(diff1.price_changes)}")
    print(f"  unchanged: {len(diff1.unchanged)}")
    print(f"  Cache boyutu: {os.path.getsize(CACHE_PATH)} byte")
    time.sleep(2)
except Exception as e:
    print(f"HATA: {type(e).__name__}: {str(e)[:150]}")

# İkinci çalıştırma
print("\n--- İkinci çalıştırma (aynı sorgu) ---")
try:
    r2 = deals("IST", region="asia", max_price=800, min_discount_pct=15)
    diff2 = watch_deals(r2, cache_path=CACHE_PATH)
    print(f"  new: {len(diff2.new)}")
    print(f"  gone: {len(diff2.gone)}")
    print(f"  price_changes: {len(diff2.price_changes)}")
    print(f"  unchanged: {len(diff2.unchanged)}")
except Exception as e:
    print(f"HATA: {type(e).__name__}: {str(e)[:150]}")


# ============================================================
# 5. PRICE_DEAL (doğrulama)
# ============================================================
print("\n" + "=" * 80)
print("5. PRICE_DEAL (güncel fiyat doğrulama)")
print("=" * 80)

if asia_deals and asia_deals.deals:
    target = asia_deals.deals[0]
    print(f"Hedef: {target.destination_city} ({target.departure_date}→{target.return_date})")
    print(f"Deals fiyatı: ${target.price}")
    try:
        time.sleep(2)
        price_result = price_deal(target)
        if price_result:
            print(f"  ✅ Doğrulama başarılı")
            print(f"  price: {price_result.price} {price_result.currency}")
            print(f"  fare_brand: {price_result.fare_brand}")
            print(f"  is_estimate: {price_result.is_estimate}")
            print(f"  booking_options: {len(price_result.booking_options)}")
        else:
            print(f"  ⚠️ price_deal None (deal expire olmuş olabilir)")
    except Exception as e:
        print(f"  HATA: {type(e).__name__}: {str(e)[:150]}")
else:
    print("Test edilecek deal yok.")


# ============================================================
# 6. ÖNERİLEN TELEGRAM BİLDİRİM FORMATLARI
# ============================================================
print("\n" + "=" * 80)
print("6. ÖNERİLEN TELEGRAM BİLDİRİMLERİ")
print("=" * 80)

if asia_deals and asia_deals.deals:
    print("\n--- YENİ FIRSAT ---")
    for d in asia_deals.deals[:2]:
        airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
        msg = (
            f"🎯 <b>[Swoop Deals] IST → {d.destination_city}</b>\n"
            f"📅 {d.departure_date} → {d.return_date}\n"
            f"💰 <b>${d.price}</b> (normal ${d.typical_price}, <b>%{d.discount_pct} indirim</b>)\n"
            f"🛫 {airlines} | {d.stops or '?'} aktarma | {d.duration_minutes or '?'}dk\n"
        )
        if d.booking_url:
            msg += f"🔗 {d.booking_url[:100]}"
        print(f"\n{msg}")

# Region bazında özet
print("\n--- BÖLGE ÖZETİ ---")
for reg, r in region_results.items():
    if r and r.deals:
        avg_disc = sum(d.discount_pct for d in r.deals if d.discount_pct) / len(r.deals)
        print(f"  {reg:10s}: {len(r.deals)} deal, ort. %{avg_disc:.0f} indirim")
    else:
        print(f"  {reg:10s}: 0 deal")

print("\n=== Test tamamlandı ===")
