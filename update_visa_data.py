"""
update_visa_data.py — Travel Buddy Visa API'sinden vize verisi çeker.

Modlar:
  --mode=full     : passports_list + map + (TÜM veya seçili) ülkeler için check
  --mode=refresh  : passports_list + map + SADECE renk değişenler için check
  --mode=map-only : sadece passports_list + map

Kullanım (GitHub Actions):
  --mode=full --countries=TH           → sadece Tayland
  --mode=full --countries=TH,GE,AZ     → 3 ülke
  --mode=full                          → tüm ülkeler (PRO)
  --mode=refresh                       → sadece değişenler
  --mode=map-only                      → en ucuz
"""

import os
import sys
import json
import time
import html
import argparse
import re
import requests
from datetime import datetime, timezone

# ─── Sabitler ──────────────────────────────────────────────────────
DATA_DIR = "data"
VISA_FILE = os.path.join(DATA_DIR, "visa_data.json")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
RAPIDAPI_HOST = "visa-requirement.p.rapidapi.com"
PASSPORT = "TR"
BASE_URL = f"https://{RAPIDAPI_HOST}"

HEADERS = {
    "Content-Type": "application/json",
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST,
}

CHECK_SLEEP = 0.3  # her check arası bekleme


# ─── Yardımcılar ───────────────────────────────────────────────────
def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _load_json():
    default = {
        "data": {"passport": PASSPORT, "passports_list": [], "colors": {}, "details": {}},
        "meta": {"version": "3.0"},
    }
    if not os.path.exists(VISA_FILE):
        return default
    try:
        with open(VISA_FILE, encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("data", {}).setdefault("passports_list", [])
        d["data"].setdefault("colors", {})
        d["data"].setdefault("details", {})
        d.setdefault("meta", {})["version"] = "3.0"
        return d
    except Exception as e:
        print(f"⚠️ JSON okunamadı ({e}), yeni başlanıyor.")
        return default


def _save_atomic(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = VISA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VISA_FILE)


def _clean_text(text):
    if not text:
        return text
    return re.sub(r"<[^>]*>", "", html.unescape(text)).strip()


def _validate_map(colors):
    if not colors:
        return False
    min_counts = {"green": 30, "blue": 30, "red": 30}
    for c, min_n in min_counts.items():
        n = len([x for x in (colors.get(c) or "").split(",") if x.strip()])
        if n < min_n:
            print(f"❌ Doğrulama: '{c}' beklenenden az ({n} < {min_n})")
            return False
    return True


# ─── API Çağrıları ─────────────────────────────────────────────────
def fetch_passports_list():
    """GET /v2/passports → 213 ülke listesi (1 istek)."""
    print("📋 Ülke listesi çekiliyor (/v2/passports)...", end=" ", flush=True)
    try:
        r = requests.get(f"{BASE_URL}/v2/passports", headers=HEADERS, timeout=30)
        r.raise_for_status()
        items = r.json().get("data", [])
        result = [
            {"iso2": x["iso_alpha2"], "iso3": x["iso_alpha3"], "name": x["name"]}
            for x in items
        ]
        print(f"✅ {len(result)} ülke")
        return result
    except Exception as e:
        print(f"❌ {e}")
        return None


def fetch_map():
    """POST /v2/visa/map → 213 ülke rengi (1 istek)."""
    print("🗺️  Renk haritası çekiliyor (/v2/visa/map)...", end=" ", flush=True)
    try:
        r = requests.post(
            f"{BASE_URL}/v2/visa/map", headers=HEADERS,
            json={"passport": PASSPORT}, timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        colors = body.get("data", {}).get("colors", {})
        if not _validate_map(colors):
            print("❌ Sağlıksız yanıt")
            return None
        # TR'yi her renkten çıkar
        for c in colors:
            colors[c] = ",".join(
                x for x in colors[c].split(",") if x.strip() and x.strip() != PASSPORT
            )
        total = sum(len([x for x in colors[c].split(",") if x.strip()]) for c in colors)
        print(f"✅ {total} ülke renklendirildi")
        return colors
    except Exception as e:
        print(f"❌ {e}")
        return None


def fetch_check(iso2):
    """POST /v2/visa/check → 1 ülkenin tüm detayı (1 istek)."""
    try:
        r = requests.post(
            f"{BASE_URL}/v2/visa/check", headers=HEADERS,
            json={"passport": PASSPORT, "destination": iso2}, timeout=30,
        )
        if r.status_code == 429:
            print("⚠️ 429 rate limit", end=" ")
            return "RATE_LIMIT"
        if r.status_code == 404:
            return None
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            print(f"⚠️ {body.get('message', '?')}", end=" ")
            return None
        return body.get("data", {})
    except requests.RequestException as e:
        print(f"❌ {e}", end=" ")
        return None


def _extract_detail(iso2, raw, color, fetched_at):
    """API yanıtından JSON'a saklanacak alanları çıkar."""
    rules = raw.get("visa_rules", {})
    primary = rules.get("primary_rule", {}) or {}
    secondary = rules.get("secondary_rule")

    def _clean_rule(r):
        if not r:
            return None
        return {
            "name": r.get("name"),
            "duration": r.get("duration"),
            "color": r.get("color"),
            "link": r.get("link"),
            "note": _clean_text(r.get("note")),
        }

    exceptions = []
    for ex in rules.get("exception_rules", []) or []:
        exceptions.append({
            "number": ex.get("number"),
            "name": ex.get("name"),
            "type": ex.get("type", []),
            "exception_type_name": ex.get("exception_type_name"),
            "duration": ex.get("duration"),
            "color": ex.get("color"),
            "all_country_codes": ex.get("all_country_codes", []),
            "age_min": ex.get("age_min"),
            "age_max": ex.get("age_max"),
            "link": ex.get("link"),
            "note": _clean_text(ex.get("note")),
        })

    regs = []
    for reg in raw.get("mandatory_registrations", []) or []:
        regs.append({
            "name": reg.get("name"),
            "duration": reg.get("duration"),
            "link": reg.get("link"),
            "note": _clean_text(reg.get("note")),
        })

    dest = raw.get("destination", {}) or {}

    return {
        "fetched_at": fetched_at,
        "color_at_fetch": color,
        "primary_rule": _clean_rule(primary),
        "secondary_rule": _clean_rule(secondary),
        "exception_rules": exceptions,
        "mandatory_registrations": regs,
        "passport_validity": dest.get("passport_validity"),
        "embassy_url": dest.get("embassy_url"),
        "continent": dest.get("continent"),
        "currency_code": dest.get("currency_code"),
    }


# ─── Modlar ────────────────────────────────────────────────────────
def mode_map_only(data):
    """passports_list + map."""
    pl = fetch_passports_list()
    if pl is None:
        return False
    data["data"]["passports_list"] = pl
    data["meta"]["passports_list_fetched_at"] = _now_iso()

    colors = fetch_map()
    if colors is None:
        return False
    data["data"]["colors"] = colors
    data["meta"]["map_fetched_at"] = _now_iso()
    return True


def mode_full(data, max_count=None, only_countries=None):
    """passports_list + map + (TÜM veya seçili) ülkeler için check."""
    if not mode_map_only(data):
        return False
    _save_atomic(data)  # kısmi kayıt

    # Renk indeksi
    color_index = {}
    for c in ("green", "blue", "yellow", "red"):
        for x in (data["data"]["colors"].get(c) or "").split(","):
            x = x.strip()
            if x:
                color_index[x] = c

    targets = []
    if only_countries:
        for iso2 in only_countries:
            if iso2 in color_index:
                targets.append((iso2, color_index[iso2]))
            else:
                print(f"⚠️ {iso2} renk haritasında yok, atlanıyor")
    else:
        for color in ("green", "blue", "yellow", "red"):
            codes = [c.strip() for c in (data["data"]["colors"].get(color) or "").split(",") if c.strip()]
            for c in codes:
                targets.append((c, color))

    if max_count:
        targets = targets[:max_count]

    print(f"\n🎯 {len(targets)} ülke için detay çekilecek")
    details = data["data"]["details"]
    fetched = 0
    rate_limited = False

    for i, (iso2, color) in enumerate(targets, 1):
        print(f"  [{i}/{len(targets)}] {iso2} ({color})...", end=" ", flush=True)
        raw = fetch_check(iso2)
        if raw == "RATE_LIMIT":
            rate_limited = True
            print("DURDU")
            break
        if raw is None:
            print("atlandı")
            continue

        details[iso2] = _extract_detail(iso2, raw, color, _now_iso())
        fetched += 1
        rule = details[iso2]["primary_rule"] or {}
        print(f"✅ {rule.get('name', '?')} ({rule.get('duration', '-')})")

        if fetched % 10 == 0:
            _save_atomic(data)
        time.sleep(CHECK_SLEEP)

    data["meta"]["details_stats"] = {
        "total": len(targets),
        "fetched_total": len(details),
        "fetched_this_run": fetched,
        "remaining": max(0, len(targets) - fetched),
        "last_run_at": _now_iso(),
        "rate_limited": rate_limited,
    }
    return not rate_limited


def mode_refresh(data):
    """passports_list + map + SADECE renk değişenler için check."""
    old_colors = dict(data["data"].get("colors", {}))

    if not mode_map_only(data):
        return False

    def _index(colors):
        idx = {}
        for c, codes in colors.items():
            for x in (codes or "").split(","):
                x = x.strip()
                if x:
                    idx[x] = c
        return idx

    old_idx = _index(old_colors)
    new_idx = _index(data["data"]["colors"])

    changed = {}
    for iso2 in set(old_idx) | set(new_idx):
        if old_idx.get(iso2) != new_idx.get(iso2):
            changed[iso2] = (old_idx.get(iso2), new_idx.get(iso2))

    if not changed:
        print("\n✅ Renk değişikliği yok.")
        data["meta"]["details_stats"] = {
            "last_refresh_at": _now_iso(),
            "changed": 0,
            "refreshed": 0,
        }
        return True

    print(f"\n🚨 {len(changed)} ülkede renk değişti:")
    emoji = {"green": "🟢", "blue": "🔵", "yellow": "🟡", "red": "🔴", None: "❔"}
    for iso2, (o, n) in changed.items():
        print(f"   • {iso2}: {emoji.get(o, '?')} → {emoji.get(n, '?')}")

    details = data["data"]["details"]
    fetched = 0
    for iso2, (old_c, new_c) in changed.items():
        print(f"  check({iso2})...", end=" ", flush=True)
        raw = fetch_check(iso2)
        if raw == "RATE_LIMIT":
            print("DURDU")
            break
        if raw is None:
            print("atlandı")
            continue
        details[iso2] = _extract_detail(iso2, raw, new_c, _now_iso())
        fetched += 1
        print("✅")
        time.sleep(CHECK_SLEEP)

    data["meta"]["details_stats"] = {
        "last_refresh_at": _now_iso(),
        "changed": len(changed),
        "refreshed": fetched,
    }
    return True


# ─── Main ──────────────────────────────────────────────────────────
def main():
    if not RAPIDAPI_KEY:
        raise SystemExit("❌ RAPIDAPI_KEY ortam değişkeni eksik")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["full", "refresh", "map-only"],
        default=os.environ.get("VISA_MODE", "map-only"),
    )
    parser.add_argument(
        "--countries",
        default=None,
        help="Virgülle ayrılmış ISO kodları (ör. TH,GE,AZ). Boş = tümü (full modda).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Test için max check sayısı",
    )
    args = parser.parse_args()

    print(f"=== Visa Data Update (mode={args.mode}) ===")
    data = _load_json()

    if args.mode == "map-only":
        ok = mode_map_only(data)
    elif args.mode == "full":
        only = None
        if args.countries:
            only = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
            print(f"Seçili ülkeler: {only}")
        ok = mode_full(data, max_count=args.max, only_countries=only)
    elif args.mode == "refresh":
        ok = mode_refresh(data)
    else:
        ok = False

    data["meta"]["generated_at"] = _now_iso()
    _save_atomic(data)

    if not ok:
        raise SystemExit(1)
    print("\n✅ Bitti.")


if __name__ == "__main__":
    main()
