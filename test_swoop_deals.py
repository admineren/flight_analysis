"""
Swoop deals() — TEK çağrı + lokal filtre stratejisi.
Bölge/indirim/fiyat filtrelerini Google'a değil Python'a yaptırıyoruz.
Telegram'a mesaj GÖNDERMEZ.
"""
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

from swoop import deals, watch_deals, price_deal


CACHE_PATH = "/tmp/swoop_deals_cache.json"

print("=" * 80)
print(f"SWOOP DEALS v2 — {datetime.now(timezone.utc).isoformat()}")
print("=" * 80)


# ============================================================
# 1. TEK ÇAĞRI: filtresiz deals()
# ============================================================
print("\n" + "=" * 80)
print("1. TEK ÇAĞRI: deals('IST') filtresiz")
print("=" * 80)

try:
    result = deals("IST")
    print(f"✅ {len(result.deals)} deal alındı")
except Exception as e:
    print(f"❌ HATA: {type(e).__name__}: {str(e)[:200]}")
    raise SystemExit(1)

# Tüm deal'leri tablolaştır
print(f"\n{'#':>2} {'Hedef':22s} {'Ülke':14s} {'Gidiş':11s} {'Fiyat':>7s} {'%':>4s} {'Bölge':15s}")
print("-" * 85)
for i, d in enumerate(sorted(result.deals, key=lambda x: -(x.discount_pct or 0))[:20], 1):
    region = str(d.destination_region).replace("Region.", "") if d.destination_region else "-"
    print(f"{i:>2} {d.destination_city[:20]:22s} {d.destination_country[:12]:14s} "
          f"{d.departure_date:11s} {d.price:>5} {d.discount_pct or 0:>3}% {region:15s}")


# ============================================================
# 2. LOKAL FİLTRE: her bölge için ayrı liste
# ============================================================
print("\n" + "=" * 80)
print("2. LOKAL FİLTRE (Google'a yeni istek YOK)")
print("=" * 80)

# Bölgeye göre grupla
by_region = defaultdict(list)
for d in result.deals:
    region = str(d.destination_region).replace("Region.", "").strip() if d.destination_region else "UNKNOWN"
    by_region[region].append(d)

for region, deals_list in sorted(by_region.items()):
    print(f"\n🌍 {region}: {len(deals_list)} deal")
    for d in sorted(deals_list, key=lambda x: -(x.discount_pct or 0))[:3]:
        print(f"   • {d.destination_city} — ${d.price} (%{d.discount_pct}) {d.departure_date}")


# ============================================================
# 3. LOKAL FİLTRE: Asya + min %20 + maks $800
# ============================================================
print("\n" + "=" * 80)
print("3. ASYA + min %20 + maks $800 (lokal filtre)")
print("=" * 80)

asia_filtered = [
    d for d in result.deals
    if d.destination_region and "ASIA" in str(d.destination_region)
    and (d.discount_pct or 0) >= 20
    and d.price <= 800
]

print(f"Sonuç: {len(asia_filtered)} deal")
if asia_filtered:
    print(f"\n{'#':>2} {'Hedef':20s} {'Gidiş':11s} {'Dönüş':11s} {'Fiyat':>7s} {'Normal':>7s} {'%':>4s} {'Havayolu':20s}")
    print("-" * 100)
    for i, d in enumerate(sorted(asia_filtered, key=lambda x: -(x.discount_pct or 0)), 1):
        airlines = ",".join(d.airline_names[:2]) if d.airline_names else "?"
        print(f"{i:>2} {d.destination_city[:18]:20s} "
              f"{d.departure_date:11s} {d.return_date or '-':11s} "
              f"{d.price:>5} {d.typical_price or 0:>7} {d.discount_pct or 0:>3}% "
              f"{airlines[:20]}")


# ============================================================
# 4. LOKAL FİLTRE: min %40 indirim (her bölgeden)
# ============================================================
print("\n" + "=" * 80)
print("4. YÜKSEK İNDİRİM (min %40, her bölgeden)")
print("=" * 80)

