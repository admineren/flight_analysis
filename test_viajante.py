from viajante import search_flights
results = search_flights("IST", "BCN", "2027-01-15")
print(f"viajante: {len(results)} sonuç bulundu.")
if results: print(f"En ucuz: {results[0]}")
