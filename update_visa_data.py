"""
update_visa_data.py — Travel Buddy Visa API'sinden vize verisi çeker.

Modlar:
  --mode=cleanup  : API'siz! Mevcut JSON'u temizler, config/iso_codes.json üretir.
  --mode=full     : map + seçili/tüm ülkeler için check (API)
  --mode=refresh  : map + sadece renk değişenler için check (API)
  --mode=map-only : sadece colors (API)
"""

import os
import json
import time
import html
import argparse
import re
import requests
from datetime import datetime, timezone

# ─── Sabitler ──────────────────────────────────────────────────────
DATA_DIR = "data"
CONFIG_DIR = "config"
VISA_FILE = os.path.join(DATA_DIR, "visa_data.json")
ISO_CODES_FILE = os.path.join(CONFIG_DIR, "iso_codes.json")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
RAPIDAPI_HOST = "visa-requirement.p.rapidapi.com"
PASSPORT = "TR"
BASE_URL = f"https://{RAPIDAPI_HOST}"
SCHEMA_VERSION = "3.1"

HEADERS = {
    "Content-Type": "application/json",
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST,
}

CHECK_SLEEP = 0.3


# ─── Yardımcılar ───────────────────────────────────────────────────
def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _remove_nulls(obj):
    """None/""/[]/{} sil; 0 ve False koru."""
    if isinstance(obj, dict):
        return {
            k: _remove_nulls(v)
            for k, v in obj.items()
            if v is not None and v != "" and v != [] and v != {}
        }
    if isinstance(obj, list):
        return [_remove_nulls(x) for x in obj]
    return obj


def _clean_text(text):
    if not text:
        return None
    return re.sub(r"<[^>]*>", "", html.unescape(text)).strip() or None


