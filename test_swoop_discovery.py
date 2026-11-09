"""
Swoop'un keşfedilmemiş fonksiyonlarını incele — signature + docstring.
Telegram'a mesaj GÖNDERMEZ.
"""
import inspect
import swoop


TARGETS = [
    "explore", "price_explore", "price_explore_all",
    "deals", "search_deal", "watch_deals", "diff_deals", "price_deal",
    "check_price",
    "Deal", "DealsResult", "DealsDiff", "PriceRange", "PriceResult",
    "ExploreResult", "ExploreDestination", "SearchLeg", "TripLeg",
]

print("=" * 80)
print("SWOOP FONKSİYON KEŞFİ")
print("=" * 80)

for name in TARGETS:
    if not hasattr(swoop, name):
        print(f"\n❌ {name} — YOK")
        continue

    obj = getattr(swoop, name)
    print(f"\n{'='*80}")
    print(f"✅ {name}")
    print('=' * 80)

    # Sınıf mı fonksiyon mu?
    if inspect.isclass(obj):
        print(f"TÜR: class")
        # __init__ signature
        try:
            sig = inspect.signature(obj.__init__)
            print(f"__init__{sig}")
        except Exception as e:
            print(f"__init__ signature alınamadı: {e}")

        # Field'ları göster (dataclass ise)
        if hasattr(obj, "__dataclass_fields__"):
            print("Alanlar:")
            for fname, fobj in obj.__dataclass_fields__.items():
                print(f"  - {fname}: {fobj.type}")
    else:
        print(f"TÜR: {type(obj).__name__}")
        try:
            sig = inspect.signature(obj)
            print(f"Signature: {name}{sig}")
        except Exception as e:
            print(f"Signature alınamadı: {e}")

    # Docstring
    doc = inspect.getdoc(obj)
    if doc:
        # İlk 500 karakter
        print(f"Docstring (ilk 500):\n{doc[:500]}")
    else:
        print("Docstring YOK")

print("\n" + "=" * 80)
print("KEŞİF TAMAMLANDI")
print("=" * 80)
