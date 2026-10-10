#!/usr/bin/env python3
"""
인천공항 공항버스 시간표 수집 → web/bus.json   (출퇴근 탭 '퇴근 T1·T2'용)

  python3 updater/bus.py [출력경로]

- 인천국제공항공사_공항버스 정보 조회 서비스 (B551177/BusInformation/getBusInfo), 갱신 주기 60분
- 노선별 T1·T2 출발 시간표(평일·주말), 승차 위치, 요금, 운수사, 정류장 순서
- 같은 노선이 '6707A (T1)', '6707A (T2)' 처럼 터미널별로 따로 오면 하나로 합침
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
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "web", "bus.json")
URL = "https://apis.data.go.kr/B551177/BusInformation/getBusInfo?serviceKey={key}&type=json&numOfRows=500&pageNo={page}"
AREA = {"1": "서울", "2": "경기", "3": "인천", "4": "강원", "5": "충청", "6": "경상", "7": "전라"}

env = os.path.join(ROOT, "config", "local.env")
if os.path.exists(env):
    for line in open(env, encoding="utf-8-sig"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip()


def fetch(key):
    items, page = [], 1
    while True:
        url = URL.format(key=urllib.parse.quote(key, safe=""), page=page)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "callsign-finder"}), timeout=60) as r:
                    d = json.loads(r.read().decode("utf-8"))
                break
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
        body = d["response"]["body"]
        got = body.get("items") or []
        if isinstance(got, dict):
            got = got.get("item") or []
        items += got if isinstance(got, list) else [got]
        if len(items) >= int(body.get("totalCount") or 0) or not got:
            return items
        page += 1


def times(s):
    out = []
    for t in re.split(r"[,\s]+", s or ""):
        if re.fullmatch(r"\d{4}", t) and int(t[:2]) < 30 and int(t[2:]) < 60:
            out.append(t)
    return sorted(set(out))


def main():
    key = urllib.parse.unquote(os.environ.get("DATA_GO_KR_KEY", "").strip())
    if not key:
        print("DATA_GO_KR_KEY 없음 → 공항버스 시간표 생략")
        return 0
    raw = fetch(key)
    routes = {}
    for x in raw:
        name = re.sub(r"\s*\((T1|T2)\)\s*$", "", (x.get("busnumber") or "").strip())
        if not name:
            continue
        r = routes.setdefault(name, {"n": name, "a": AREA.get(str(x.get("area")), ""), "c": x.get("busclass") or "",
                                     "f": x.get("adultfare") or "", "cp": x.get("cpname") or "", "s": []})
        stops = [s.strip() for s in (x.get("routeinfo") or "").split(",") if s.strip()]
        if len(stops) > len(r["s"]):
            r["s"] = stops
        for t in ("t1", "t2"):
            wd, we = times(x.get(t + "wdayt")), times(x.get(t + "wt"))
            if wd or we:
                r[t] = {"wd": wd, "we": we or wd, "lo": (x.get(t + "ridelo") or "").strip(),
                        "first": x.get(t + "endfirst") or "", "last": x.get(t + "endlast") or ""}
        if x.get("toawfirst"):
            r["toaw"] = [x.get("toawfirst") or "", x.get("toawlast") or ""]
    out = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "인천국제공항공사 공항버스 정보 (공공데이터포털)",
           "routes": sorted(routes.values(), key=lambda r: (r["a"], r["n"]))}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("공항버스: 원본 %d건 → 노선 %d개, T1 %d · T2 %d, %d bytes" % (
        len(raw), len(routes), sum(1 for r in routes.values() if "t1" in r), sum(1 for r in routes.values() if "t2" in r), os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
