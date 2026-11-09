"""
Google Flights veri testi — sadece loglara yazar, Telegram'a mesaj GÖNDERMEZ.
Kullanım: Actions > "Google Flights TEST" > Run workflow
Test bittikten sonra bu dosya silinebilir.
"""
from swoop import search as swoop_search
from datetime import datetime, timezone


ROUTES = [
    {
        "name": "IST → London (Ocak 2027)",
        "origin": "IST", "destination": "LHR",
        "departure": "2027-01-15", "return_date": "2027-01-22",
        "mode": "roundtrip",
    },
    {
        "name": "IST → Tokyo Haneda (Mart 2027)",
        "origin": "IST", "destination": "HND",
        "departure": "2027-03-10", "return_date": "2027-03-20",
        "mode": "roundtrip",
    },
    {
        "name": "IST → Bangkok (Şubat 2027)",
        "origin": "IST", "destination": "BKK",
        "departure": "2027-02-20", "return_date": "2027-03-02",
        "mode": "roundtrip",
    },
    {
        "name": "IST → Dubai (Aralık 2026)",
        "origin": "IST", "destination": "DXB",
        "departure": "2026-12-20", "return_date": "2026-12-27",
        "mode": "roundtrip",
    },
]


def check_leg(origin, dest, date):
    """Tek yön için en ucuz fiyat + havayolu + tüm fiyat dağılımı."""
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


def main():
    print(f"=== Google Flights Test — {datetime.now(timezone.utc).isoformat()} ===\n")

    for route in ROUTES:
        print("=" * 80)
        print(f"ROTA: {route['name']}")
        print(f"  {route['origin']} → {route['destination']} ({route['mode']})")
        print("=" * 80)

        # Gidiş
        print(f"\n  [Gidiş: {route['departure']}]")
        out = check_leg(route["origin"], route["destination"], route["departure"])
        if not out:
            print("    sonuç yok")
            print()
            continue

        print(f"    En ucuz: {out['price']}")
        print(f"    Havayolları: {', '.join(sorted(out['airlines']))}")
        print(f"    Toplam {out['total_options']} seçenek")
        prices = out["all_prices"]
        print(f"    Fiyat dağılımı: min={prices[0]}, "
              f"medyan={prices[len(prices)//2]}, max={prices[-1]}")

        # Dönüş (roundtrip ise)
        if route["mode"] == "roundtrip":
            print(f"\n  [Dönüş: {route['return_date']}]")
            ret = check_leg(route["destination"], route["origin"], route["return_date"])
            if not ret:
                print("    sonuç yok")
                print()
                continue

            print(f"    En ucuz: {ret['price']}")
            print(f"    Havayolları: {', '.join(sorted(ret['airlines']))}")
            print(f"    Toplam {ret['total_options']} seçenek")

            total = out["price"] + ret["price"]
            print(f"\n  ➡️ TAHMİNİ ROUNDTRIP: {total}")
            print(f"     (gidiş {out['price']} + dönüş {ret['price']})")

            common = out["airlines"] & ret["airlines"]
            if common:
                print(f"     Ortak havayolu: {', '.join(sorted(common))}")
            else:
                print(f"     ⚠️ Ortak havayolu yok — gerçek bundle fiyatı daha yüksek olabilir")

        print()

    print("=== Test tamamlandı ===")


if __name__ == "__main__":
    main()
