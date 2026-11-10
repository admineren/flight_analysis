import asyncio
from letsfg.local import search_local

async def run():
    result = await search_local("IST", "BCN", "2027-01-15")
    print(f"LetsFG: {len(result.offers)} sonuç bulundu.")
    if result.offers: print(f"En ucuz: {result.offers[0].price}")

asyncio.run(run())
