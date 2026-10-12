"""인천 버스 API 명세(openapi.json) 받기: 공공데이터포털 검색 → 데이터셋 명세 저장 (키 불필요)."""
import json, os, re, time, urllib.parse, urllib.request
OUT = "probe/bus_ic/spec"; os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (callsign-finder probe)"
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30) as r:
        return r.read().decode("utf-8", "replace")
found = {}
for kw in ["인천광역시_버스도착정보", "인천광역시_버스노선", "인천광역시_정류소", "인천광역시_버스위치정보", "인천광역시 버스"]:
    try:
        html = get("https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=API&currentPage=1&perPage=40&keyword=" + urllib.parse.quote(kw))
        for m in re.finditer(r'/data/(\d{8})/openapi\.do[^>]*>\s*(?:<[^>]+>\s*)*([^<]{3,120})', html):
            if "인천" in m.group(2): found.setdefault(m.group(1), m.group(2).strip())
    except Exception as e:
        found["err_" + kw] = str(e)
    time.sleep(1)
for k in ["15058487", "15056529", "15059206"]: found.setdefault(k, "")
index = {}
for did, title in found.items():
    if not did.isdigit(): continue
    try:
        body = get(f"https://www.data.go.kr/catalog/{did}/openapi.json")
        open(os.path.join(OUT, did + ".json"), "w", encoding="utf-8").write(body[:200000])
        try:
            d = json.loads(body); index[did] = {"title": title or d.get("name", ""), "paths": list((d.get("paths") or {}).keys())[:20], "host": d.get("host", ""), "base": d.get("basePath", ""), "servers": d.get("servers")}
        except Exception: index[did] = {"title": title, "raw": body[:300]}
    except Exception as e:
        index[did] = {"title": title, "err": str(e)}
    time.sleep(1)
json.dump(index, open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(index, ensure_ascii=False)[:4000])
