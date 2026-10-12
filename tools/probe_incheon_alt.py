"""인천 버스 실시간 대안 API 점검 (TAGO 등): 어떤 API가 승인됐고 해외(깃허브)에서 응답하는지. 키 값은 저장 안 함."""
import json, os, re, time, urllib.parse, urllib.request
KEY = os.environ.get("DATA_GO_KR_KEY", ""); k = urllib.parse.quote(KEY, safe="")
OUT = "probe/bus_ic/alt"; os.makedirs(OUT, exist_ok=True)
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 callsign-finder probe"}), timeout=40) as r:
            return str(r.status), r.read().decode("utf-8", "replace")
    except Exception as e:
        b = ""
        try: b = e.read().decode("utf-8", "replace")[:2000]
        except Exception: pass
        return "ERR %s" % e, b
T = "https://apis.data.go.kr/1613000"
C = [
 ("tago_route_no", f"{T}/BusRouteInfoInqireService/getRouteNoList?serviceKey={k}&_type=json&cityCode=23&routeNo=306&numOfRows=10&pageNo=1"),
 ("tago_city", f"{T}/BusRouteInfoInqireService/getCtyCodeList?serviceKey={k}&_type=json"),
 ("tago_sttn_nm", f"{T}/BusSttnInfoInqireService/getSttnNoList?serviceKey={k}&_type=json&cityCode=23&nodeNm=%EA%B3%B5%ED%95%AD&numOfRows=10&pageNo=1"),
 ("tago_arvl", f"{T}/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList?serviceKey={k}&_type=json&cityCode=23&nodeId=ICB165000111&numOfRows=20&pageNo=1"),
 ("tago_arvl_city", f"{T}/ArvlInfoInqireService/getCtyCodeList?serviceKey={k}&_type=json"),
 ("tago_loc", f"{T}/BusLcInfoInqireService/getCtyCodeList?serviceKey={k}&_type=json"),
 ("ic_arrival", f"https://apis.data.go.kr/6280000/busArrivalService/getAllRouteBusArrivalList?serviceKey={k}&pageNo=1&numOfRows=5&bstopId=165000111"),
 ("ic_route", f"https://apis.data.go.kr/6280000/busRouteService/getBusRouteSectionList?serviceKey={k}&pageNo=1&numOfRows=5&routeId=169000096"),
]
res = {}
for name, u in C:
    st, b = get(u)
    b = b.replace(k, "KEY").replace(KEY, "KEY")
    msg = re.search(r"<(?:returnAuthMsg|resultMsg)>([^<]*)<", b) or re.search(r'"(?:returnAuthMsg|resultMsg)"\s*:\s*"([^"]*)"', b)
    res[name] = {"status": st, "msg": msg.group(1) if msg else "", "head": re.sub(r"\s+", " ", b)[:700]}
    open(os.path.join(OUT, name + ".txt"), "w", encoding="utf-8").write(st + "\n" + b[:30000])
    time.sleep(0.5)
# TAGO 도착이 되면: 인천 공항버스 노선 하나로 경로·정류장 확인
if "정상" in res["tago_route_no"]["msg"] or '"resultCode":"00"' in res["tago_route_no"]["head"].replace(" ", ""):
    try:
        d = json.loads(open(os.path.join(OUT, "tago_route_no.txt"), encoding="utf-8").read().split("\n", 1)[1])
        it = d["response"]["body"]["items"]["item"]; it = it if isinstance(it, list) else [it]
        rid = it[0]["routeid"]
        st, b = get(f"{T}/BusRouteInfoInqireService/getRouteAcctoThrghSttnList?serviceKey={k}&_type=json&cityCode=23&routeId={rid}&numOfRows=200&pageNo=1")
        open(os.path.join(OUT, "tago_route_stops.txt"), "w", encoding="utf-8").write(st + "\n" + b.replace(k, "KEY")[:60000])
        res["tago_route_stops"] = {"status": st, "routeId": rid, "head": b[:300]}
    except Exception as e:
        res["tago_route_stops"] = {"err": str(e)}
json.dump(res, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({n: [v.get("status"), v.get("msg")] for n, v in res.items()}, ensure_ascii=False))
