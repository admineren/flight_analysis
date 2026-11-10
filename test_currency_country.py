"""
set_country format testi — rate limit dostu.
Her format için TEK search çağrısı, 10sn arayla.
"""
import time
import inspect
from datetime import datetime, timedelta, timezone

from swoop import search as swoop_search, set_country


print("=" * 70)
print("set_country FORMATLARI")
print("=" * 70)

# Önce kaynak kodu
print(f"Signature: {inspect.signature(set_country)}")
try:
    src = inspect.getsource(set_country)
    print(f"\nKaynak (ilk 800):")
    print(src[:800])
except:
    pass

# Test rotası
ORIGIN = "IST"
DEST = "TBS"
today = datetime.now(timezone.utc).date()
depart = today + timedelta(days=60)

FORMATS_TO_TRY = [
    "TR",       # ISO alpha-2
    "TUR",      # ISO alpha-3
    "Turkey",   # İngilizce isim
]

print(f"\nTest rotası: {ORIGIN} → {DEST}, {depart}")
print(f"Formatlar: {FORMATS_TO_TRY}")
print(f"Her format arası 10sn bekle\n")

# İlk çağrıdan önce 15sn bekle (önceki rate limit'in geçmesi için)
print("Rate limit için 15sn bekleniyor...")
time.sleep(15)

for fmt in FORMATS_TO_TRY:
    print(f"\n{'='*60}")
    print(f"TEST: set_country('{fmt}')")
    print('='*60)

    try:
        set_country(fmt)
        print(f"  set_country('{fmt}') çağrısı başarılı")

        time.sleep(2)
        result = swoop_search(ORIGIN, DEST, str(depart))

        if result.results:
            prices = [opt.price for opt in result.results if opt.price]
            currency = getattr(result.results[0], "currency", "?")

            print(f"  ✅ Sonuç: {len(prices)} seçenek")
            print(f"  Min fiyat: {min(prices)} {currency}")
            print(f"  İlk 3: {prices[:3]}")
        else:
            print(f"  ⚠️ Sonuç yok (boş liste)")

    except Exception as e:
        print(f"  ❌ HATA: {type(e).__name__}: {str(e)[:120]}")

    # Rate limit için 10sn bekle
    print(f"  10sn bekleniyor...")
    time.sleep(10)

print("\n=== Test tamamlandı ===")
