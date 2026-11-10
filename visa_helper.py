import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
VISA_FILE = os.path.join(BASE_DIR, "data", "visa_data.json")


def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Config yüklenemedi ({path}): {e}")
        return default if default is not None else {}


# Config dosyalarını yükle
AIRPORTS = _load_json(os.path.join(CONFIG_DIR, "airports.json"))
COUNTRIES = _load_json(os.path.join(CONFIG_DIR, "countries.json"))
COUNTRY_NAMES_EN = _load_json(os.path.join(CONFIG_DIR, "country_names_en.json"))


# Travel Buddy Vize Verisini Yükle
VISA_MAP = {"green": set(), "blue": set(), "yellow": set(), "red": set()}
if os.path.exists(VISA_FILE):
    try:
        with open(VISA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            colors = data.get("data", {}).get("colors", {})
            for color in ["green", "blue", "yellow", "red"]:
                if color in colors:
                    VISA_MAP[color] = set(c.strip() for c in colors[color].split(",") if c.strip())
    except Exception as e:
        print(f"Vize verisi yüklenemedi: {e}")


def _get_visa_string_by_iso(iso2):
    if not iso2:
        return "❔ Bilinmiyor"
    if iso2 in VISA_MAP["green"]: return "🟢 Vizesiz"
    if iso2 in VISA_MAP["blue"]: return "🔵 e-Vize/Kapıda"
    if iso2 in VISA_MAP["yellow"]: return "🟡 eTA"
    if iso2 in VISA_MAP["red"]: return "🔴 Vize Gerekli"
    return "⚪ Bilinmiyor"


def get_visa_by_country_name(country_name):
    """Swoop için: İngilizce ülke isminden vize durumu."""
    iso2 = COUNTRY_NAMES_EN.get(country_name)
    return _get_visa_string_by_iso(iso2)


def get_visa_by_iata(iata_code):
    """Telegram Bot için: IATA kodundan vize + Türkçe ülke adı."""
    iso2 = AIRPORTS.get(iata_code.upper())
    if not iso2:
        return "❔ Bilinmiyor"
    name = COUNTRIES.get(iso2, iso2)
    visa_text = _get_visa_string_by_iso(iso2)
    return f"{visa_text} ({name})"
