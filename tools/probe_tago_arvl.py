"""TAGO 도착정보 응답 형식 확인 (인천 306 노선 중간 정류장). 세션 부족(99)이면 몇 번 다시 시도. 키 저장 안 함."""
import json, os, time, urllib.parse, urllib.request
KEY = os.environ.get("DATA_GO_KR_KEY", ""); k = urllib.parse.quote(KEY, safe="")
OUT = "probe/bus_ic/alt"; T = "https://apis.data.go.kr/1613000"
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 callsign-finder probe"}), timeout=40) as r:
            return str(r.status), r.read().decode("utf-8", "replace")
    except Exception as e:
        return "ERR %s" % e, ""
stops = json.loads(open(os.path.join(OUT, "tago_route_stops.txt"), encoding="utf-8").read().split("\n", 1)[1])["response"]["body"]["items"]["item"]
rid = stops[0]["routeid"]
up = [s for s in stops if str(s.get("updowncd")) == "0"]
pick = up[len(up) // 2] if up else stops[len(stops) // 3]
res = {"route": rid, "stop": pick, "dirs": sorted(set(str(s.get("updowncd")) for s in stops)), "n": len(stops),
       "airport_stops": [[s["nodeord"], s["nodenm"], s.get("updowncd")] for s in stops if "공항" in s["nodenm"]][:10]}
for name, u in [("route_arvl", f"{T}/ArvlInfoInqireService/getSttnAcctoSpcifyRouteBusArvlPrearngeInfoList?serviceKey={k}&_type=json&cityCode=23&nodeId={pick['nodeid']}&routeId={rid}&numOfRows=10&pageNo=1"),
                ("all_arvl", f"{T}/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList?serviceKey={k}&_type=json&cityCode=23&nodeId={pick['nodeid']}&numOfRows=30&pageNo=1")]:
    for t in range(6):
        st, b = get(u); b = b.replace(k, "KEY")
        if '"resultCode":"00"' in b.replace(" ", ""): break
        time.sleep(8)
    res[name] = {"status": st, "tries": t + 1, "body": b[:3000]}
json.dump(res, open(os.path.join(OUT, "tago_arvl.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False)[:3000])
