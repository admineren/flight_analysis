import inspect
from swoop import set_country

print("=" * 60)
print("set_country FONKSİYONU")
print("=" * 60)
print(f"Signature: {inspect.signature(set_country)}")

doc = inspect.getdoc(set_country)
if doc:
    print(f"\nDocstring:\n{doc[:1000]}")

print("\n" + "=" * 60)
print("KAYNAK KODU (ilk 50 satır)")
print("=" * 60)
try:
    source = inspect.getsource(set_country)
    print(source[:2000])
except Exception as e:
    print(f"Kaynak alınamadı: {e}")

# TransportConfig içinde country nasıl kullanılıyor?
print("\n" + "=" * 60)
print("TransportConfig")
print("=" * 60)
from swoop import TransportConfig
print(f"Signature: {inspect.signature(TransportConfig)}")
try:
    tc_doc = inspect.getdoc(TransportConfig)
    if tc_doc:
        print(f"\nDocstring:\n{tc_doc[:500]}")
except:
    pass
