"""
TCMB kur + set_country("TR") testi.
- TCMB'den güncel USD/TRY kuru çeker
- set_country öncesi/sonrası fiyatları karşılaştırır
- Hangi para biriminde geldiğini tespit eder
Telegram'a mesaj GÖNDERMEZ.
"""
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from swoop import search as swoop_search, deals, set_country


# ============================================================
# 1. TCMB KUR ÇEKME
# ============================================================
print("=" * 70)
print("1. TCMB USD/TRY KURU")
print("=" * 70)

def get_usd_tl_tcmb():
    try:
        r = requests.get(
            "https://www.tcmb.gov.tr/kurlar/today.xml",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            # USD Currency bloğunu bul
            match = re.search(
                r'<Currency[^>]*CurrencyCode="USD"[^>]*>(.*?)</Currency>',
                r.text, re.DOTALL
            )
            if match:
                block = match.group(1)
                forex_buying = re.search(r"<ForexBuying>([\d.]+)</ForexBuying>", block)
                forex_selling = re.search(r"<ForexSelling>([\d.]+)</ForexSelling>", block)
                return {
                    "buying": float(forex_buying.group(1)) if forex_buying else None,
                    "selling": float(forex_selling.group(1)) if forex_selling else None,
                    "source": "TCMB",
                }
        return {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}

tcmb = get_usd_tl_tcmb()
print(f"TCMB sonucu: {tcmb}")

# Alternatif: exchangerate API (fallback)
def get_usd_tl_fallback():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("rates", {}).get("TRY")
    except Exception as e:
        print(f"  fallback hata: {e}")
    return None

fallback = get_usd_tl_fallback()
print(f"Exchangerate-API: {fallback} TL")


# ============================================================
# 2. SET_COUNTRY TESTİ
# ============================================================
print("\n" + "=" * 70)
print("2. SET_COUNTRY TESTİ")
print("=" * 70)

# Test rotası (Tiflis)
ORIGIN = "IST"
DEST = "TBS"
today = datetime.now(timezone.utc).date()
depart = today + timedelta(days=60)
ret = depart + timedelta(days=5)

print(f"Test rotası: {ORIGIN} → {DEST}")
print(f"Tarih: {depart} → {ret}\n")

# --- A) Ülke ayarlanmadan (default) ---
print("--- A) Default ülke (ayarlanmamış) ---")
try:
    out_default = swoop_search(ORIGIN, DEST, str(depart))
    time.sleep(2)
    ret_default = swoop_search(DEST, ORIGIN, str(ret))

    if out_default.results and ret_default.results:
        out_prices = [opt.price for opt in out_default.results if opt.price]
        ret_prices = [opt.price for opt in ret_default.results if opt.price]

        out_min = min(out_prices) if out_prices else None
        ret_min = min(ret_prices) if ret_prices else None
        total_default = (out_min + ret_min) if (out_min and ret_min) else None

        # Para birimi bilgisi (TripOption'da currency var mı?)
        first_opt = out_default.results[0]
        currency = getattr(first_opt, "currency", None)

        print(f"  Gidiş min: {out_min} {currency or '?'}")
        print(f"  Dönüş min: {ret_min} {currency or '?'}")
        print(f"  Toplam: {total_default} {currency or '?'}")
        print(f"  Para birimi (TripOption.currency): {currency}")
        print(f"  Toplam seçenek: {len(out_prices)} + {len(ret_prices)}")
    else:
        print("  Sonuç yok")
        total_default = None
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {str(e)[:150]}")
    total_default = None

time.sleep(3)

# --- B) set_country("TR") ile ---
print("\n--- B) set_country('TR') ---")
try:
    set_country("TR")
    print("  set_country('TR') çağrıldı")

    time.sleep(2)
    out_tr = swoop_search(ORIGIN, DEST, str(depart))
    time.sleep(2)
    ret_tr = swoop_search(DEST, ORIGIN, str(ret))

    if out_tr.results and ret_tr.results:
        out_prices = [opt.price for opt in out_tr.results if opt.price]
        ret_prices = [opt.price for opt in ret_tr.results if opt.price]

        out_min = min(out_prices) if out_prices else None
        ret_min = min(ret_prices) if ret_prices else None
        total_tr = (out_min + ret_min) if (out_min and ret_min) else None

        first_opt = out_tr.results[0]
        currency = getattr(first_opt, "currency", None)

        print(f"  Gidiş min: {out_min} {currency or '?'}")
        print(f"  Dönüş min: {ret_min} {currency or '?'}")
        print(f"  Toplam: {total_tr} {currency or '?'}")
        print(f"  Para birimi: {currency}")
        print(f"  Toplam seçenek: {len(out_prices)} + {len(ret_prices)}")
    else:
        print("  Sonuç yok")
        total_tr = None
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {str(e)[:150]}")
    total_tr = None


# ============================================================
# 3. KARŞILAŞTIRMA
# ============================================================
print("\n" + "=" * 70)
print("3. KARŞILAŞTIRMA (default vs TR)")
print("=" * 70)

if total_default and total_tr:
    print(f"  Default: {total_default}")
    print(f"  TR:      {total_tr}")

    if total_default == total_tr:
        print("  ➡️ AYNI fiyat — set_country fiyatları etkilemiyor (cache veya currency farkı yok)")
    elif total_tr < total_default:
        diff_pct = (total_default - total_tr) / total_default * 100
        print(f"  ➡️ TR DAHA UCUZ: %{diff_pct:.1f} azaldı")
    else:
        diff_pct = (total_tr - total_default) / total_default * 100
        print(f"  ➡️ TR DAHA PAHALI: %{diff_pct:.1f} arttı")
else:
    print("  Karşılaştırma için yeterli veri yok")


# ============================================================
# 4. DEALS ÜZERİNDE SET_COUNTRY ETKİSİ
# ============================================================
print("\n" + "=" * 70)
print("4. DEALS ÜZERİNDE SET_COUNTRY ETKİSİ")
print("=" * 70)

# TR ayarlı, deals çağır
time.sleep(3)
print("\n--- set_country('TR') ile deals ---")
try:
    tr_deals = deals("IST")
    print(f"  Toplam deal: {len(tr_deals.deals)}")

    # İlk 5 deal'in para birimini göster
    for d in tr_deals.deals[:5]:
        currency = getattr(d, "currency", None)
        print(f"    • {d.destination_city} — ${d.price} {currency or '?'} (%{d.discount_pct})")

    if tr_deals.deals:
        first_currency = getattr(tr_deals.deals[0], "currency", None)
        print(f"\n  Deal.currency: {first_currency}")
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {str(e)[:150]}")


# ============================================================
# 5. ÖZET VE ÖNERİ
# ============================================================
print("\n" + "=" * 70)
print("5. ÖZET")
print("=" * 70)

print(f"\nTCMB USD/TRY:")
if tcmb.get("selling"):
    print(f"  Satış: {tcmb['selling']}")
if tcmb.get("buying"):
    print(f"  Alış:  {tcmb['buying']}")
if tcmb.get("error"):
    print(f"  Hata: {tcmb['error']}")
if fallback:
    print(f"  Fallback (exchangerate-api): {fallback}")

print(f"\nset_country('TR') etkisi:")
if total_default and total_tr:
    if total_default == total_tr:
        print("  ❌ Etki yok — set_country işe yaramıyor, default ülke ile çalışmaya devam")
    else:
        print(f"  ✅ Etki var: {total_default} → {total_tr}")
else:
    print("  ⚠️ Karşılaştırma yapılamadı")

print("\n=== Test tamamlandı ===")
