"""인천 버스정보 API 점검 (1회성): 승인 여부 · 응답 형식 · 공항버스 인천 노선의 노선 ID · 정류장 순서 · 도착 정보.
결과는 probe/bus_ic/ 에 저장. 인증키 값은 저장하지 않음 (응답 안의 키는 KEY 로 바꿈)."""
import json, os, re, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

KEY = os.environ.get("DATA_GO_KR_KEY", "")
k = urllib.parse.quote(KEY, safe="")
OUT = "probe/bus_ic"; os.makedirs(OUT, exist_ok=True)
B = "https://apis.data.go.kr/6280000"


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


def save(name, status, body, n=40000):
    open(os.path.join(OUT, name + ".txt"), "w", encoding="utf-8").write(f"{status}\n{body.replace(k, 'KEY').replace(KEY, 'KEY')[:n]}")


def items(body):
    """XML 또는 JSON 응답에서 item 목록을 dict 로"""
    body = body.strip()
    if body.startswith("{"):
        try:
            d = json.loads(body)
            it = (((d.get("response") or {}).get("body") or {}).get("items") or {})
            it = it.get("item", it) if isinstance(it, dict) else it
            return it if isinstance(it, list) else [it] if it else []
        except Exception:
            return []
    try:
        root = ET.fromstring(body)
    except Exception:
        return []
    out = []
    for el in root.iter():
        if el.tag in ("itemList", "item"):
            out.append({c.tag: (c.text or "").strip() for c in el})
    return out


def head(body):
    m = re.search(r"<(resultCode|returnReasonCode)>([^<]*)<.*?<(resultMsg|returnAuthMsg)>([^<]*)<", body, re.S)
    return (m.group(2) + " " + m.group(4)) if m else body[:120].replace("\n", " ")


log = {"calls": {}}
nums = []
try:
    bus = json.load(open("web/bus.json", encoding="utf-8"))
    nums = [r.get("n", "").split("(")[0] for r in bus["routes"] if r.get("a") == "인천"]
except Exception as e:
    log["bus_json"] = str(e)
nums = [n for n in nums if n] or ["306", "6777", "111"]
log["routes_in_bus_json"] = nums

# 1) 노선 번호 → 노선 ID (첫 노선은 응답 원문 저장, 형식 비교용으로 _type=json 도)
routes = {}
for i, n in enumerate(nums):
    url = f"{B}/busRouteService/getBusRouteNo?serviceKey={k}&pageNo=1&numOfRows=20&routeNo={urllib.parse.quote(n)}"
    st, b = get(url)
    if i == 0:
        save("route_no_" + n, st, b)
        st2, b2 = get(url + "&_type=json"); save("route_no_" + n + "_json", st2, b2)
        log["calls"]["getBusRouteNo"] = [str(st), head(b)]
    its = items(b)
    routes[n] = [{kk: it.get(kk) for kk in it} for it in its if (it.get("ROUTENO") or it.get("routeno") or "").replace(" ", "") == n.replace(" ", "")] or its[:3]
json.dump(routes, open(os.path.join(OUT, "routes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def rid_of(n):
    for it in routes.get(n) or []:
        for kk in ("ROUTEID", "routeid", "ROUTE_ID"):
            if it.get(kk): return it[kk]
    return ""


# 2) 노선 정류장 순서 (몇 노선만 원문 저장)
sample = [n for n in ("306", "6777", "111", "202", "303") if n in nums and rid_of(n)][:3] or [n for n in nums if rid_of(n)][:3]
stops = {}
for n in [x for x in nums if rid_of(x)]:
    rid = rid_of(n)
    st, b = get(f"{B}/busRouteService/getBusRouteSectionList?serviceKey={k}&pageNo=1&numOfRows=300&routeId={rid}")
    if n in sample: save(f"section_{n}", st, b)
    if sample and n == sample[0]: log["calls"]["getBusRouteSectionList"] = [str(st), head(b)]
    stops[n] = items(b)
json.dump({n: [{kk: s.get(kk) for kk in s} for s in v] for n, v in stops.items()}, open(os.path.join(OUT, "sections.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)

# 3) 도착 정보: 샘플 노선의 앞쪽 1/3 지점 정류장
for n in sample:
    ss = stops.get(n) or []
    if not ss: continue
    s = ss[max(0, len(ss) // 4)]
    bid = s.get("BSTOPID") or s.get("bstopid") or s.get("BSTOP_ID") or ""
    rid = rid_of(n)
    st, b = get(f"{B}/busArrivalService/getBusArrivalList?serviceKey={k}&pageNo=1&numOfRows=10&bstopId={bid}&routeId={rid}")
    save(f"arrival_{n}", st, b); log["calls"].setdefault("getBusArrivalList", [str(st), head(b)])
    st, b = get(f"{B}/busArrivalService/getAllRouteBusArrivalList?serviceKey={k}&pageNo=1&numOfRows=30&bstopId={bid}")
    save(f"arrival_all_{n}", st, b); log["calls"].setdefault("getAllRouteBusArrivalList", [str(st), head(b)])
    st, b = get(f"{B}/busStationService/getBusStationIdList?serviceKey={k}&pageNo=1&numOfRows=5&bstopId={bid}")
    save(f"station_{n}", st, b); log["calls"].setdefault("getBusStationIdList", [str(st), head(b)])
    log.setdefault("samples", []).append({"route": n, "routeId": rid, "stop": s, "stops": len(ss)})
    st, b = get(f"{B}/busLocationService/getBusRouteLocation?serviceKey={k}&pageNo=1&numOfRows=50&routeId={rid}")
    save(f"location_{n}", st, b); log["calls"].setdefault("getBusRouteLocation", [str(st), head(b)])

log["found"] = {n: rid_of(n) for n in nums}
log["stop_counts"] = {n: len(v) for n, v in stops.items()}
json.dump(log, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(log, ensure_ascii=False)[:3000])
