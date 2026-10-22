#!/usr/bin/env python3
"""
인천 도착편의 출발지 예정 출발시각 (AeroDataBox) → web/dep.json

  python3 updater/adb.py            받기 (3일마다, 키 있을 때만)  → data/adb_icn.json (저장소에 넣지 않음, Actions 캐시)
  python3 updater/adb.py --export   web/data.json 의 인천 도착편에 맞춰 web/dep.json 만들기 (배포용, 저장소에 넣지 않음)
  python3 updater/adb.py --force    주기와 상관없이 받기

- 공공데이터(인천공항)에는 도착편의 '인천 도착 시각'만 있어서, 출발지 현지 출발 예정시각(STD)은 AeroDataBox 에서 받음
  · FIDS(공항 도착 목록, by time range) + withLeg=true → 편마다 departure.scheduledTime(출발 공항 현지·UTC)
- 키: 환경변수 ADB_KEY (GitHub Secret). 없으면 아무것도 안 함. ADB_HOST 기본 aerodatabox.p.rapidapi.com
- 무료(Basic) 요금제: 월 400 units(초과 시 차단), FIDS 1회 = 2 units
  · 예정 출발시각: 6.5일마다 앞으로 7일치(12시간 창 14번 = 28 units), 월 4~5번 = 약 120~140 units
  · 실제 이륙·착륙(runwayTime): 6시간마다 '6시간 전~6시간 뒤' 도착+출발편 1번(direction=Both, 2 units — 2026-10-22 시험으로 확인), 월 약 248 units
    → 지난 1주 운항 기록(이륙·착륙·게이트 출발/도착·비행시간)도 여기서 쌓임 (보관 7일과 같은 기간)
  · 합계 약 370~390 units. 응답의 남은 units 가 40 아래면 실제 이륙시각 받기는 쉼
- 이용 조건
  · 출처 표시 필수 → 앱 화면에 'AeroDataBox' 표시
  · 보관 7일 → 받은 지 7일 지난 기록은 지우고, 저장소(공개 기록)에는 커밋하지 않음 (Actions 캐시 · 배포 파일만)
- 같은 편 · 같은 출발지 · 같은 요일 · 같은 인천 도착 시각일 때만 그 요일 기록의 출발~도착 간격을 다른 날짜에 씀
  (정기편도 요일마다 출발시각이 다를 수 있어서). 표시는 'd'
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
RAW = os.path.join(ROOT, "data", "adb_icn.json")
OUT = os.path.join(ROOT, "web", "dep.json")
DATA = os.path.join(ROOT, "web", "data.json")
LIVE = "https://shpdragonfly-bit.github.io/callsign-finder/dep.json"
KST = dt.timezone(dt.timedelta(hours=9))
EVERY_H = 156           # 예정 출발시각 7일치: 6.5일마다 (보관 7일 안에 새로 받음) → 월 4~5번 × 28 units
NEAR_H = 5.5            # 실제 이륙시각: 6시간마다 앞으로 12시간 도착편 1번 → 하루 4번 × 2 units
UNITS_FLOOR = 40        # 남은 units 가 이보다 적으면 실제 이륙시각 받기는 쉼 (예정 출발시각 몫을 남김)
DAYS = 7                # 앞으로 7일치 (요일별 출발시각이 모두 들어오게)
KEEP_H = 7 * 24 - 2     # 이용 조건: 보관 7일

_env = os.path.join(ROOT, "config", "local.env")
if os.path.exists(_env):
    for line in open(_env, encoding="utf-8-sig"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip()
KEY = os.environ.get("ADB_KEY", "").strip()
HOST = (os.environ.get("ADB_HOST") or "aerodatabox.p.rapidapi.com").strip()
NOW = dt.datetime.now(dt.timezone.utc)
LIMIT = {}
STAMP = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def load():
    try:
        return json.load(open(RAW, encoding="utf-8"))
    except Exception:
        return {"checked": "", "f": {}}


def purge(db):
    """받은 지 7일 지난 기록 삭제 (이용 조건)"""
    for t in ("f", "d"):
        m = db.setdefault(t, {})
        for fn in list(m):
            m[fn] = {k: v for k, v in m[fn].items() if len(v) > 3 and ts(v[3]) and (NOW - ts(v[3])).total_seconds() < KEEP_H * 3600}
            if not m[fn]:
                del m[fn]


def tm(s):
    """'2026-10-21 22:40-07:00' / '2026-10-22 05:40Z' → (UTC 'YYYYMMDDHHMM', 시차 분)"""
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::\d\d)?(Z|[+-]\d\d:?\d\d)?", s or "")
    if not m:
        return None, None
    t = dt.datetime(*map(int, m.groups()[:5]))
    z = m.group(6) or "Z"
    off = 0 if z == "Z" else (1 if z[0] == "+" else -1) * (int(z[1:3]) * 60 + int(z[-2:]))
    return (t - dt.timedelta(minutes=off)).strftime("%Y%m%d%H%M"), off


def call(frm, to, direction="Arrival"):
    url = "https://%s/flights/airports/iata/ICN/%s/%s?%s" % (HOST, frm, to, urllib.parse.urlencode({
        "withLeg": "true", "direction": direction, "withCancelled": "true", "withCodeshared": "false",
        "withCargo": "true", "withPrivate": "false", "withLocation": "false"}))
    h = {"Accept": "application/json", "User-Agent": "callsign-finder/1.0", "X-RapidAPI-Key": KEY, "X-RapidAPI-Host": HOST}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        rl = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}   # 남은 사용량 (비밀값 아님)
        if rl:
            LIMIT.update(rl)
        return json.loads(r.read().decode("utf-8") or "{}")


def units_left():
    for k, v in LIMIT.items():
        if "units" in k and "remaining" in k:
            try:
                return int(v)
            except ValueError:
                pass
    return None


def keep(old, i, new):
    return new or (old[i] if len(old) > i else "")


def take(db, res):
    """응답 → db. 도착편 db['f'][편][인천도착예정UTC], 출발편 db['d'][편][인천출발예정UTC]"""
    got = 0
    for x in res.get("arrivals") or []:
        fn = re.sub(r"\s+", "", x.get("number") or "").upper()
        dep, arr = x.get("departure") or {}, x.get("arrival") or {}
        st = dep.get("scheduledTime") or {}
        std, _ = tm(st.get("utc") or "")
        _, off = tm(st.get("local") or "")
        sta, _ = tm((arr.get("scheduledTime") or {}).get("utc") or "")
        if not (fn and std and sta):
            continue
        u = lambda o, k: tm((o.get(k) or {}).get("utc") or "")[0] or ""
        old = db["f"].get(fn, {}).get(sta) or []
        # [출발예정, 출발지시차, 출발지, 받은때, 실제이륙, 변경·실제출발(게이트), 인천착륙, 인천도착(게이트), 도착함]
        db["f"].setdefault(fn, {})[sta] = [std, off or 0, ((dep.get("airport") or {}).get("iata") or "").upper(), STAMP,
                                           keep(old, 4, u(dep, "runwayTime")), keep(old, 5, u(dep, "revisedTime")),
                                           keep(old, 6, u(arr, "runwayTime")), keep(old, 7, u(arr, "revisedTime") if x.get("status") == "Arrived" else ""),
                                           1 if x.get("status") == "Arrived" else (old[8] if len(old) > 8 else 0)]
        got += 1
    for x in res.get("departures") or []:
        fn = re.sub(r"\s+", "", x.get("number") or "").upper()
        dep, arr = x.get("departure") or {}, x.get("arrival") or {}
        std, _ = tm((dep.get("scheduledTime") or {}).get("utc") or "")
        at = arr.get("scheduledTime") or {}
        sta, _ = tm(at.get("utc") or "")
        _, aoff = tm(at.get("local") or "")
        if not (fn and std):
            continue
        u = lambda o, k: tm((o.get(k) or {}).get("utc") or "")[0] or ""
        old = db.setdefault("d", {}).get(fn, {}).get(std) or []
        dn = x.get("status") in ("Departed", "EnRoute", "Approaching", "Arrived", "Diverted")
        # [목적지, 도착예정, 목적지시차, 받은때, 인천이륙, 인천출발(게이트), 목적지착륙, 목적지도착(게이트)]
        db["d"].setdefault(fn, {})[std] = [((arr.get("airport") or {}).get("iata") or "").upper(), sta or "", aoff or 0, STAMP,
                                           keep(old, 4, u(dep, "runwayTime")), keep(old, 5, u(dep, "revisedTime") if dn else ""),
                                           keep(old, 6, u(arr, "runwayTime")), keep(old, 7, u(arr, "revisedTime") if x.get("status") == "Arrived" else "")]
        got += 1
    return got


def fetch(db, days=DAYS, sample=None, back=0, direction="Arrival"):
    now = dt.datetime.now(KST).replace(second=0, microsecond=0) - dt.timedelta(hours=back)
    got = calls = 0
    for k in range(max(1, days * 2)):                           # 12시간 창 (API 한 번에 최대 12시간)
        a = now + dt.timedelta(hours=12 * k)
        b = a + dt.timedelta(hours=12, minutes=-1)
        try:
            res = call(a.strftime("%Y-%m-%dT%H:%M"), b.strftime("%Y-%m-%dT%H:%M"), direction)
            calls += 1
        except Exception as e:
            print("AeroDataBox 실패: %s" % (getattr(e, "code", "") or type(e).__name__))   # 키가 로그에 남지 않게 주소는 출력하지 않음
            if getattr(e, "code", 0) in (401, 403, 429):
                break
            continue
        got += take(db, res)
        time.sleep(1)
    print("AeroDataBox(%s): 호출 %d회(약 %d units), %d편" % (direction, calls, calls * 2, got))
    if LIMIT:
        print("  남은 사용량: %s" % ", ".join("%s=%s" % kv for kv in sorted(LIMIT.items())))
    return calls


def export():
    """web/data.json 의 인천 도착편(콜사인 · 인천 도착 예정 UTC)에 출발 예정시각을 붙여 web/dep.json"""
    db = load(); purge(db)
    if not db["f"]:                                             # 캐시가 없으면 지금 배포된 것을 그대로 (이용 기간 안일 때만)
        try:
            with urllib.request.urlopen(LIVE, timeout=30) as r:
                old = json.loads(r.read().decode("utf-8"))
            if ts(old.get("fetched", "")) and (NOW - ts(old["fetched"])).total_seconds() < KEEP_H * 3600:
                json.dump(old, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
                print("dep.json: 배포된 것 유지")
                return 0
        except Exception:
            pass
        if os.path.exists(OUT):
            os.remove(OUT)
        print("dep.json: 자료 없음")
        return 0
    d = json.load(open(DATA, encoding="utf-8"))
    iata = {a.get("iata"): k for k, a in (d.get("airlines") or {}).items() if isinstance(a, dict) and a.get("iata")}
    idx = {}
    for fn, recs in db["f"].items():
        m = re.match(r"^([A-Z0-9]{2})0*(\d+[A-Z]?)$", fn)
        if m and m.group(1) in iata:
            idx.setdefault(iata[m.group(1)] + m.group(2), {}).update(recs)

    def kst(k):
        x = dt.datetime.strptime(k, "%Y%m%d%H%M") + dt.timedelta(hours=9)
        return x.isoweekday(), x.strftime("%H%M")

    def mins(a, b):
        return int((dt.datetime.strptime(a, "%Y%m%d%H%M") - dt.datetime.strptime(b, "%Y%m%d%H%M")).total_seconds() // 60)

    out = {}
    for cs, f in (d.get("flights") or {}).items():
        recs = idx.get(cs)
        if not recs or not isinstance(f, dict):
            continue
        for i in ((f.get("sch") or {}).get("inst") or []):
            if i[2] != "A":
                continue
            sta, ap = i[0], i[3]
            r = recs.get(sta) or next((recs[k] for k in recs if abs(mins(k, sta)) <= 180 and (not recs[k][2] or recs[k][2] == ap)), None)
            if r:
                out.setdefault(cs, {})[sta] = [r[0], r[1], "x"] + ([r[4] if len(r) > 4 else "", r[5] if len(r) > 5 else ""] if len(r) > 4 and (r[4] or r[5]) else [])
                continue
            same = sorted(k for k, v in recs.items() if (not ap or not v[2] or v[2] == ap) and kst(k) == kst(sta))
            if same:
                k = same[-1]; v = recs[k]
                dd = dt.datetime.strptime(sta, "%Y%m%d%H%M") - dt.timedelta(minutes=mins(k, v[0]))
                out.setdefault(cs, {})[sta] = [dd.strftime("%Y%m%d%H%M"), v[1], "d"]
    # 지난 1주 운항 기록: 콜사인 → [[방향, 출발예정UTC, 출발지, 도착지, 출발지시차, 도착지시차, 이륙, 착륙, 게이트출발, 게이트도착(분, 출발예정 기준)]]
    def cs_of(fn):
        m = re.match(r"^([A-Z0-9]{2})0*(\d+[A-Z]?)$", fn)
        return m and m.group(1) in iata and iata[m.group(1)] + m.group(2)

    def rel(t, base):
        return mins(t, base) if t else None
    # 기간은 날짜가 아니라 '마지막으로 받은 때 + 7일'(이용 조건). 착륙 뒤 몇 시간 안에 마지막으로 받으므로
    # 지난주 같은 요일 편이 이번 주 같은 편 출발 무렵까지 남음. 앱도 행마다 받은 때(맨 끝)로 7일을 다시 확인
    hist = {}
    now_k = NOW.strftime("%Y%m%d%H%M")
    for fn, recs in db["f"].items():
        cs = cs_of(fn)
        for sta, v in (recs.items() if cs else ()):
            v = v + [""] * (9 - len(v))
            if v[0] > now_k or not (v[4] or v[6]):
                continue
            hist.setdefault(cs, []).append(["A", v[0], v[2], "ICN", v[1], 540, rel(v[4], v[0]), rel(v[6], v[0]), rel(v[5], v[0]) if v[4] else None, rel(v[7], v[0]), rel(sta, v[0]), v[3]])
    for fn, recs in (db.get("d") or {}).items():
        cs = cs_of(fn)
        for std, v in (recs.items() if cs else ()):
            if std > now_k or not (v[4] or v[6]):
                continue
            hist.setdefault(cs, []).append(["D", std, "ICN", v[0], 540, v[2], rel(v[4], std), rel(v[6], std), rel(v[5], std), rel(v[7], std), rel(v[1], std), v[3]])
    for cs in hist:
        hist[cs].sort(key=lambda r: r[1], reverse=True)
    oldest = min((v[3] for t in ("f", "d") for recs in (db.get(t) or {}).values() for v in recs.values()), default=STAMP)
    json.dump({"generated": STAMP, "fetched": oldest, "near": db.get("near", ""), "src": "AeroDataBox", "f": out, "h": hist}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("dep.json: 콜사인 %d개, %d편 · 지난 기록 %d개 %d편" % (len(out), sum(len(v) for v in out.values()), len(hist), sum(len(v) for v in hist.values())))
    return 0


def main():
    if "--export" in sys.argv:
        return export()
    if not KEY:
        print("AeroDataBox: 키(ADB_KEY) 없음 → 건너뜀")
        return 0
    db = load(); purge(db)
    if "--probe" in sys.argv:                                  # 시험: 도착만 vs 도착+출발 요금 비교, 필드 이름·개수만 (자료는 저장하지 않음)
        now = dt.datetime.now(KST).replace(second=0, microsecond=0)
        a, b = (now - dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M"), (now + dt.timedelta(hours=5, minutes=59)).strftime("%Y-%m-%dT%H:%M")
        out = []
        for d in ("Arrival", "Both"):
            LIMIT.clear(); res = call(a, b, d); time.sleep(2)
            out.append("[%s] 남은 사용량: %s" % (d, ", ".join("%s=%s" % kv for kv in sorted(LIMIT.items()))))
            for side in ("arrivals", "departures"):
                xs = res.get(side) or []
                c = lambda f: sum(1 for x in xs if f(x))
                g = lambda x, s1, s2: ((x.get(s1) or {}).get(s2) or {}).get("utc")
                out.append("  %s %d건 · 출발필드 %s · 도착필드 %s" % (side, len(xs), sorted({k for x in xs for k in (x.get("departure") or {})}), sorted({k for x in xs for k in (x.get("arrival") or {})})))
                out.append("    dep.runway %d · dep.revised %d · arr.runway %d · arr.revised %d · arr.predicted %d · status %s" % (
                    c(lambda x: g(x, "departure", "runwayTime")), c(lambda x: g(x, "departure", "revisedTime")),
                    c(lambda x: g(x, "arrival", "runwayTime")), c(lambda x: g(x, "arrival", "revisedTime")), c(lambda x: g(x, "arrival", "predictedTime")),
                    sorted({x.get("status") for x in xs})))
        print("\n".join(out))
        os.makedirs(os.path.join(ROOT, "probe", "adb"), exist_ok=True)
        open(os.path.join(ROOT, "probe", "adb", "probe.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
        return 0
    if "--sample" in sys.argv:                                 # 시험: 12시간 창 1번만 받고 응답 앞부분 저장 (키는 저장하지 않음)
        now = dt.datetime.now(KST).replace(second=0, microsecond=0)
        res = call(now.strftime("%Y-%m-%dT%H:%M"), (now + dt.timedelta(hours=11, minutes=59)).strftime("%Y-%m-%dT%H:%M"))
        arr = res.get("arrivals") or []
        ok = [x for x in arr if ((x.get("departure") or {}).get("scheduledTime") or {}).get("utc")]
        print("필드:", sorted({k for x in arr[:5] for k in (x.get("departure") or {})}))      # 자료 자체는 저장·출력하지 않음 (보관 조건)
        print("출발 예정시각 있는 편 %d / %d" % (len(ok), len(arr)))
        print("남은 사용량:", ", ".join("%s=%s" % kv for kv in sorted(LIMIT.items())))
        print("시험 호출: 도착편 %d건" % len(arr))
        return 0
    last, near = ts(db.get("checked") or ""), ts(db.get("near") or "")
    if "--force" in sys.argv or not last or (NOW - last).total_seconds() >= EVERY_H * 3600:
        if fetch(db):                                            # 7일치 (첫 창이 '앞으로 12시간'이라 실제 이륙시각도 함께)
            db["checked"] = db["near"] = STAMP
    elif not near or (NOW - near).total_seconds() >= NEAR_H * 3600:
        left = db.get("units_left")
        if left is not None and left < UNITS_FLOOR:
            print("AeroDataBox: 남은 units %s → 실제 이륙시각 받기 쉼" % left)
        elif fetch(db, days=0, back=6, direction="Both"):         # 6시간 전 ~ 6시간 뒤 도착·출발편 1번 (지난 1주 기록 · 실제 이륙)
            db["near"] = STAMP
    else:
        print("AeroDataBox: 예정 %.1f시간 전 · 실제 이륙 %.1f시간 전에 받음 → 건너뜀" % ((NOW - last).total_seconds() / 3600, (NOW - near).total_seconds() / 3600))
    if units_left() is not None:
        db["units_left"] = units_left()
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    json.dump(db, open(RAW, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
