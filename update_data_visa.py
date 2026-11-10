import os
import json
import requests
from datetime import datetime, timedelta

VISA_DATA_FILE = "visa_data.json"
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = "visa-requirement.p.rapidapi.com"
PASSPORT_CODE = "TR"

def update_visa_data():
    if not RAPIDAPI_KEY:
        print("HATA: RAPIDAPI_KEY ortam değişkeni bulunamadı.")
        return

    # Haftada bir güncelleme kontrolü (7 gün geçmediyse atla)
    if os.path.exists(VISA_DATA_FILE):
        mtime = datetime.fromtimestamp(os.path.getmtime(VISA_DATA_FILE))
        if datetime.now() - mtime < timedelta(days=7):
            print(f"Vize verisi güncel (Son güncelleme: {mtime.strftime('%Y-%m-%d %H:%M')}). Atlanıyor.")
            return

    print("Travel Buddy AI'den vize haritası çekiliyor...")
    url = f"https://{RAPIDAPI_HOST}/v2/visa/map"
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    payload = {"passport": PASSPORT_CODE}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Çekilen veriyi kaydet
        with open(VISA_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"Başarılı: Vize verisi {VISA_DATA_FILE} dosyasına kaydedildi.")
        
        # Özet bilgi ver
        colors = data.get("data", {}).get("colors", {})
        print(f"Yeşil (Vizesiz): {len(colors.get('green', '').split(','))} ülke")
        print(f" Mavi (Kapıda/e-Vize): {len(colors.get('blue', '').split(','))} ülke")
        print(f" Sarı (eTA): {len(colors.get('yellow', '').split(','))} ülke")
        print(f" Kırmızı (Vize Gerekli): {len(colors.get('red', '').split(','))} ülke")

    except Exception as e:
        print(f"API Hatası: {e}")

if __name__ == "__main__":
    update_visa_data()
