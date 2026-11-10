import time
from swoop import deals, set_country, TransportConfig

def main():
    print("Swoop API ülke isimleri testi başlıyor...\n")
    set_country("TR")
    
    try:
        # Tek bir çağrı ile 30 deal alıyoruz
        result = deals("IST", transport=TransportConfig(country="TR"))
        
        if not result.deals:
            print("Hiç deal bulunamadı.")
            return

        print(f"Toplam {len(result.deals)} deal alındı.\n")
        
        # Benzersiz ülke isimlerini topla
        unique_countries = set()
        for d in result.deals:
            if d.destination_country:
                unique_countries.add(d.destination_country)
        
        print(f"Bulunan benzersiz ülke sayısı: {len(unique_countries)}\n")
        print("Ülke isimleri (alfabetik):")
        print("-" * 40)
        for country in sorted(unique_countries):
            print(f"  • {country}")
            
        print("\n" + "="*40)
        print("Python sözlük formatı (kopyala-yapıştır için):")
        print("COUNTRY_NAME_TO_ISO = {")
        for country in sorted(unique_countries):
            # Varsayılan olarak boş bir ISO kodu bırakıyoruz, kullanıcı dolduracak
            print(f'    "{country}": "",')
        print("}")

    except Exception as e:
        print(f"HATA: {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
