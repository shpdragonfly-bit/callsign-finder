#!/usr/bin/env python3
"""
공항버스 노선별 '공항 가는 방향' 정류장 목록(정류장 ID 포함) → web/busstops.json   (출퇴근 탭 '출근' 실시간 도착용)

  python3 updater/busstops.py [출력경로] [--force]

- web/bus.json 의 서울·경기·인천 노선을 서울 버스정보(ws.bus.go.kr)·경기 버스정보(GBIS v2)·국토교통부 TAGO(인천)에서 찾아
  노선 ID 와 정류장 ID·순번을 저장합니다. 앱은 이 ID 로 실시간 도착 중계(Apps Script)에 묻습니다.
- 정류장은 거의 바뀌지 않으므로 파일이 7일 이내면 건너뜁니다 (--force 로 강제).
- 인증키: 환경변수 DATA_GO_KR_KEY (또는 config/local.env)
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = args[0] if args else os.path.join(ROOT, "web", "busstops.json")
FORCE = "--force" in sys.argv
AIR = re.compile(r"인천공항|여객터미널|입국장|출국장|공항T[12]|화물청사|국제업무단지")

env = os.path.join(ROOT, "config", "local.env")
if os.path.exists(env):
    for line in open(env, encoding="utf-8-sig"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip()
KEY = urllib.parse.quote(os.environ.get("DATA_GO_KR_KEY", ""), safe="")
CALLS = 0


def get(url):
    global CALLS
    for attempt in range(3):
        try:
            CALLS += 1
            req = urllib.request.Request(url, headers={"User-Agent": "callsign-finder"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 * (attempt + 1))


def split(n):
    m = re.match(r"^([^()]+?)\s*\((.+)\)\s*$", n)
    return (m[1].strip(), m[2].strip()) if m else (n.strip(), "")


def lab_score(label, *names):
    """노선 설명(괄호 안)과 기점·종점 이름이 얼마나 겹치는지"""
    toks = [t for t in re.split(r"[/,·\s()]+", label) if len(t) >= 2 and t != "심야"]
    txt = " ".join(x or "" for x in names)
    return sum(1 for t in toks if t in txt)


def seoul(num, label):
    d = get(f"http://ws.bus.go.kr/api/rest/busRouteInfo/getBusRouteList?serviceKey={KEY}&strSrch={urllib.parse.quote(num)}&resultType=json")
    items = ((d or {}).get("msgBody") or {}).get("itemList") or []
    cands = [i for i in items if (i.get("busRouteNm") or "").strip() == num and str(i.get("routeType")) == "1"]
    if not cands:
        return None
    best = max(cands, key=lambda i: lab_score(label, i.get("stStationNm"), i.get("edStationNm")))
    rid = best["busRouteId"]
    d = get(f"http://ws.bus.go.kr/api/rest/busRouteInfo/getStaionByRoute?serviceKey={KEY}&busRouteId={rid}&resultType=json")
    st = ((d or {}).get("msgBody") or {}).get("itemList") or []
    stops = []
    for s in st:
        name, ars = (s.get("stationNm") or "").strip(), (s.get("arsId") or "").strip()
        if not ars or ars == "0" or "가상" in name or "(경유)" in name or "미정차" in (s.get("stationNo") or ""):
            continue                                   # 가상·미정차 정류장 제외
        if not re.search(r"공항|인천", s.get("direction") or "") or AIR.search(name):
            continue                                   # 공항 가는 방향만, 공항 안 정류장 제외
        stops.append([int(s["seq"]), s["station"], name, ars])
    return {"src": "s", "id": rid, "stops": stops} if stops else None


def gbis(num, label):
    d = get(f"https://apis.data.go.kr/6410000/busrouteservice/v2/getBusRouteListv2?serviceKey={KEY}&keyword={urllib.parse.quote(num)}&format=json")
    items = ((((d or {}).get("response") or {}).get("msgBody") or {}).get("busRouteList")) or []
    if isinstance(items, dict):
        items = [items]
    cands = [i for i in items if str(i.get("routeName")).strip() == num]
    air = [i for i in cands if str(i.get("routeTypeCd")) in ("51", "53")]
    cands = air or cands
    if not cands:
        return None
    best = max(cands, key=lambda i: (lab_score(label, i.get("startStationName"), i.get("endStationName"), i.get("regionName")), str(i.get("routeTypeCd")) == "51"))
    rid = best["routeId"]
    d = get(f"https://apis.data.go.kr/6410000/busrouteservice/v2/getBusRouteStationListv2?serviceKey={KEY}&routeId={rid}&format=json")
    st = ((((d or {}).get("response") or {}).get("msgBody") or {}).get("busRouteStationList")) or []
    if isinstance(st, dict):
        st = [st]
    if not st:
        return None
    turn = next((int(s["stationSeq"]) for s in st if s.get("turnYn") == "Y"), len(st))
    from_air = bool(AIR.search(str(best.get("startStationName") or "")))
    stops = []
    for s in st:
        seq, name = int(s["stationSeq"]), (s.get("stationName") or "").strip()
        if (seq > turn) != from_air or AIR.search(name) or "(경유)" in name or "대기" in name:
            continue                                   # 공항 가는 방향만, 경유·대기 지점 제외
        stops.append([seq, s["stationId"], name, str(s.get("mobileNo") or "").strip()])
    return {"src": "g", "id": rid, "stops": stops} if stops else None


def tago(num, label):
    """인천: 국토교통부 TAGO (인천시 API 는 해외 서버에서 응답하지 않아 TAGO 사용). 정류장 순서대로 첫 인천공항 정류장 앞까지 = 공항 가는 방향"""
    T = "https://apis.data.go.kr/1613000/BusRouteInfoInqireService"
    def items(d):
        it = ((((d or {}).get("response") or {}).get("body") or {}).get("items") or {})
        it = it.get("item", []) if isinstance(it, dict) else []
        return it if isinstance(it, list) else [it]
    cands = [i for i in items(get(f"{T}/getRouteNoList?serviceKey={KEY}&_type=json&cityCode=23&numOfRows=50&pageNo=1&routeNo={urllib.parse.quote(num)}"))
             if str(i.get("routeno")).strip() == num]
    if not cands:
        return None
    best = max(cands, key=lambda i: (bool(AIR.search(str(i.get("endnodenm")) + str(i.get("startnodenm")))), lab_score(label, i.get("startnodenm"), i.get("endnodenm"))))
    rid = best["routeid"]
    st = sorted(items(get(f"{T}/getRouteAcctoThrghSttnList?serviceKey={KEY}&_type=json&cityCode=23&numOfRows=400&pageNo=1&routeId={rid}")),
                key=lambda x: int(x.get("nodeord") or 0))
    if not st:
        return None
    air = [bool(AIR.search(str(x.get("nodenm") or ""))) for x in st]
    # 공항 정류장 묶음: 처음부터 공항이면(공항 출발) 그 묶음은 건너뛰고 다음 공항 묶음 앞까지
    i = 0
    while i < len(st) and air[i]:
        i += 1
    start = i
    while i < len(st) and not air[i]:
        i += 1
    if i >= len(st) or i == start:
        return None                                    # 공항으로 가는 구간 없음
    stops = []
    for x in st[start:i]:
        name = str(x.get("nodenm") or "").strip()
        if "(경유)" in name or "차고지" in name:
            continue
        stops.append([int(x["nodeord"]), x["nodeid"], name, str(x.get("nodeno") or "").strip()])
    return {"src": "t", "id": rid, "stops": stops} if stops else None


def main():
    if not KEY:
        print("DATA_GO_KR_KEY 없음 - 건너뜀"); return
    if not FORCE and os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(old["generated"].replace("Z", "+00:00"))
            if age < dt.timedelta(days=7):
                print(f"busstops.json {age.days}일 전 자료 - 건너뜀"); return
        except Exception:
            pass
    bus = json.load(open(os.path.join(ROOT, "web", "bus.json"), encoding="utf-8"))
    out, miss = {}, []
    for r in bus["routes"]:
        if r.get("a") not in ("서울", "경기", "인천"):
            continue
        num, label = split(r["n"])
        order = (tago,) if r["a"] == "인천" else (seoul, gbis) if r["a"] == "서울" else (gbis, seoul)
        got = None
        for f in order:
            got = f(num, label)
            if got:
                break
        if got:
            out[r["n"]] = got
        else:
            miss.append(r["n"])
    data = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "서울 버스정보(ws.bus.go.kr), 경기 버스정보(GBIS), 국토교통부 TAGO(인천)", "routes": out, "missing": miss}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"노선 {len(out)}개 (못 찾음 {len(miss)}: {', '.join(miss[:20])}) · API 호출 {CALLS}회 → {OUT}")


if __name__ == "__main__":
    main()
