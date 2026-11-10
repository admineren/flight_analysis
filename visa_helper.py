import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VISA_FILE = os.path.join(BASE_DIR, "data", "visa_data.json")

# 1. Swoop için: İngilizce Ülke İsmi -> ISO2 Kodu
COUNTRY_NAME_TO_ISO = {
    "Afghanistan": "AF", "Albania": "AL", "Algeria": "DZ", "Andorra": "AD", "Angola": "AO",
    "Antigua and Barbuda": "AG", "Argentina": "AR", "Armenia": "AM", "Australia": "AU",
    "Austria": "AT", "Azerbaijan": "AZ", "Bahamas": "BS", "Bahrain": "BH", "Bangladesh": "BD",
    "Barbados": "BB", "Belarus": "BY", "Belgium": "BE", "Belize": "BZ", "Benin": "BJ",
    "Bhutan": "BT", "Bolivia": "BO", "Bosnia and Herzegovina": "BA", "Botswana": "BW",
    "Brazil": "BR", "Brunei": "BN", "Bulgaria": "BG", "Burkina Faso": "BF", "Burundi": "BI",
    "Cambodia": "KH", "Cameroon": "CM", "Canada": "CA", "Cape Verde": "CV",
    "Central African Republic": "CF", "Chad": "TD", "Chile": "CL", "China": "CN",
    "Colombia": "CO", "Comoros": "KM", "Congo": "CG", "Congo (Dem. Rep.)": "CD",
    "Costa Rica": "CR", "Cote d'Ivoire": "CI", "Croatia": "HR", "Cuba": "CU", "Cyprus": "CY",
    "Czech Republic": "CZ", "Czechia": "CZ", "Denmark": "DK", "Djibouti": "DJ",
    "Dominica": "DM", "Dominican Republic": "DO", "Ecuador": "EC", "Egypt": "EG",
    "El Salvador": "SV", "Equatorial Guinea": "GQ", "Eritrea": "ER", "Estonia": "EE",
    "Eswatini": "SZ", "Ethiopia": "ET", "Fiji": "FJ", "Finland": "FI", "France": "FR",
    "Gabon": "GA", "Gambia": "GM", "Georgia": "GE", "Germany": "DE", "Ghana": "GH",
    "Greece": "GR", "Grenada": "GD", "Guatemala": "GT", "Guinea": "GN", "Guinea-Bissau": "GW",
    "Guyana": "GY", "Haiti": "HT", "Honduras": "HN", "Hong Kong": "HK", "Hungary": "HU",
    "Iceland": "IS", "India": "IN", "Indonesia": "ID", "Iran": "IR", "Iraq": "IQ",
    "Ireland": "IE", "Israel": "IL", "Italy": "IT", "Jamaica": "JM", "Japan": "JP",
    "Jordan": "JO", "Kazakhstan": "KZ", "Kenya": "KE", "Kiribati": "KI", "Kosovo": "XK",
    "Kuwait": "KW", "Kyrgyzstan": "KG", "Laos": "LA", "Latvia": "LV", "Lebanon": "LB",
    "Lesotho": "LS", "Liberia": "LR", "Libya": "LY", "Liechtenstein": "LI",
    "Lithuania": "LT", "Luxembourg": "LU", "Macau": "MO", "Madagascar": "MG",
    "Malawi": "MW", "Malaysia": "MY", "Maldives": "MV", "Mali": "ML", "Malta": "MT",
    "Marshall Islands": "MH", "Mauritania": "MR", "Mauritius": "MU", "Mexico": "MX",
    "Micronesia": "FM", "Moldova": "MD", "Monaco": "MC", "Mongolia": "MN",
    "Montenegro": "ME", "Morocco": "MA", "Mozambique": "MZ", "Myanmar": "MM",
    "Namibia": "NA", "Nauru": "NR", "Nepal": "NP", "Netherlands": "NL",
    "New Zealand": "NZ", "Nicaragua": "NI", "Niger": "NE", "Nigeria": "NG",
    "North Korea": "KP", "North Macedonia": "MK", "Norway": "NO", "Oman": "OM",
    "Pakistan": "PK", "Palau": "PW", "Palestinian Territories": "PS", "Panama": "PA",
    "Papua New Guinea": "PG", "Paraguay": "PY", "Peru": "PE", "Philippines": "PH",
    "Poland": "PL", "Portugal": "PT", "Qatar": "QA", "Romania": "RO", "Russia": "RU",
    "Russian Federation": "RU", "Rwanda": "RW", "Saint Kitts and Nevis": "KN",
    "Saint Lucia": "LC", "Saint Vincent and the Grenadines": "VC", "Samoa": "WS",
    "San Marino": "SM", "Sao Tome and Principe": "ST", "Saudi Arabia": "SA",
    "Senegal": "SN", "Serbia": "RS", "Seychelles": "SC", "Sierra Leone": "SL",
    "Singapore": "SG", "Slovakia": "SK", "Slovenia": "SI", "Solomon Islands": "SB",
    "Somalia": "SO", "South Africa": "ZA", "South Korea": "KR", "South Sudan": "SS",
    "Spain": "ES", "Sri Lanka": "LK", "Sudan": "SD", "Suriname": "SR", "Sweden": "SE",
    "Switzerland": "CH", "Syria": "SY", "Taiwan": "TW", "Tajikistan": "TJ",
    "Tanzania": "TZ", "Thailand": "TH", "Timor-Leste": "TL", "Togo": "TG",
    "Tonga": "TO", "Trinidad and Tobago": "TT", "Tunisia": "TN", "Turkey": "TR",
    "Türkiye": "TR", "Turkmenistan": "TM", "Tuvalu": "TV", "Uganda": "UG",
    "Ukraine": "UA", "United Arab Emirates": "AE", "United Kingdom": "GB",
    "United States": "US", "United States of America": "US", "Uruguay": "UY",
    "Uzbekistan": "UZ", "Vanuatu": "VU", "Vatican City": "VA", "Venezuela": "VE",
    "Vietnam": "VN", "Viet Nam": "VN", "Yemen": "YE", "Zambia": "ZM", "Zimbabwe": "ZW",
}

