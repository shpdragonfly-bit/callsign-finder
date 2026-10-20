#!/usr/bin/env python3
"""
공항행(출근) 정류장별 시간표 수집 → web/busgo.json

  python3 updater/busgo.py [출력경로] [--force]

공공데이터에는 공항버스의 '공항행 정류장별 시각'이 없어서(첫차·막차만), 공개된 곳에서 출처별로 받음.
출처마다 따로 갱신하고, 한 출처가 실패하면 그 출처의 기존 자료를 그대로 둠.

  출처            노선                                         방식 / 주기
  seoulairbus     서울공항리무진 6006·6009·6020·6200·6300·6500·6600   홈페이지 정류장별 표 (robots 전체 허용) / 7일
  klimousine      한국공항리무진 6701·6702·6703·6705A·N6701·N6703    홈페이지 정류장별 표 (robots: /member·/adm 만 제한) / 7일
  tago_exp        지방 고속버스 (금호고속 등)                       국토교통부 TAGO 고속버스정보 API / 매일 (당일 배차만 제공)
  tago_sub        지방 시외버스                                     국토교통부 TAGO 시외버스정보 API / 매일 (활용신청 필요)

TAGO 는 '오늘' 배차만 주므로, 오늘이 평일이면 평일(wd)·휴일이면 휴일(we) 칸만 새로 쓰고 나머지 칸은 지난 자료를 둠.

출력: {"generated", "src": {출처: 받은 시각}, "routes": {노선키: {"src", "stops": [정류장...],
        "wd": [[각 정류장 'HHMM' 또는 "", ..., T1 도착, T2 도착], ...], "we": [...], "arr": ["T1", "T2"]}}}
  · 노선키: 수도권 = 노선 번호(6300), 지방 = bus.json 의 노선 이름 그대로(광주(유·스퀘어))
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else os.path.join(ROOT, "web", "busgo.json")
BUS = os.path.join(ROOT, "web", "bus.json")
UA = "callsign-finder/1.0 (offline flight assist; timetable check)"
FORCE = "--force" in sys.argv
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(dt.timezone.utc)

_env = os.path.join(ROOT, "config", "local.env")             # 이 PC 전용 키 (GitHub 미포함)
if os.path.exists(_env):
    for line in open(_env, encoding="utf-8-sig"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip()
KEY = urllib.parse.unquote(os.environ.get("DATA_GO_KR_KEY", "").strip())


def get(url, data=None, tries=3, hdr=None):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None,
                                         headers=dict({"User-Agent": UA}, **(hdr or {})))
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if getattr(e, "code", 0) in (401, 403, 404):
                break
            time.sleep(2 * (i + 1))
    raise last


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<br\s*/?>", " ", re.sub(r"<(?!br)[^>]+>", "", s, flags=re.I), flags=re.I))).strip()


def hhmm(v):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v.strip())
    return "%02d%s" % (int(m.group(1)), m.group(2)) if m else ""


def tstamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(s):
    try:
        return (NOW - dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).total_seconds() / 86400
    except Exception:
        return 1e9


# ---------------------------------------------------------------- 서울공항리무진
SAB = "https://www.seoulairbus.com"


def sab_table(page):
    """정류장별 표 → (정류장 이름 목록, 행 목록). 공항 출발 열(시내행)은 버림."""
    m = re.search(r"<table[^>]*>(.*?)</table>", page, re.S)
    if not m:
        return None, None
    t = m.group(1)
    head = re.search(r"<thead>(.*?)</thead>", t, re.S)
    cols = [(a, text(b)) for a, b in re.findall(r"<th([^>]*)>(.*?)</th>", head.group(1) if head else "", re.S)]
    if not cols or cols[0][1] != "순번":
        return None, None
    names = [n for a, n in cols[1:]]
    n_stop = sum(1 for a, n in cols[1:] if "arrived" not in a and "departure" not in a)
    arr_idx = [i for i, (a, n) in enumerate(cols[1:]) if "arrived" in a]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", re.search(r"<tbody>(.*?)</tbody>", t, re.S).group(1), re.S):
        tds = [text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)][1:]
        if len(tds) < len(names):
            continue
        st = [hhmm(v) for v in tds[:n_stop]]
        if not any(st):
            continue
        rows.append(st + [hhmm(tds[i]) for i in arr_idx])
    return names[:n_stop], rows


def seoulairbus():
    top = get(SAB + "/bus")
    nums = sorted(set(re.findall(r'/bus/([0-9A-Za-z\-]+)', top)))
    out = {}
    for num in nums:
        try:
            m = re.search(r"/timetableAll/(\d+)/0", get("%s/bus/%s" % (SAB, num)))
            if not m:
                continue
            rid = m.group(1)
            stops, wd = sab_table(get("%s/timetableAll/%s/0" % (SAB, rid)))
            _, we = sab_table(get("%s/timetableAll/%s/1" % (SAB, rid)))
            if stops and wd:
                out[num] = {"stops": stops, "wd": wd, "we": we or wd}
                print("  %s: 정류장 %d · 평일 %d편 · 휴일 %d편" % (num, len(stops), len(wd), len(we or [])))
            time.sleep(1)
        except Exception as e:
            print("  %s: 실패 %s" % (num, e))
    return out


# ---------------------------------------------------------------- 한국공항리무진
KLM = "https://www.klimousine.com"


def klimousine():
    top = get(KLM + "/bus/limousine.php")
    nums = []
    for n in re.findall(r"limousine\.php\?bus_no=([0-9A-Za-z]+)", top):
        if n not in nums:
            nums.append(n)
    try:                                                       # 첫 화면에 안 보이는 심야 노선 등: bus.json 의 같은 운영사 노선도
        for r in json.load(open(BUS, encoding="utf-8"))["routes"]:
            n = re.split(r"[(\s]", r["n"])[0]
            if "한국공항리무진" in r.get("cp", "") and n not in nums:
                nums.append(n)
    except Exception:
        pass
    out = {}
    for num in nums:
        try:
            pg = get(KLM + "/inc/ajax.php", {"mode": "limousine_Time", "bus_num": num, "LANG": "KOR"},
                     hdr={"X-Requested-With": "XMLHttpRequest", "Referer": KLM + "/bus/limousine.php?bus_no=" + num,
                          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
            m = re.search(r"<h3>\s*공항행\s*</h3>\s*<table[^>]*>(.*?)</table>", pg, re.S)
            if not m:
                print("  %s: 공항행 표 없음 %r" % (num, re.sub(r"\s+", " ", pg)[:300]))
                continue
            t = m.group(1)
            head = [text(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", re.search(r"<thead>(.*?)</thead>", t, re.S).group(1), re.S)][1:]
            arr = {i: ("T1" if "T1" in h else "T2") for i, h in enumerate(head) if "인천공항" in h or "도착" in h}
            stop_i = [i for i in range(len(head)) if i not in arr]
            rows = []
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", re.search(r"<tbody>(.*?)</tbody>", t, re.S).group(1), re.S):
                tds = [hhmm(text(x)) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                tds += [""] * (len(head) - len(tds))           # 도착 칸이 비어 아예 없는 행 (심야)
                if not any(tds[i] for i in stop_i):
                    continue
                a = {v: tds[i] for i, v in arr.items()}
                rows.append([tds[i] for i in stop_i] + [a.get("T1", ""), a.get("T2", "")])
            if rows:
                out[num] = {"stops": [head[i] for i in stop_i], "wd": rows, "we": rows}
                print("  %s: 정류장 %d · %d편" % (num, len(stop_i), len(rows)))
            time.sleep(1)
        except Exception as e:
            print("  %s: 실패 %s" % (num, e))
    return out


# ---------------------------------------------------------------- TAGO 고속·시외버스 (지방 노선)
TAGO = "https://apis.data.go.kr/1613000/"
SVC = {"tago_exp": ("ExpBusInfo", "GetExpBusTrminlList", "GetStrtpntAlocFndExpbusInfo"),
       "tago_sub": ("SuburbsBusInfo", "GetSuberbsBusTrminlList", "GetStrtpntAlocFndSuberbsBusInfo")}
nrm = lambda s: re.sub(r"[\s.,·()\-]", "", str(s or ""))


def tago_call(svc, op, params):
    p = dict(params, serviceKey=KEY, _type="json")
    body = get(TAGO + svc + "/" + op + "?" + urllib.parse.urlencode(p), tries=2)
    j = json.loads(body)
    if "response" not in j:
        raise RuntimeError(json.dumps(j, ensure_ascii=False)[:200])
    it = j["response"].get("body", {}).get("items") or {}
    it = it.get("item", []) if isinstance(it, dict) else []
    return it if isinstance(it, list) else [it]


def tago(name):
    svc, op_term, op_sched = SVC[name]
    terms = tago_call(svc, op_term, {"numOfRows": "3000", "pageNo": "1"})
    by = {}
    for t in terms:
        by.setdefault(nrm(t.get("terminalNm")), []).append(t["terminalId"])
    air = {"T1": by.get(nrm("인천공항T1"), []) + by.get(nrm("인천공항1터미널"), []),
           "T2": by.get(nrm("인천공항T2"), []) + by.get(nrm("인천공항2터미널"), [])}
    if not air["T1"] and not air["T2"]:
        raise RuntimeError("인천공항 터미널 ID 없음")
    today = dt.datetime.now(KST).strftime("%Y%m%d")
    routes = json.load(open(BUS, encoding="utf-8"))["routes"]
    cache, out = {}, {}
    for r in routes:
        if r.get("a") in ("서울", "경기", "인천"):
            continue
        stops = [s for s in r.get("s", []) if "공항" not in s and by.get(nrm(s))]
        if not stops:
            continue
        rows = []
        for i, s in enumerate(stops):
            got = {}
            for term in ("T1", "T2"):
                for dep in by[nrm(s)][:2]:
                    for arr in air[term][:1]:
                        k = (dep, arr)
                        if k not in cache:
                            try:
                                cache[k] = tago_call(svc, op_sched, {"depTerminalId": dep, "arrTerminalId": arr,
                                                                     "depPlandTime": today, "numOfRows": "300"})
                            except Exception as e:
                                print("  %s→%s 실패 %s" % (s, term, str(e)[:80]))
                                cache[k] = []
                            time.sleep(0.2)
                        for x in cache[k]:
                            d, a = str(x.get("depPlandTime", ""))[-4:], str(x.get("arrPlandTime", ""))[-4:]
                            if len(d) == 4:
                                got.setdefault(d, {})[term] = a
            for d in sorted(got):
                row = [""] * len(stops) + [got[d].get("T1", ""), got[d].get("T2", "")]
                row[i] = d
                rows.append(row)
        if rows:
            rows.sort(key=lambda x: next(v for v in x if v))
            out[r["n"]] = {"stops": stops, "rows": rows}
            print("  %s: 정류장 %d · %d편" % (r["n"], len(stops), len(rows)))
    return out


# ---------------------------------------------------------------- 경기공항리무진 (고정 자료)
# 홈페이지가 자동 접속 차단 화면을 띄우므로 자동으로 받지 않음. 브라우저로 직접 확인한 값을
# data/busgo_ggairport.json 에 두고(받은 날짜 포함) 그대로 씀. 시간표가 바뀌면 그 파일만 고치면 됨.
GGA = os.path.join(ROOT, "data", "busgo_ggairport.json")


def ggairport():
    j = json.load(open(GGA, encoding="utf-8"))
    out = {}
    for s in j["stops"]:
        times = sorted({hhmm(t) for t in s["t"] if hhmm(t)})
        for b in s["bus"]:
            key = re.sub(r"^A", "", b)
            e = out.setdefault(key, {"stops": [], "rows": [], "mix": {}})
            e["stops"].append(s["stop"])
            if len(s["bus"]) > 1:
                e["mix"][s["stop"]] = " · ".join(re.sub(r"^A", "", x) for x in s["bus"])
            night = [t for t in times if t < "0400"]          # 심야(N) 번호와 섞인 정류장: 새벽 4시 전은 심야 버스로 봄
            if any(x.startswith("N") for x in s["bus"]):
                e["rows"].append(night if key.startswith("N") else [t for t in times if t >= "0400"])
            else:
                e["rows"].append(times)
    res = {}
    for key, e in out.items():
        n = len(e["stops"])
        rows = []
        for i, times in enumerate(e["rows"]):
            for t in times:
                r = [""] * (n + 2)
                r[i] = t
                rows.append(r)
        rows.sort(key=lambda x: next(v for v in x if v))
        res[key] = {"stops": e["stops"], "wd": rows, "we": rows, "mix": e["mix"]}
    return res, j.get("fetched", "")


# ---------------------------------------------------------------- 모으기
def main():
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = {}
    routes = dict(old.get("routes", {}))
    src = dict(old.get("src", {}))
    for k, v in routes.items():                                # 예전 형식(출처 기록 없음) 호환
        src.setdefault(v.get("src", ""), old.get("generated", ""))
    changed = False
    kst_today = dt.datetime.now(KST)
    holiday = kst_today.weekday() >= 5                         # 공휴일은 bus.json 기준과 같이 주말만 구분

    for name, fn, every in (("seoulairbus", seoulairbus, 7), ("klimousine", klimousine, 7)):
        if not FORCE and age_days(src.get(name, "")) < every:
            print("%s: %.1f일 전 자료 유지" % (name, age_days(src.get(name, ""))))
            continue
        print("%s 시간표 받는 중" % name)
        try:
            got = fn()
        except Exception as e:
            print("%s: 실패 %s → 기존 자료 유지" % (name, e))
            continue
        if not got:
            print("%s: 받은 노선 없음 → 기존 자료 유지" % name)
            continue
        routes = {k: v for k, v in routes.items() if v.get("src") != name}
        for k, v in got.items():
            routes[k] = dict(v, src=name, arr=["T1", "T2"])
        src[name] = tstamp(NOW)
        changed = True

    try:                                                       # 경기공항리무진 고정 자료 (매번 반영, 가벼움)
        got, fetched = ggairport()
        routes = {k: v for k, v in routes.items() if v.get("src") != "ggairport"}
        for k, v in got.items():
            routes[k] = dict(v, src="ggairport", arr=["T1", "T2"])
        stamp = fetched + "T00:00:00Z" if fetched else ""
        if src.get("ggairport") != stamp:
            changed = True
        src["ggairport"] = stamp
        print("ggairport: 노선 %d개 (%s 확인 자료)" % (len(got), fetched))
    except Exception as e:
        print("ggairport: 실패 %s" % e)

    for name in ("tago_exp", "tago_sub"):
        if not KEY:
            print("%s: 인증키 없음 → 건너뜀" % name)
            continue
        last = src.get(name, "")
        try:
            same_day = dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).astimezone(KST).date() == kst_today.date()
        except Exception:
            same_day = False
        if same_day and not FORCE:
            print("%s: 오늘 자료 있음" % name)
            continue
        print("%s 오늘 배차 받는 중" % name)
        try:
            got = tago(name)
        except Exception as e:
            print("%s: 실패 %s → 기존 자료 유지" % (name, str(e)[:160]))
            continue
        if not got:
            print("%s: 받은 노선 없음" % name)
            src[name] = tstamp(NOW)
            continue
        slot = "we" if holiday else "wd"
        for k, v in got.items():
            prev = routes.get(k) if (routes.get(k) or {}).get("src") == name else None
            ent = {"src": name, "stops": v["stops"], "arr": ["T1", "T2"],
                   "wd": (prev or {}).get("wd") or v["rows"], "we": (prev or {}).get("we") or v["rows"]}
            if prev and prev.get("stops") != v["stops"]:
                ent["wd"] = ent["we"] = v["rows"]
            ent[slot] = v["rows"]
            routes[k] = ent
        src[name] = tstamp(NOW)
        changed = True

    if not changed and os.path.exists(OUT):
        return 0
    if not routes:
        print("공항행 시간표: 자료 없음")
        return 1
    out = {"generated": tstamp(NOW), "src": src, "routes": routes}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("공항행 시간표: 노선 %d개, %d bytes → %s" % (len(routes), os.path.getsize(OUT), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
