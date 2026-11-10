from fast_flights import FlightQuery, Passengers, create_query, get_flights

query = create_query(
    flights=[FlightQuery(date="2027-01-15", from_airport="IST", to_airport="BCN")],
    trip="one-way", seat="economy", passengers=Passengers(adults=1)
)
results = get_flights(query)
print(f"fast-flights: {len(results)} sonuç bulundu.")
if results: print(f"En ucuz: {results[0]}")
