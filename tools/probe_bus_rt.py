"""공항버스 실시간 도착 점검 (서울 6001, 경기 8844): 노선 정류장 목록 + 도착 정보 응답을 probe/bus_rt/ 에 저장. 인증키 값은 저장하지 않음."""
import os, json, urllib.request, urllib.parse

KEY = os.environ.get("DATA_GO_KR_KEY", "")
OUT = "probe/bus_rt"; os.makedirs(OUT, exist_ok=True)
k = urllib.parse.quote(KEY, safe="")


def get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 callsign-finder probe"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        body = ""
        try: body = e.read().decode("utf-8", "replace")[:3000]
        except Exception: pass
        return "ERR %s" % e, body


def save(name, status, body, n=60000):
    open(os.path.join(OUT, name + ".txt"), "w", encoding="utf-8").write(f"{status}\n{body.replace(k, 'KEY')[:n]}")


def js(body):
    try: return json.loads(body)
    except Exception: return None


log = {}
# ---- 서울 6001 ----
SR = "100100412"
st, b = get(f"http://ws.bus.go.kr/api/rest/busRouteInfo/getStaionByRoute?serviceKey={k}&busRouteId={SR}&resultType=json")
items = ((js(b) or {}).get("msgBody") or {}).get("itemList") or []
compact = [[i.get("seq"), i.get("station"), i.get("arsId"), i.get("stationNm"), i.get("direction"), i.get("transYn")] for i in items]
save("seoul_6001_stations", st, json.dumps(compact, ensure_ascii=False, indent=0))
toair = [c for c in compact if "공항" in (c[4] or "") and (c[2] or "").strip()]
log["seoul_stations"] = len(compact); log["seoul_toair"] = len(toair)
if toair:
    c = toair[len(toair) // 3]
    st, b = get(f"http://ws.bus.go.kr/api/rest/arrive/getArrInfoByRoute?serviceKey={k}&stId={c[1]}&busRouteId={SR}&ord={c[0]}&resultType=json")
    save("seoul_6001_arr_one", st, f"# {c}\n" + b)
st, b = get(f"http://ws.bus.go.kr/api/rest/arrive/getArrInfoByRouteAll?serviceKey={k}&busRouteId={SR}&resultType=json")
it = ((js(b) or {}).get("msgBody") or {}).get("itemList") or []
keep = ["staOrd", "stId", "stNm", "arsId", "dir", "arrmsg1", "arrmsg2", "traTime1", "traTime2", "sectOrd1", "sectOrd2", "isLast1", "plainNo1", "vehId1", "nextBus", "term"]
save("seoul_6001_arr_all", st, json.dumps([{x: i.get(x) for x in keep} for i in it], ensure_ascii=False, indent=0))
st, b = get(f"http://ws.bus.go.kr/api/rest/buspos/getBusPosByRtid?serviceKey={k}&busRouteId={SR}&resultType=json")
save("seoul_6001_pos", st, b, 20000)
# 서울 공항버스 노선 목록 (routeType 1 이 공항버스)
st, b = get(f"http://ws.bus.go.kr/api/rest/busRouteInfo/getBusRouteList?serviceKey={k}&strSrch=60&resultType=json")
it = ((js(b) or {}).get("msgBody") or {}).get("itemList") or []
save("seoul_routes_60", st, json.dumps([[i.get("busRouteId"), i.get("busRouteNm"), i.get("routeType"), i.get("stStationNm"), i.get("edStationNm")] for i in it], ensure_ascii=False, indent=0))

# ---- 경기 8844 ----
GR = "241005890"
st, b = get(f"https://apis.data.go.kr/6410000/busrouteservice/v2/getBusRouteStationListv2?serviceKey={k}&routeId={GR}&format=json")
items = (((js(b) or {}).get("response") or {}).get("msgBody") or {}).get("busRouteStationList") or []
save("gbis_8844_stations_raw", st, b, 4000)
compact = [[i.get("stationSeq"), i.get("stationId"), i.get("mobileNo"), i.get("stationName"), i.get("turnYn"), i.get("regionName")] for i in items]
save("gbis_8844_stations", st, json.dumps(compact, ensure_ascii=False, indent=0))
log["gbis_stations"] = len(compact)
if compact:
    c = compact[min(5, len(compact) - 1)]
    st, b = get(f"https://apis.data.go.kr/6410000/busarrivalservice/v2/getBusArrivalItemv2?serviceKey={k}&stationId={c[1]}&routeId={GR}&staOrder={c[0]}&format=json")
    save("gbis_8844_arr_item", st, f"# {c}\n" + b)
    log["gbis_arr_item"] = str(st) + " " + b[:200]
    st, b = get(f"https://apis.data.go.kr/6410000/busarrivalservice/v2/getBusArrivalListv2?serviceKey={k}&stationId={c[1]}&format=json")
    save("gbis_8844_arr_list", st, f"# {c}\n" + b)
st, b = get(f"https://apis.data.go.kr/6410000/buslocationservice/v2/getBusLocationListv2?serviceKey={k}&routeId={GR}&format=json")
save("gbis_8844_location", st, b)
log["gbis_location"] = str(st) + " " + b[:200]
open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8").write(json.dumps(log, ensure_ascii=False, indent=1).replace(k, "KEY"))
print(log)