def _save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _load_json_file(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ {path} okunamadı: {e}")
        return None


def _load_visa_data():
    d = _load_json_file(VISA_FILE)
    if d is None:
        return {"data": {"passport": PASSPORT, "colors": {}, "details": {}}, "meta": {"version": SCHEMA_VERSION}}
    d.setdefault("data", {}).setdefault("colors", {})
    d["data"].setdefault("details", {})
    d.setdefault("meta", {})["version"] = SCHEMA_VERSION
    return d


def _validate_map(colors):
    if not colors:
        return False
    for c, min_n in {"green": 30, "blue": 30, "red": 30}.items():
        n = len([x for x in (colors.get(c) or "").split(",") if x.strip()])
        if n < min_n:
            print(f"❌ Doğrulama: '{c}' beklenenden az ({n} < {min_n})")
            return False
    return True


# ─── Mod: cleanup (API'siz) ────────────────────────────────────────
def mode_cleanup():
    """
    Mevcut visa_data.json'u temizler:
      - passports_list varsa → config/iso_codes.json'a taşı, JSON'dan sil
      - Her detail'den embassy_url sil
      - Null/boş alanları sil
      - sort_keys=True ile yaz
      - meta.version = 3.1
    Ayrıca config/iso_codes.json dosyasını üretir/günceller.
    """
    print("🧹 Cleanup başlıyor (API isteği YOK)")
    data = _load_visa_data()

    # 1) passports_list → config/iso_codes.json
    pl = data["data"].pop("passports_list", None)
    if pl:
        iso_codes = {
            x["iso2"]: {"iso3": x.get("iso3"), "name": x.get("name")}
            for x in pl
            if x.get("iso2") and x.get("name")
        }
        _save_json(ISO_CODES_FILE, iso_codes)
        print(f"📝 config/iso_codes.json → {len(iso_codes)} ülke (passports_list'ten)")
    else:
        # passports_list yoksa config'ten kontrol et
        existing = _load_json_file(ISO_CODES_FILE)
        if existing:
            print(f"ℹ️  config/iso_codes.json mevcut ({len(existing)} ülke), dokunulmadı")
        else:
            print("⚠️ passports_list de iso_codes.json da yok — iso kodları eksik kalacak")

    # 2) meta'daki passports_list_fetched_at'i de temizle
    data["meta"].pop("passports_list_fetched_at", None)

    # 3) Detayları temizle
    cleaned = 0
    for iso2 in list(data["data"]["details"].keys()):
        old = data["data"]["details"][iso2]
        new = _remove_nulls({k: v for k, v in old.items() if k != "embassy_url"})
        if new != old:
            data["data"]["details"][iso2] = new
            cleaned += 1

    data["meta"]["version"] = SCHEMA_VERSION
    data["meta"]["last_cleanup_at"] = _now_iso()
    _save_json(VISA_FILE, data)

    # Rapor
    detail_count = len(data["data"]["details"])
    print(f"🧹 {cleaned}/{detail_count} detay temizlendi")
    print(f"📦 Yeni visa_data.json boyutu: {os.path.getsize(VISA_FILE) / 1024:.1f} KB")
    if os.path.exists(ISO_CODES_FILE):
        print(f"📦 iso_codes.json boyutu: {os.path.getsize(ISO_CODES_FILE) / 1024:.1f} KB")
    return True


# ─── API Çağrıları ─────────────────────────────────────────────────
def fetch_map():
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
    rules = raw.get("visa_rules", {})
    primary = rules.get("primary_rule", {}) or {}
    secondary = rules.get("secondary_rule")
    dest = raw.get("destination", {}) or {}

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

    detail = {
        "fetched_at": fetched_at,
        "color_at_fetch": color,
        "primary_rule": _clean_rule(primary),
        "secondary_rule": _clean_rule(secondary),
        "exception_rules": exceptions,
        "mandatory_registrations": regs,
        "passport_validity": dest.get("passport_validity"),
        "continent": dest.get("continent"),
        "currency_code": dest.get("currency_code"),
    }
    return _remove_nulls(detail)


# ─── Modlar (API'li) ───────────────────────────────────────────────
def mode_map_only(data):
    colors = fetch_map()
    if colors is None:
        return False
    data["data"]["colors"] = colors
    data["meta"]["map_fetched_at"] = _now_iso()
    return True


def mode_full(data, max_count=None, only_countries=None, skip_map=False):
    if skip_map:
        if not data["data"].get("colors"):
            print("⚠️ --skip-map verildi ama colors boş, map çekiliyor")
            if not mode_map_only(data):
                return False
        else:
            print("⏭️  Map zaten mevcut, skip ediliyor")
    else:
        if not mode_map_only(data):
            return False
    _save_json(VISA_FILE, data)
  
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
            for c in [x.strip() for x in (data["data"]["colors"].get(color) or "").split(",") if x.strip()]:
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
        rule = details[iso2].get("primary_rule", {})
        print(f"✅ {rule.get('name', '?')} ({rule.get('duration', '-')})")
        if fetched % 10 == 0:
            _save_json(VISA_FILE, data)
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
    changed = {i: (old_idx.get(i), new_idx.get(i)) for i in set(old_idx) | set(new_idx) if old_idx.get(i) != new_idx.get(i)}

    if not changed:
        print("\n✅ Renk değişikliği yok.")
        data["meta"]["details_stats"] = {"last_refresh_at": _now_iso(), "changed": 0, "refreshed": 0}
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=["cleanup", "full", "refresh", "map-only"],
        default=os.environ.get("VISA_MODE", "map-only"),
    )
    parser.add_argument("--countries", default=None)
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument(
        "--skip-map", action="store_true",
        help="Map zaten mevcut, yeniden çekme (sadece full modunda etkili)",
    )
    args = parser.parse_args()

    # cleanup API key gerektirmez
    if args.mode == "cleanup":
        print(f"=== Visa Data Cleanup ===")
        ok = mode_cleanup()
        if not ok:
            raise SystemExit(1)
        print("\n✅ Bitti.")
        return

    if not RAPIDAPI_KEY:
        raise SystemExit("❌ RAPIDAPI_KEY ortam değişkeni eksik")

    if args.skip_map and args.mode in ("refresh", "map-only"):
        print(f"⚠️ --skip-map sadece 'full' modunda etkili, '{args.mode}' için görmezden geliniyor")

    print(f"=== Visa Data Update (mode={args.mode}) ===")
    data = _load_visa_data()

    if args.mode == "map-only":
        ok = mode_map_only(data)
    elif args.mode == "full":
        only = None
        if args.countries:
            only = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
            print(f"Seçili ülkeler: {only}")
        ok = mode_full(data, max_count=args.max, only_countries=only, skip_map=args.skip_map)
    elif args.mode == "refresh":
        ok = mode_refresh(data)
    else:
        ok = False

    data["meta"]["generated_at"] = _now_iso()
    _save_json(VISA_FILE, data)

    if not ok:
        raise SystemExit(1)
    print("\n✅ Bitti.")


if __name__ == "__main__":
    main()