high_discount = [d for d in result.deals if (d.discount_pct or 0) >= 40]
print(f"Sonuç: {len(high_discount)} deal")
for d in sorted(high_discount, key=lambda x: -(x.discount_pct or 0)):
    region = str(d.destination_region).replace("Region.", "") if d.destination_region else "-"
    print(f"  🎯 {d.destination_city} ({region}) — ${d.price} (normal ${d.typical_price}, %{d.discount_pct})")


# ============================================================
# 5. WATCH_DEALS (cache diff — 1 çağrı daha)
# ============================================================
print("\n" + "=" * 80)
print("5. WATCH_DEALS (cache diff)")
print("=" * 80)

time.sleep(3)  # rate limit için biraz bekle

try:
    # İlk çalıştırma
    diff = watch_deals(result, cache_path=CACHE_PATH, allow_empty=True)
    print(f"  new: {len(diff.new)}")
    print(f"  gone: {len(diff.gone)}")
    print(f"  price_changes: {len(diff.price_changes)}")
    print(f"  unchanged: {len(diff.unchanged)}")
    print(f"  Cache boyutu: {os.path.getsize(CACHE_PATH)} byte")

    if diff.new:
        print(f"\n  🆕 Yeni deal'ler:")
        for d in diff.new[:5]:
            print(f"    • {d.destination_city} — ${d.price} (%{d.discount_pct})")

    # Cache içeriği
    print(f"\n  Cache ilk 3 deal:")
    import json
    with open(CACHE_PATH) as f:
        cache_data = json.load(f)
    for i, item in enumerate(cache_data[:3] if isinstance(cache_data, list) else list(cache_data.items())[:3], 1):
        print(f"    {i}. {str(item)[:150]}")
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {str(e)[:150]}")


# ============================================================
# 6. PRICE_DEAL (1 çağrı daha)
# ============================================================
print("\n" + "=" * 80)
print("6. PRICE_DEAL (doğrulama)")
print("=" * 80)

if result.deals:
    target = sorted(result.deals, key=lambda x: -(x.discount_pct or 0))[0]
    print(f"Hedef: {target.destination_city} ({target.departure_date}) — ${target.price}")

    time.sleep(3)
    try:
        pr = price_deal(target)
        if pr:
            print(f"  ✅ Doğrulama: ${pr.price} {pr.currency} (deals: ${target.price})")
            print(f"  is_estimate: {pr.is_estimate}")
            print(f"  booking_options: {len(pr.booking_options)}")
        else:
            print(f"  ⚠️ None döndü (deal expire olmuş olabilir)")
    except Exception as e:
        print(f"  HATA: {type(e).__name__}: {str(e)[:150]}")


# ============================================================
# 7. ÖNERİLEN TELEGRAM BİLDİRİM FORMATI
# ============================================================
print("\n" + "=" * 80)
print("7. ÖNERİLEN TELEGRAM BİLDİRİMİ")
print("=" * 80)

# Yüksek indirimliler için örnek
for d in sorted(result.deals, key=lambda x: -(x.discount_pct or 0))[:2]:
    region = str(d.destination_region).replace("Region.", "") if d.destination_region else "-"
    airlines = ", ".join(d.airline_names[:2]) if d.airline_names else "?"
    msg = (
        f"🎯 <b>[Swoop Deals] IST → {d.destination_city}</b> ({region})\n"
        f"📅 {d.departure_date} → {d.return_date}\n"
        f"💰 <b>${d.price}</b> (normal ${d.typical_price}, <b>%{d.discount_pct}</b>)\n"
        f"🛫 {airlines}"
    )
    if d.stops is not None:
        msg += f" | {d.stops} aktarma"
    if d.duration_minutes:
        msg += f" | {d.duration_minutes}dk"
    if d.booking_url:
        msg += f"\n🔗 {d.booking_url[:100]}"
    print(f"\n{msg}")

print("\n=== Test tamamlandı ===")
