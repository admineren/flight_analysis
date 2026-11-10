import inspect
from enum import Enum
import viajante

def discover_module(module_name, module):
    print("=" * 80)
    print(f"MODÜL: {module_name}")
    print("=" * 80)
    
    if module.__doc__:
        print(f"Açıklama: {module.__doc__.strip()[:300]}\n")
    
    members = inspect.getmembers(module)
    
    functions = []
    classes = []
    enums = []
    
    for name, obj in members:
        if name.startswith("_") or inspect.ismodule(obj):
            continue
        if inspect.isfunction(obj):
            functions.append((name, obj))
        elif inspect.isclass(obj):
            if issubclass(obj, Enum):
                enums.append((name, obj))
            else:
                classes.append((name, obj))

    # 1. FONKSİYONLAR
    if functions:
        print(f"\n--- FONKSİYONLAR ({len(functions)}) ---")
        for name, func in functions:
            try:
                sig = inspect.signature(func)
                print(f"\n✅ {name}{sig}")
            except Exception:
                print(f"\n✅ {name}()")
            
            doc = inspect.getdoc(func)
            if doc:
                print(f"   {doc[:400]}")

    # 2. SINIFLAR
    if classes:
        print(f"\n--- SINIFLAR ({len(classes)}) ---")
        for name, cls in classes:
            print(f"\n✅ {name}")
            try:
                sig = inspect.signature(cls.__init__)
                print(f"   __init__{sig}")
            except Exception:
                pass
            
            doc = inspect.getdoc(cls)
            if doc:
                print(f"   {doc[:200]}")
            
            # Dataclass alanları
            if hasattr(cls, "__dataclass_fields__"):
                print("   Alanlar:")
                for fname, fobj in cls.__dataclass_fields__.items():
                    print(f"     - {fname}: {fobj.type}")

    # 3. ENUM'LAR
    if enums:
        print(f"\n--- ENUM'LAR ({len(enums)}) ---")
        for name, enum_cls in enums:
            print(f"\n✅ {name}:")
            for member in enum_cls:
                print(f"     - {member.name} = '{member.value}'")

print("VIAJANTE PAKETİ KEŞFİ BAŞLIYOR...\n")

# Ana modül
discover_module("viajante", viajante)

# Alt modüller (varsa)
for sub in ["models_flights", "control", "history", "querying", "scrape", "errors"]:
    try:
        mod = __import__(f"viajante.{sub}", fromlist=[sub])
        print("\n\n")
        discover_module(f"viajante.{sub}", mod)
    except ImportError:
        print(f"\n(viajante.{sub} modülü bulunamadı veya import edilemedi)")

print("\n\nKEŞİF TAMAMLANDI.")
