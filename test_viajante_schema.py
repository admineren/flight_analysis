"""
Viajante gerçek yanıt şeması — JSON dökümü.
Hem get_flights hem search_flex için tüm alanları gösterir.
"""
import json
import time
from datetime import date, datetime
from dataclasses import asdict, is_dataclass

from viajante import get_flights, search_flex


def jsonable(obj):
    """date/datetime/enum'ları JSON'a çevir."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "value"):  # enum
        return obj.value
    return str(obj)


def dump(title, obj):
    print(f"\n{'='*70}")
    print(f"{title}")
    print('=' * 70)
    try:
        print(json.dumps(obj, indent=2, default=jsonable, ensure_ascii=False))
    except Exception as e:
        print(f"JSON dökümü başarısız: {e}")
        print(repr(obj)[:2000])


# ============================================================
# 1. get_flights — Tek rota, tek tarih
# ============================================================
print("### TEST 1: get_flights (IST-BCN 2027-01-15) ###")
try:
    report = get_flights(
        "IST-BCN:2027-01-15",
        fetch="sweep", top=3, currency="TRY",
    )
    dump("SearchReport (üst seviye)", {
        "searched_at": report.searched_at,
        "currency": report.currency,
        "locale": report.locale,
        "fetch_backend": report.fetch_backend,
        "fetch_ms": report.fetch_ms,
        "schema_version": report.schema_version,
        "coverage": report.coverage,
        "queries_count": len(report.queries),
    })

    for q in report.queries:
        if q.status == "ok":
            dump("QuerySuccess — tüm alanlar", {
                "status": q.status,
                "raw_count": q.raw_count,
                "eligible_count": q.eligible_count,
                "offers_count": len(q.offers),
                "first_offer": q.offers[0] if q.offers else None,
                "stops_compare": q.stops_compare,
                "price_insight": q.price_insight,
                "empty_reason": q.empty_reason,
                "page_errors_count": len(q.page_errors),
                "nearby_dates": q.nearby_dates,
            })
        else:
            err = q.error
            dump("QueryFailure", {
                "status": q.status,
                "error_code": getattr(err.code, "value", str(err.code)),
                "error_message": err.message,
                "rate_limited": err.rate_limited,
                "retry_until": err.retry_until,
            })
except Exception as e:
    print(f"TEST 1 HATA: {type(e).__name__}: {e}")


# Rate limit için bekle
print("\n15 saniye bekleniyor (rate limit)...")
time.sleep(15)


# ============================================================
# 2. search_flex — ±3 gün esnek tarama
# ============================================================
print("\n### TEST 2: search_flex (IST-BCN 2027-01-15 ±3 gün) ###")
try:
    flex = search_flex(
        origin="IST", destination="BCN",
        around=date(2027, 1, 15), flex_days=3,
        currency="TRY", max_stops=1, top=3,
    )
    dump("FlexSearchReport (üst seviye)", {
        "searched_at": flex.searched_at,
        "origin": flex.origin,
        "destination": flex.destination,
        "around": flex.around,
        "flex_days": flex.flex_days,
        "start_date": flex.start_date,
        "end_date": flex.end_date,
        "chosen_date": flex.chosen_date,
        "return_date": flex.return_date,
        "currency": flex.currency,
        "offers_count": len(flex.offers),
        "stops_compare": flex.stops_compare,
        "typical": flex.typical,
        "vs_typical": flex.vs_typical,
        "days_count": len(flex.days),
        "first_3_days": flex.days[:3] if flex.days else None,
        "error": flex.error,
    })
except Exception as e:
    print(f"TEST 2 HATA: {type(e).__name__}: {e}")
