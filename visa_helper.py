import os
import re
import json
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
VISA_FILE = os.path.join(BASE_DIR, "data", "visa_data.json")
ISO_CODES_FILE = os.path.join(CONFIG_DIR, "iso_codes.json")


def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Config yüklenemedi ({path}): {e}")
        return default if default is not None else {}


AIRPORTS = _load_json(os.path.join(CONFIG_DIR, "airports.json"))
COUNTRIES = _load_json(os.path.join(CONFIG_DIR, "countries.json"))
COUNTRY_NAMES_EN = _load_json(os.path.join(CONFIG_DIR, "country_names_en.json"))
ISO_CODES = _load_json(ISO_CODES_FILE)


# ─── Vize verisi ────────────────────────────────────────────────────
VISA_MAP = {"green": set(), "blue": set(), "yellow": set(), "red": set()}
VISA_DETAILS = {}
VISA_LOADED = False

if os.path.exists(VISA_FILE):
    try:
        with open(VISA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            colors = data.get("data", {}).get("colors", {})
            for color in ["green", "blue", "yellow", "red"]:
                if color in colors:
                    VISA_MAP[color] = set(c.strip() for c in colors[color].split(",") if c.strip())
            VISA_DETAILS = data.get("data", {}).get("details", {})
        VISA_LOADED = any(VISA_MAP[c] for c in VISA_MAP)
    except Exception as e:
        print(f"Vize verisi yüklenemedi: {e}")

if not VISA_LOADED:
    print("🚨 KRİTİK: visa_data.json boş/eksik. Tüm deal'ler reddedilecek!")


# ─── Normalize ──────────────────────────────────────────────────────
def _normalize(name):
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_name.lower().replace(",", " ").split())


_NORMALIZED_COUNTRY_MAP = {_normalize(k): v for k, v in COUNTRY_NAMES_EN.items()}


# ─── Temel string ───────────────────────────────────────────────────
def _get_visa_string_by_iso(iso2):
    if not iso2:
        return "❔ Bilinmiyor"
    iso2 = iso2.upper()
    if iso2 in VISA_MAP["green"]: return "🟢 Vizesiz"
    if iso2 in VISA_MAP["blue"]: return "🔵 e-Vize/Kapıda"
    if iso2 in VISA_MAP["yellow"]: return "🟡 eTA"
    if iso2 in VISA_MAP["red"]: return "🔴 Vize Gerekli"
    return "⚪ Bilinmiyor"


def get_visa_by_country_name(country_name):
    if not country_name:
        return "❔ Bilinmiyor"
    iso2 = COUNTRY_NAMES_EN.get(country_name) or _NORMALIZED_COUNTRY_MAP.get(_normalize(country_name))
    return _get_visa_string_by_iso(iso2)


def get_visa_by_iata(iata_code):
    iso2 = AIRPORTS.get(iata_code.upper())
    if not iso2:
        return "❔ Bilinmiyor"
    name = COUNTRIES.get(iso2, iso2)
    return f"{_get_visa_string_by_iso(iso2)} ({name})"


def get_iso_by_country_name(country_name):
    if not country_name:
        return None
    iso2 = COUNTRY_NAMES_EN.get(country_name) or _NORMALIZED_COUNTRY_MAP.get(_normalize(country_name))
    if not iso2:
        print(f"    ⚠️ Bilinmeyen ülke: {country_name!r}", flush=True)
    return iso2


def get_iso_by_iata(iata_code):
    if not iata_code:
        return None
    return AIRPORTS.get(iata_code.upper())


# ─── Duration / validity parse ──────────────────────────────────────
_DURATION_RE = re.compile(r"(\d+)\s*(day|days|month|months|year|years)", re.I)


def _parse_duration_days(text):
    if not text:
        return None
    t = text.lower()
    if "period of stay" in t or "valid on arrival" in t:
        return None
    total = 0
    for n, unit in _DURATION_RE.findall(t):
        n = int(n)
        u = unit.lower()
        if u.startswith("day"):
            total += n
        elif u.startswith("month"):
            total += n * 30
        elif u.startswith("year"):
            total += n * 365
    return total or None


