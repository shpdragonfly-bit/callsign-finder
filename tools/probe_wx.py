#!/usr/bin/env python3
"""NOAA aviationweather.gov API 점검: 응답 형식·CORS 헤더·여러 공항 일괄 조회 한도 (인증키 사용 안 함)"""
import json, os, urllib.request
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe", "wx")
os.makedirs(OUT, exist_ok=True)
ids = "RKSI,KLAX,RJAA,EGLL,RKSS,RKPC,VTBS,KJFK"
many = ",".join(["RKSI","RKSS","RKPC","RKPK","RJAA","RJBB","RJTT","KLAX","KJFK","KSFO","KSEA","KORD","KATL","EGLL","LFPG","EDDF","VTBS","VHHH","RCTP","WSSS","ZSPD","ZBAA","YSSY","OMDB","LTFM","CYVR","PHNL","PGUM","VVNB","RPLL"] * 4)
res = {}
for name, url in [
    ("metar_json", f"https://aviationweather.gov/api/data/metar?ids={ids}&format=json"),
    ("taf_json", f"https://aviationweather.gov/api/data/taf?ids={ids}&format=json"),
    ("metar_raw", f"https://aviationweather.gov/api/data/metar?ids={ids}&format=raw"),
    ("taf_raw", f"https://aviationweather.gov/api/data/taf?ids={ids}&format=raw"),
    ("metar_many", f"https://aviationweather.gov/api/data/metar?ids={many}&format=json"),
]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "callsign-finder/1.0", "Origin": "https://shpdragonfly-bit.github.io"})
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read().decode("utf-8", "replace")
            res[name] = {"status": r.status, "headers": dict(r.headers), "len": len(body)}
        open(os.path.join(OUT, name + ".txt"), "w").write(body[:40000])
    except Exception as e:
        res[name] = {"error": repr(e)[:300]}
json.dump(res, open(os.path.join(OUT, "_summary.json"), "w"), indent=1)
print(json.dumps(res, indent=1)[:3000])
