from swoop import search
result = search("IST", "BCN", "2027-01-15")
print(f"swoop-flights: {len(result.results)} sonuç bulundu.")
if result.results: print(f"En ucuz: {result.results[0].price}")
