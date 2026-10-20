#!/usr/bin/env python3
"""
공항행(출근) 정류장별 시간표 수집 → web/busgo.json

  python3 updater/busgo.py [출력경로]

- 공공데이터에는 공항버스의 '공항행 정류장별 시각'이 없어서(첫차·막차만), 운영사 홈페이지의 공개 시간표를 받음
- 1차: 서울공항리무진 (www.seoulairbus.com, robots.txt 전체 허용) — 6006·6009·6020·6200·6300·6500·6600
  · 노선 목록(/bus) → 노선별 페이지(/bus/번호)에서 내부 번호 → 평일(/timetableAll/N/0)·휴일(/timetableAll/N/1) 표
- 7일마다 새로 받음 (시간표는 자주 바뀌지 않음). 실패하면 기존 파일을 그대로 둠
- 출력: {"generated", "source", "routes": {"6300": {"src": "seoulairbus", "stops": [정류장...],
         "wd": [[각 정류장 'HHMM' 또는 ""], ...], "we": [...], "arr": ["T1 도착", "T2 도착"]}}}
  · 행마다 정류장 열 + 마지막 2칸은 T1·T2 도착 예정 시각
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else os.path.join(ROOT, "web", "busgo.json")
BASE = "https://www.seoulairbus.com"
UA = "callsign-finder/1.0 (offline flight assist; weekly timetable check)"
REFRESH_DAYS = 7


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def parse_table(page):
    """정류장별 표 → (정류장 이름 목록, 행 목록). 공항 출발 열(시내행)은 버림."""
    m = re.search(r"<table[^>]*>(.*?)</table>", page, re.S)
    if not m:
        return None, None
    t = m.group(1)
    head = re.search(r"<thead>(.*?)</thead>", t, re.S)
    ths = re.findall(r"<th([^>]*)>(.*?)</th>", head.group(1) if head else "", re.S)
    cols = [(a, text(b)) for a, b in ths]
    if not cols or cols[0][1] != "순번":
        return None, None
    names = [n for a, n in cols[1:]]
    # 정류장 열 = 'arrived'/'departure' 클래스가 아닌 열, 그다음 T1 도착 · T2 도착
    n_stop = sum(1 for a, n in cols[1:] if "arrived" not in a and "departure" not in a)
    arr_idx = [i for i, (a, n) in enumerate(cols[1:]) if "arrived" in a]
    stops = names[:n_stop]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", re.search(r"<tbody>(.*?)</tbody>", t, re.S).group(1), re.S):
        tds = [text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)][1:]   # 순번 제외
        if len(tds) < len(names):
            continue
        fix = lambda v: v.replace(":", "") if re.fullmatch(r"\d{1,2}:\d{2}", v) else ""
        st = [fix(v).zfill(4) if fix(v) else "" for v in tds[:n_stop]]
        if not any(st):                                    # 공항 출발만 있는 행 (시내행) → 제외
            continue
        arr = [fix(tds[i]).zfill(4) if fix(tds[i]) else "" for i in arr_idx]
        rows.append(st + arr)
    return stops, rows


def age_days(path):
    try:
        g = json.load(open(path, encoding="utf-8"))["generated"]
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(g, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).days
    except Exception:
        return 1e9


def main():
    if "--force" not in sys.argv and age_days(OUT) < REFRESH_DAYS:
        print("공항행 시간표: %d일 전 자료 유지" % age_days(OUT))
        return 0
    try:
        top = get(BASE + "/bus")
    except Exception as e:
        print("공항행 시간표: 노선 목록 실패 %s" % e)
        return 1
    nums = sorted(set(re.findall(r'href="/bus/([0-9A-Za-z\-]+)"', top)) | set(re.findall(r'/bus/([0-9A-Za-z\-]+)', top)))
    routes = {}
    for num in nums:
        try:
            pg = get("%s/bus/%s" % (BASE, num))
            m = re.search(r"/timetableAll/(\d+)/0", pg)
            if not m:
                print("  %s: 시간표 번호 없음" % num)
                continue
            rid = m.group(1)
            stops, wd = parse_table(get("%s/timetableAll/%s/0" % (BASE, rid)))
            _, we = parse_table(get("%s/timetableAll/%s/1" % (BASE, rid)))
            if not stops or not wd:
                print("  %s: 표 읽기 실패" % num)
                continue
            routes[num] = {"src": "seoulairbus", "id": int(rid), "stops": stops, "wd": wd, "we": we or wd, "arr": ["T1", "T2"]}
            print("  %s: 정류장 %d · 평일 %d편 · 휴일 %d편" % (num, len(stops), len(wd), len(we or [])))
            time.sleep(1)
        except Exception as e:
            print("  %s: 실패 %s" % (num, e))
    if not routes:
        print("공항행 시간표: 받은 노선 없음 → 기존 파일 유지")
        return 1
    out = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "서울공항리무진 홈페이지 정류장별 시간표 (www.seoulairbus.com)", "routes": routes}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("공항행 시간표: 노선 %d개, %d bytes → %s" % (len(routes), os.path.getsize(OUT), os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
