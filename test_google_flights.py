from swoop import search as swoop_search
from datetime import datetime, timezone

# Kurlar (manuel güncellenir)
USD_TL = 36.0
EUR_TL = 56.0

ROUTES = [
    {"name": "IST → Bangkok",        "origin": "IST", "destination": "BKK",
     "departure": "2027-02-23", "return_date": "2027-03-02"},
    {"name": "IST → Hanoi",          "origin": "IST", "destination": "HAN",
     "departure": "2027-02-15", "return_date": "2027-02-25"},
    {"name": "IST → Ho Chi Minh",    "origin": "IST", "destination": "SGN",
     "departure": "2027-02-15", "return_date": "2027-02-25"},
    {"name": "IST → Kuala Lumpur",   "origin": "IST", "destination": "KUL",
     "departure": "2027-01-26", "return_date": "2027-02-16"},
    {"name": "IST → Shanghai",       "origin": "IST", "destination": "PVG",
     "departure": "2027-01-04", "return_date": "2027-01-19"},
    {"name": "IST → Tokyo Haneda",   "origin": "IST", "destination": "HND",
     "departure": "2027-03-10", "return_date": "2027-03-20"},
    {"name": "IST → Tokyo Narita",   "origin": "IST", "destination": "NRT",
     "departure": "2027-02-21", "return_date": "2027-03-01"},
    {"name": "IST → Manila",         "origin": "IST", "destination": "MNL",
     "departure": "2027-02-15", "return_date": "2027-03-01"},
    {"name": "IST → Singapore",      "origin": "IST", "destination": "SIN",
     "departure": "2027-02-15", "return_date": "2027-02-25"},
    {"name": "IST → Hong Kong",      "origin": "IST", "destination": "HKG",
     "departure": "2027-02-15", "return_date": "2027-02-25"},
    {"name": "IST → Seoul",          "origin": "IST", "destination": "ICN",
     "departure": "2027-03-10", "return_date": "2027-03-20"},
    {"name": "IST → Taipei",         "origin": "IST", "destination": "TPE",
     "departure": "2027-02-15", "return_date": "2027-02-25"},
]


def check_leg(origin, dest, date):
    try:
        results = swoop_search(origin, dest, date)
        if not results.results:
            return None
        options = [(opt.price, opt) for opt in results.results if opt.price]
        if not options:
            return None
        options.sort(key=lambda x: x[0])
        min_price, min_opt = options[0]
        airlines = set()
        for leg in min_opt.legs:
            if leg.itinerary and leg.itinerary.airline_names:
                for name in leg.itinerary.airline_names:
                    airlines.add(name)
        all_prices = sorted([p for p, _ in options])
        return {
            "price": min_price,
            "airlines": airlines,
            "total_options": len(options),
            "all_prices": all_prices,
        }
    except Exception as e:
        print(f"    HATA: {type(e).__name__}: {e}")
        return None


def fmt_conv(price):
    """Hem USD hem EUR varsayımıyla TL karşılığı."""
    return (f"{price} (~{price*USD_TL:,.0f} TL USD'ye göre, "
            f"~{price*EUR_TL:,.0f} TL EUR'ya göre)")


def main():
    print(f"=== Google Flights Test — {datetime.now(timezone.utc).isoformat()} ===")
    print(f"Kurlar: 1 USD = {USD_TL} TL | 1 EUR = {EUR_TL} TL\n")

    for route in ROUTES:
        print("=" * 80)
        print(f"ROTA: {route['name']}")
        print("=" * 80)

        print(f"\n  [Gidiş: {route['departure']}]")
        out = check_leg(route["origin"], route["destination"], route["departure"])
        if not out:
            print("    sonuç yok\n")
            continue

        print(f"    En ucuz: {out['price']} → {out['price']*USD_TL:,.0f} TL (USD)")
        print(f"    Havayolları: {', '.join(sorted(out['airlines']))}")
        print(f"    Toplam {out['total_options']} seçenek")

        print(f"\n  [Dönüş: {route['return_date']}]")
        ret = check_leg(route["destination"], route["origin"], route["return_date"])
        if not ret:
            print("    sonuç yok\n")
            continue

        print(f"    En ucuz: {ret['price']} → {ret['price']*USD_TL:,.0f} TL (USD)")
        print(f"    Havayolları: {', '.join(sorted(ret['airlines']))}")
        print(f"    Toplam {ret['total_options']} seçenek")

        total = out["price"] + ret["price"]
        print(f"\n  ➡️ TAHMİNİ ROUNDTRIP (toplam):")
        print(f"     {total} USD = {total*USD_TL:,.0f} TL")
        print(f"     {total} EUR = {total*EUR_TL:,.0f} TL")

        common = out["airlines"] & ret["airlines"]
        if common:
            print(f"     ✅ Ortak havayolu: {', '.join(sorted(common))}")
        else:
            print(f"     ⚠️ Ortak havayolu yok")

        print()

    print("=== Test tamamlandı ===")


if __name__ == "__main__":
    main()