# 2. Telegram Bot için: IATA Kodu -> ISO2 Kodu
IATA_TO_ISO = {
    "IST": "TR", "SAW": "TR", "BKK": "TH", "DPS": "ID", "KUL": "MY", "SIN": "SG",
    "HKG": "HK", "HAN": "VN", "SGN": "VN", "MNL": "PH", "TBS": "GE", "GYD": "AZ",
    "BEG": "RS", "SJJ": "BA", "MSQ": "BY", "DXB": "AE", "AUH": "AE", "SHJ": "AE",
    "DOH": "QA", "RUH": "SA", "AMM": "JO", "BEY": "LB", "CAI": "EG", "SSH": "EG",
    "CMN": "MA", "TNG": "MA", "LHR": "GB", "CDG": "FR", "FRA": "DE", "AMS": "NL",
    "FCO": "IT", "MAD": "ES", "BCN": "ES", "ATH": "GR", "BSL": "CH", "ZRH": "CH",
    "JFK": "US", "LAX": "US", "NRT": "JP", "HND": "JP", "ICN": "KR", "PEK": "CN",
    "PVG": "CN", "TPE": "TW", "DEL": "IN"
}

# 3. Ülke isimleri (Telegram çıktılarında Türkçe göstermek için)
ISO_TO_NAME_TR = {
    "TR": "Türkiye", "TH": "Tayland", "ID": "Endonezya", "MY": "Malezya", "SG": "Singapur",
    "HK": "Hong Kong", "VN": "Vietnam", "PH": "Filipinler", "GE": "Gürcistan",
    "AZ": "Azerbaycan", "RS": "Sırbistan", "BA": "Bosna-Hersek", "BY": "Belarus",
    "AE": "BAE", "QA": "Katar", "SA": "Suudi Arabistan", "JO": "Ürdün", "EG": "Mısır",
    "MA": "Fas", "GB": "İngiltere", "FR": "Fransa", "DE": "Almanya", "NL": "Hollanda",
    "IT": "İtalya", "ES": "İspanya", "GR": "Yunanistan", "CH": "İsviçre",
    "US": "ABD", "JP": "Japonya", "KR": "Güney Kore", "CN": "Çin", "TW": "Tayvan", "IN": "Hindistan"
}

# 4. Travel Buddy Vize Verisini Yükle
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
    """ISO koduna göre vize metnini döndürür."""
    if not iso2:
        return "❔ Bilinmiyor"
    if iso2 in VISA_MAP["green"]: return "🟢 Vizesiz"
    if iso2 in VISA_MAP["blue"]: return "🔵 e-Vize/Kapıda"
    if iso2 in VISA_MAP["yellow"]: return "🟡 eTA"
    if iso2 in VISA_MAP["red"]: return "🔴 Vize Gerekli"
    return "⚪ Bilinmiyor"


def get_visa_by_country_name(country_name):
    """Swoop API'si için: İngilizce ülke isminden vize durumu."""
    iso2 = COUNTRY_NAME_TO_ISO.get(country_name)
    return _get_visa_string_by_iso(iso2)


def get_visa_by_iata(iata_code):
    """Telegram Bot için: IATA kodundan vize durumu + Türkçe ülke adı."""
    iso2 = IATA_TO_ISO.get(iata_code.upper())
    if not iso2:
        return "❔ Bilinmiyor"
    name = ISO_TO_NAME_TR.get(iso2, iso2)
    visa_text = _get_visa_string_by_iso(iso2)
    return f"{visa_text} ({name})"
