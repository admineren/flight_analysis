import inspect
import swoop

print("=" * 80)
print("SWOOP KÜTÜPHANESİ TAM KEŞİF")
print("=" * 80)

# 1. Tüm public fonksiyonlar ve sınıflar
print("\n--- FONKSİYONLAR ---")
for name in sorted(dir(swoop)):
    if name.startswith("_"):
        continue
    obj = getattr(swoop, name)
    if inspect.isfunction(obj):
        try:
            sig = inspect.signature(obj)
            print(f"\n✅ {name}{sig}")
        except Exception:
            print(f"\n✅ {name}()")
        doc = inspect.getdoc(obj)
        if doc:
            print(f"   {doc[:300]}")

print("\n\n--- SINIFLAR ---")
for name in sorted(dir(swoop)):
    if name.startswith("_"):
        continue
    obj = getattr(swoop, name)
    if inspect.isclass(obj):
        print(f"\n✅ {name}")
        try:
            sig = inspect.signature(obj.__init__)
            print(f"   __init__{sig}")
        except Exception:
            pass
        doc = inspect.getdoc(obj)
        if doc:
            print(f"   {doc[:200]}")
        if hasattr(obj, "__dataclass_fields__"):
            print("   Alanlar:")
            for fname, fobj in obj.__dataclass_fields__.items():
                print(f"     - {fname}: {fobj.type}")

# 2. search_legs özel inceleme
print("\n\n--- SEARCH_LEGS DETAYI ---")
if hasattr(swoop, "search_legs"):
    print(inspect.getdoc(swoop.search_legs))
    print(f"\nSignature: {inspect.signature(swoop.search_legs)}")

# 3. SearchLeg özel inceleme
print("\n\n--- SearchLeg SINIFI ---")
if hasattr(swoop, "SearchLeg"):
    print(inspect.getdoc(swoop.SearchLeg))
    print(f"Signature: {inspect.signature(swoop.SearchLeg.__init__)}")
    if hasattr(swoop.SearchLeg, "__dataclass_fields__"):
        for fname, fobj in swoop.SearchLeg.__dataclass_fields__.items():
            print(f"  - {fname}: {fobj.type}")

# 4. RoundTrip var mı?
print("\n\n--- ROUNDTRIP ARAMA ---")
for name in ["RoundTrip", "roundtrip", "round_trip", "Trip", "SearchLeg", "SelectedLeg"]:
    if hasattr(swoop, name):
        print(f"✅ {name} bulundu")
    else:
        print(f"❌ {name} yok")
