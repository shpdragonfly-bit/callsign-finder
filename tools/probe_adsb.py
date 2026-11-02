"""ADS-B 공개 API: adsb.lol 여러 값 한 번 조회 가능한지 → 표준출력"""
import urllib.request, urllib.error, json, time
H = {"User-Agent": "callsign-finder/1.0 (personal, non-commercial; github.com/shpdragonfly-bit/callsign-finder)"}
def g(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30) as r:
            b = r.read(); j = json.loads(b or b"{}"); a = j.get("ac") or []
            print(u[:110], r.status, len(b), "ac", len(a), [(x.get("r"), x.get("hex"), (x.get("flight") or "").strip()) for x in a[:6]], {k: v for k, v in r.headers.items() if "rate" in k.lower()})
            return a
    except urllib.error.HTTPError as e:
        print(u[:110], "HTTP", e.code, (e.read() or b"")[:100], {k: v for k, v in e.headers.items() if "rate" in k.lower() or k.lower() == "retry-after"})
    except Exception as e:
        print(u[:110], "ERR", type(e).__name__, e)
    return []
a = g("https://api.adsb.lol/v2/type/B77W"); time.sleep(4)
kal = [x for x in a if (x.get("flight") or "").startswith(("KAL", "AAR"))]
hexes = ",".join(x["hex"] for x in kal[:5]) or "71be12,71c225"
regs = ",".join(x.get("r", "") for x in kal[:5]) or "HL8005,HL8226"
for u in ["https://api.adsb.lol/v2/hex/" + hexes, "https://api.adsb.lol/v2/reg/" + regs, "https://api.adsb.lol/v2/registration/" + regs,
          "https://api.adsb.lol/v2/callsign/KAL017", "https://api.adsb.lol/v2/icao/" + hexes]:
    g(u); time.sleep(4)
for t in ["B789", "A359", "B788", "B772"]:
    g("https://api.adsb.lol/v2/type/" + t); time.sleep(4)
