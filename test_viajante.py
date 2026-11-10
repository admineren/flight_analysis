from viajante import get_flights

report = get_flights("IST-BCN:2027-01-15", fetch="sweep", top=5)
print(f"viajante: {len(report)} sonuç bulundu.")
if report:
    for r in report[:3]:
        print(f"  {r}")
