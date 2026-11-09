"""
Swoop esnek tarih testi — sadece loglara yazar, Telegram'a mesaj GÖNDERMEZ.
Kullanım: Actions > "Flexible Dates TEST" > Run workflow
"""
import time
from datetime import datetime, timedelta, timezone

import swoop
from swoop import search as swoop_search


# ============================================================
# 1. SWOOP'UN DESTEKLEDİĞİ FONKSİYONLARI KEŞFET
# ============================================================
print("=" * 70)
print("1. SWOOP API KEŞFİ")
print("=" * 70)
print(f"Modül versiyonu: {getattr(swoop, '__version__', '?')}")
print(f"Modül yolu: {swoop.__file__}")
print(f"\nMevcut fonksiyonlar (public):")
for name in dir(swoop):
    if name.startswith("_"):
        continue
    obj = getattr(swoop, name)
    if callable(obj):
        print(f"  - {name}()")


# ============================================================
# 2. ESNEK TARİH FONKSİYONU VAR MI?
# ============================================================
print("\n" + "=" * 70)
print("2. ESNEK TARİH FONKSİYONU ARAMA")
print("=" * 70)

flex_candidates = ["search_dates", "search_date_range", "search_flexible",
                   "search_calendar", "search_grid", "search_month"]
found_flex = None
for name in flex_candidates:
    if hasattr(swoop, name):
        print(f"  ✅ {name} bulundu!")
        found_flex = name
    else:
        print(f"  ❌ {name} yok")

print(f"\nSonuç: {'✅ Esnek tarih fonksiyonu VAR: ' + found_flex if found_flex else '❌ Esnek tarih fonksiyonu YOK, manuel döngü gerekecek'}")


# ============================================================
# 3. HAFTALIK ÖRNEKLEME İLE TARAMA (Rate limit dostu)
# ============================================================
print("\n" + "=" * 70)
print("3. HAFTALIK TARAMA TESTİ (IST → BKK, 8 hafta)")
print("=" * 70)

ORIGIN = "IST"
DESTINATION = "BKK"
WEEKS_AHEAD = 8
STAY_DAYS = 7

today = datetime.now(timezone.utc).date()
results = []

for week in range(WEEKS_AHEAD):
    depart = today + timedelta(days=7 + week * 7)  # yarın+7'den başla
    ret = depart + timedelta(days=STAY_DAYS)
    label = f"{depart} → {ret}"

    print(f"\n  [{week+1}/{WEEKS_AHEAD}] {label} sorgulanıyor...")
    try:
        # Gidiş
        out = swoop_search(ORIGIN, DESTINATION, str(depart))
        time.sleep(1)  # rate limit koruması
        # Dönüş
        ret_res = swoop_search(DESTINATION, ORIGIN, str(ret))

        if not out.results or not ret_res.results:
            print(f"    sonuç yok")
            continue

        out_min = min(opt.price for opt in out.results if opt.price)
        ret_min = min(opt.price for opt in ret_res.results if opt.price)
        total = out_min + ret_min

        results.append({
            "depart": str(depart),
            "return": str(ret),
            "out_usd": out_min,
            "ret_usd": ret_min,
            "total_usd": total,
        })
        print(f"    ${out_min} + ${ret_min} = ${total}")

        time.sleep(1)  # rate limit koruması
    except Exception as e:
        print(f"    hata: {type(e).__name__}: {str(e)[:100]}")
        time.sleep(2)


# ============================================================
# 4. SONUÇLARI SIRALA VE ANALİZ ET
# ============================================================
print("\n" + "=" * 70)
print("4. EN UCUZ 5 TARİH KOMBİNASYONU")
print("=" * 70)

if not results:
    print("Sonuç yok.")
else:
    results.sort(key=lambda x: x["total_usd"])
    prices = [r["total_usd"] for r in results]
    median = sorted(prices)[len(prices) // 2]
    threshold = median * 0.85  # %15 altı

    print(f"Toplam taranan: {len(results)} kombinasyon")
    print(f"Medyan: ${median}")
    print(f"%15 altı eşiği: ${threshold:.0f}\n")

    print(f"{'#':>2} {'Gidiş':12s} {'Dönüş':12s} {'Gidiş USD':>10s} {'Dönüş USD':>10s} {'Toplam':>10s} {'Durum':10s}")
    print("-" * 80)
    for i, r in enumerate(results[:5], 1):
        flag = "🎯 FIRSAT" if r["total_usd"] < threshold else "normal"
        print(f"{i:>2} {r['depart']:12s} {r['return']:12s} "
              f"${r['out_usd']:>9} ${r['ret_usd']:>9} ${r['total_usd']:>9} {flag:10s}")

    # USD→TL çevirisi (USD_TO_TL = 50 varsayımı)
    usd_to_tl = 50.0
    print(f"\nTL karşılığı (1 USD = {usd_to_tl} TL):")
    for i, r in enumerate(results[:3], 1):
        tl = r["total_usd"] * usd_to_tl
        print(f"  {i}. {r['depart']} → {r['return']}: ~{tl:,.0f} TL")


# ============================================================
# 5. ÖNERİLEN BİLDİRİM FORMATI
# ============================================================
print("\n" + "=" * 70)
print("5. ÖNERİLEN TELEGRAM BİLDİRİMİ (en ucuz kombinasyon)")
print("=" * 70)

if results:
    best = results[0]
    msg = (
        f"✈️ <b>[Esnek Tarih] IST → BKK</b>\n"
        f"📅 {best['depart']} → {best['return']} (7 gün)\n"
        f"💰 ~<b>{best['total_usd'] * 50:,.0f} TL</b> "
        f"(${best['total_usd']})\n"
        f"📊 {len(results)} tarih tarandı, bu en ucuz\n"
        f"⚠️ <i>USD bazlı tahmin, doğrula</i>"
    )
    print(msg)

print("\n=== Test tamamlandı ===")
