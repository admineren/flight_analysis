import time
from datetime import date
from viajante import get_flights, RoundTrip

trip = RoundTrip(
    origin="IST", destination="BKK",
    departure_date=date(2027, 2, 15),
    return_date=date(2027, 2, 22),
    max_stops=1,
)
report = get_flights(trip, fetch="sweep", top=3, currency="TRY")
for q in report.queries:
    if q.status == "ok" and q.offers:
        print(f"✅ RoundTrip ÇALIŞIYOR: {len(q.offers)} teklif")
        for o in q.offers[:2]:
            print(f"   {o.airline} | {o.price_text}")
    else:
        err = getattr(q, "error", None)
        print(f"❌ Hata: {getattr(err.code, 'value', 'unknown') if err else 'unknown'}")