def _parse_validity_warning(text):
    if not text:
        return None
    t = text.lower()
    if "period of stay" in t:
        return "Seyahat süresi kadar geçerli"
    if "valid on arrival" in t:
        return "Varışta geçerli yeterli"
    if "longer than" in t:
        m = re.search(r"(\d+)\s*(month|day|year)", t)
        if m:
            n, u = m.group(1), m.group(2).lower()
            unit_tr = {"day": "gün", "month": "ay", "year": "yıl"}[u]
            return f"Seyahat + {n} {unit_tr} geçerli olmalı"
    m = re.search(r"(\d+)\s*(month|day|year)", t)
    if m:
        n, u = m.group(1), m.group(2).lower()
        unit_tr = {"day": "gün", "month": "ay", "year": "yıl"}[u]
        return f"En az {n} {unit_tr} geçerli olmalı"
    return text


# ─── Detaylı vize bilgisi (FALLBACK'Lİ) ─────────────────────────────
def get_visa_details(iso2, trip_days=None):
    if not iso2:
        return None
    iso2 = iso2.upper()

    d = VISA_DETAILS.get(iso2)

    # FALLBACK: Detay yok ama renk map'te var → sadece renkle karar ver
    if not d:
        for color in ("green", "yellow", "blue", "red"):
            if iso2 in VISA_MAP.get(color, set()):
                name_map = {
                    "green": "Visa not required",
                    "yellow": "eTA",
                    "blue": "eVisa/VOA",
                    "red": "Visa required",
                }
                return {
                    "primary": {"name": name_map[color], "color": color, "duration": None},
                    "secondary": {},
                    "color": color,
                    "name": name_map[color],
                    "duration": None,
                    "link": None,
                    "passport_validity": None,
                    "warnings": ["⚠️ Detay verisi yok, sadece renk bilgisi"],
                    "regs": [],
                    "exceptions": [],
                    "continent": None,
                    "currency_code": None,
                }
        return None  # Ne detay ne renk — gerçekten bilinmiyor

    # Tam detay var — normal akış
    primary = d.get("primary_rule", {}) or {}
    secondary = d.get("secondary_rule") or {}
    warnings = []

    if trip_days:
        max_days = 0
        for rule in (primary, secondary):
            if not rule:
                continue
            dur = _parse_duration_days(rule.get("duration"))
            if dur and dur > max_days:
                max_days = dur
        if max_days and trip_days > max_days:
            warnings.append(f"⚠️ Vize {max_days}g, trip {trip_days}g — yetersiz olabilir")

    regs = d.get("mandatory_registrations", [])
    names = [r.get("name", "?") for r in regs if r.get("name")]
    if names:
        warnings.append(f"📋 Zorunlu: {', '.join(names)}")

    validity_warning = _parse_validity_warning(d.get("passport_validity"))
    if validity_warning:
        warnings.append(f"🛡️ Pasaport: {validity_warning}")

    exceptions = d.get("exception_rules", [])

    return {
        "primary": primary,
        "secondary": secondary,
        "color": primary.get("color"),
        "name": primary.get("name"),
        "duration": primary.get("duration") or secondary.get("duration"),
        "link": primary.get("link") or secondary.get("link"),
        "passport_validity": d.get("passport_validity"),
        "warnings": warnings,
        "regs": regs,
        "exceptions": exceptions,
        "continent": d.get("continent"),
        "currency_code": d.get("currency_code"),
    }


def is_visa_acceptable(iso2):
    """Green/Yellow/Blue → kabul. Red ama ETA/e-Vize/online → kabul. Gerçek red → filtrele."""
    details = get_visa_details(iso2)   # fallback otomatik
    if not details:
        return False, "bilinmeyen kod"

    color = details.get("color")
    name = (details.get("name") or "").lower()
    duration = (details.get("duration") or "").lower()

    if color in ("green", "yellow", "blue"):
        return True, color

    if color == "red":
        if any(k in name for k in ("online", "evisa", "e-visa", "eta", "electronic")):
            return True, "red-eta"
        if re.search(r"180|6\s*month", duration):
            return True, "red-eta"
        return False, "vize gerekli"

    return False, f"bilinmeyen: {color}"


def visa_priority(iso2):
    acceptable, kind = is_visa_acceptable(iso2)
    if not acceptable:
        return 9
    return {"green": 0, "yellow": 1, "blue": 2, "red-eta": 3}.get(kind, 9)
