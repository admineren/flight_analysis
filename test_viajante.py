from viajante import get_flights

print("viajante test ediliyor...")
report = get_flights("IST-BCN:2027-01-15", fetch="sweep", top=5)

print(f"Dönen Nesne Tipi: {type(report)}")
print(f"Mevcut Özellikler (Attributes): {[a for a in dir(report) if not a.startswith('_')]}")

# Muhtemel sonuç listesi özelliklerini kontrol et
if hasattr(report, "results"):
    print(f"\nToplam Sonuç: {len(report.results)}")
    for r in report.results[:3]:
        print(f"  {r}")
elif hasattr(report, "offers"):
    print(f"\nToplam Teklif: {len(report.offers)}")
    for o in report.offers[:3]:
        print(f"  {o}")
elif hasattr(report, "flights"):
    print(f"\nToplam Uçuş: {len(report.flights)}")
    for f in report.flights[:3]:
        print(f"  {f}")
else:
    print("\nSonuçlar doğrudan bir listede değil. Tüm nesne içeriği:")
    print(report)
