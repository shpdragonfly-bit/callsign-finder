#!/usr/bin/env python3
"""
기번별 운항 기록 (대한항공 · 아시아나 B777 · 777F · B747 · B787 · A350) → fleet 브랜치 reg/{기번}.json

  python3 updater/fleet.py OUTDIR      15분마다: 기번 목록으로 ADS-B 한 번 조회 → 구간 만들기 + 인천공항 실제 시각 합치기

출처
  - 인천 출발·도착 구간: 인천공항 공공데이터 (data/public_cache.json, update.yml 이 6시간마다 갱신) — 계획·실제(게이트) 시각
  - 그 밖의 구간(화물기 해외 간 등): adsb.lol 공개 ADS-B (키 없음 · 한도 유동 → 호출 사이 3초 이상)
    · airplanes.live 는 GitHub 실행 서버에서 403(사전 연락 필요)이라 쓰지 않음 (2026-11-02 시험)
    · 15분마다 기번 목록(약 110대)을 한 번에 조회(/v2/reg/a,b,c…) → 그 순간 날고 있는 우리 항공기만 받음
    · 기번 목록은 인천공항 자료(기종·기번) + 6시간마다 기종별 조회로 새 기체 추가
  - 위치 기록은 남기지 않고 구간(콜사인 · 출발/도착 공항 · 이륙/착륙 추정 시각)만 저장. 2개월(61일) 보관
상태(기번 목록 · 진행 중 구간)는 같은 브랜치의 state.json (공개 ADS-B 위치 몇 개뿐)
"""
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update import normalize_callsign  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICN = os.path.join(ROOT, "data", "public_cache.json")
DATA = os.path.join(ROOT, "web", "data.json")
TYPES = ["B772", "B773", "B77W", "B77L", "B744", "B748", "B788", "B789", "B78X", "A359", "A35K"]
AL = ("KAL", "AAR")
KEEP_DAYS = 61
DISC_H = 6                      # 새 기체 찾기 (기종별 조회) 주기
GAP_H = 16                      # 같은 콜사인이 이 시간 안에 다시 보이면 같은 구간 (대양 위 수신 공백)
LAND_MIN = 40                   # 낮은 고도에서 마지막으로 본 뒤 이만큼 안 보이면 착륙으로 봄
LOW_FT = 8000                   # 이보다 낮으면 공항 근처(이륙 직후 · 착륙 직전)로 봄
UA = "callsign-finder/1.0 (personal, non-commercial; github.com/shpdragonfly-bit/callsign-finder)"
NOW = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
K = lambda d: d.strftime("%Y%m%d%H%M")
P = lambda s: dt.datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=dt.timezone.utc)
LOG = []


def log(m):
    print(m); LOG.append(m)


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def alt_of(ac):
    a = ac.get("alt_baro")
    return 0 if a == "ground" else (a if isinstance(a, (int, float)) else ac.get("alt_geom") or 0)


# ---------- 공항 · 노선 ----------
D = load(DATA, {})
APS = {k: (v[4], v[5], v[0]) for k, v in (D.get("airports") or {}).items() if isinstance(v, list) and len(v) > 5 and v[4] is not None}
ROUTES = {k: f.get("r") or [] for k, f in (D.get("flights") or {}).items() if isinstance(f, dict)}


def near_ap(pos, cands=None, lim=60):
    best = None
    for c in (cands or APS):
        if c in APS:
            d = km(pos, APS[c][:2])
            if best is None or d < best[0]:
                best = (d, c)
    return best[1] if best and (cands or best[0] <= lim) else None


def iata(icao):
    return (APS.get(icao) or (0, 0, ""))[2] or icao or "?"


# ---------- 기번 목록 ----------
def seed_from_icn(st):
    icn = load(ICN, {}).get("icn") or {}
    n = 0
    for cs, rows in icn.items():
        if not cs.startswith(AL):
            continue
        for r in rows:
            reg, ty = (r.get("reg") or "").upper(), (r.get("ty") or "").upper()
            if reg.startswith("HL") and ty in TYPES:
                x = st["regs"].setdefault(reg, {"ty": ty, "al": cs[:3]})
                x["ty"], x["al"] = ty, cs[:3]
                n += 1
    return icn


def discover(st):
    last = st.get("disc")
    if last and (NOW - P(last)).total_seconds() < DISC_H * 3600:
        return
    found = 0
    for t in TYPES:
        try:
            res = get("https://api.adsb.lol/v2/type/" + t)
        except Exception as e:
            log("  기종 조회 실패 %s (%s)" % (t, getattr(e, "code", "") or type(e).__name__)); time.sleep(5); continue
        for ac in res.get("ac") or []:
            cs, reg = normalize_callsign(ac.get("flight")), (ac.get("r") or "").upper()
            if reg.startswith("HL") and cs.startswith(AL):
                x = st["regs"].setdefault(reg, {"ty": t, "al": cs[:3]})
                x["hex"] = ac.get("hex") or x.get("hex", "")
                found += 1
        time.sleep(3.5)
    st["disc"] = K(NOW)
    log("기번 찾기: 비행 중 %d대 확인, 목록 %d대" % (found, len(st["regs"])))


# ---------- ADS-B 한 번 조회 → 구간 ----------
def poll(regs):
    lst = sorted(regs)
    out = []
    for i in range(0, len(lst), 100):
        part = ",".join(lst[i:i + 100])
        for k in range(2):
            try:
                out += get("https://api.adsb.lol/v2/reg/" + part).get("ac") or []
                break
            except Exception as e:
                log("  adsb.lol 실패 (%s)" % (getattr(e, "code", "") or type(e).__name__))
                if k:
                    return None
                time.sleep(8)
        time.sleep(3.5)
    return out


def close(reg, cur, landed, out):
    """진행 중 구간을 끝내 out[reg] 에 추가. landed: 낮은 고도에서 사라짐/지상 확인"""
    cs = cur["cs"]
    route = [c for c in (ROUTES.get(cs) or []) if c in APS]
    p0, p1 = cur["p0"], cur["p1"]
    q = ""
    def seg(pos):                     # 노선(여러 구간)에서 이 위치가 지나는 구간 (A→B 사이 우회 거리가 가장 작은 것)
        pr = [(km(APS[x][:2], pos[:2]) + km(pos[:2], APS[y][:2]) - km(APS[x][:2], APS[y][:2]), x, y) for x, y in zip(route, route[1:])]
        return min(pr)[1:] if pr else (None, None)
    dep = near_ap(p0[:2]) if p0[2] < LOW_FT else None
    if not dep:
        dep = seg(p0)[0]; q += "d"                                   # 처음 본 곳이 높은 고도 → 노선에서 추정
    arr = near_ap(p1[:2]) if landed and p1[2] < LOW_FT else None
    if not arr:
        arr = seg(p1)[1]; q += "a"
    if p0[2] >= LOW_FT:
        q += "o"                                                       # 이륙 시각 = 처음 본 시각 (실제는 더 이름)
    if not landed:
        q += "n"                                                       # 착륙 미확인 = 마지막 본 시각
    leg = {"c": cs, "d": iata(dep) if dep else "?", "a": iata(arr) if arr else "?", "o": cur["t0"], "n": cur["t1"], "src": "adsb"}
    if q:
        leg["q"] = q
    out.setdefault(reg, []).append(leg)


def track(st, acs):
    cur, out = st.setdefault("cur", {}), {}
    seen = set()
    for ac in acs or []:
        reg = (ac.get("r") or "").upper()
        if reg not in st["regs"]:
            continue
        cs = normalize_callsign(ac.get("flight")) or (cur.get(reg) or {}).get("cs", "")
        lat, lon = ac.get("lat"), ac.get("lon")
        if lat is None or lon is None:
            continue
        seen.add(reg)
        alt, gs = alt_of(ac), ac.get("gs") or 0
        t = K(NOW - dt.timedelta(seconds=float(ac.get("seen_pos") or 0)))
        pos = [round(lat, 3), round(lon, 3), int(alt)]
        c = cur.get(reg)
        if ac.get("alt_baro") == "ground" or gs < 60:                  # 지상: 진행 중 구간이 있으면 착륙
            if c:
                c["p1"] = pos; close(reg, c, True, out); cur.pop(reg, None)
            continue
        if c and c["cs"] == cs and (P(t) - P(c["t1"])).total_seconds() < GAP_H * 3600:
            c["t1"], c["p1"] = t, pos
            continue
        if c:
            close(reg, c, c["p1"][2] < LOW_FT, out)
        cur[reg] = {"cs": cs, "t0": t, "p0": pos, "t1": t, "p1": pos}
    for reg in list(cur):
        if reg in seen:
            continue
        c = cur[reg]; age = (NOW - P(c["t1"])).total_seconds() / 60
        if (c["p1"][2] < LOW_FT and age > LAND_MIN) or age > GAP_H * 60:
            close(reg, c, c["p1"][2] < LOW_FT, out); cur.pop(reg)
    return out, len(seen)


# ---------- 저장 ----------
def save(outdir, st, new, icn):
    os.makedirs(os.path.join(outdir, "reg"), exist_ok=True)
    cut = K(NOW - dt.timedelta(days=KEEP_DAYS))
    idx, changed = {}, 0
    for reg, info in sorted(st["regs"].items()):
        p = os.path.join(outdir, "reg", reg + ".json")
        f = load(p, {"reg": reg, "legs": [], "icn": []})
        before = json.dumps(f, sort_keys=True)
        f["ty"], f["al"] = info.get("ty", ""), info.get("al", "")
        f["legs"] = [x for x in f.get("legs", []) if x.get("o", "") >= cut] + new.get(reg, [])
        # 인천공항 자료: 이 기번이 배정된 지난 편(출발·도착 확인된 것) — 계획·실제(게이트) 시각
        ic = {(x["c"], x["t"]): x for x in f.get("icn", []) if x.get("t", "") >= cut}
        for cs, rows in icn.items():
            if not cs.startswith(AL):
                continue
            for r in rows:
                if (r.get("reg") or "").upper() == reg and r.get("st") in ("출발", "도착", "착륙") and r.get("t", "") <= K(NOW):
                    ic[(cs, r["t"])] = {"c": cs, "io": r.get("io"), "ap": r.get("ap"), "t": r["t"], "e": r.get("e") or "", "st": r.get("st")}
        f["icn"] = sorted(ic.values(), key=lambda x: x["t"])
        f["legs"].sort(key=lambda x: x["o"])
        if json.dumps(f, sort_keys=True) != before:
            json.dump(f, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")); changed += 1
        allt = [x["o"] for x in f["legs"]] + [x["t"] for x in f["icn"]]
        idx[reg] = {"ty": f["ty"], "al": f["al"], "n": len(f["legs"]) + len(f["icn"]), "last": max(allt) if allt else ""}
    json.dump({"updated": K(NOW), "keep_days": KEEP_DAYS, "types": TYPES,
               "src": ["인천공항 공공데이터", "airplanes.live / adsb.lol (ADS-B)"], "regs": idx},
              open(os.path.join(outdir, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return changed


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_fleet")
    STATE = os.path.join(outdir, "state.json")
    st = load(STATE, {"regs": {}, "cur": {}})
    st.setdefault("regs", {}); st.setdefault("cur", {})
    icn = seed_from_icn(st)
    discover(st)
    acs = poll(st["regs"])
    if acs is None:
        new, n = {}, 0
    else:
        new, n = track(st, acs)
    ch = save(outdir, st, new, icn)
    st["last"] = K(NOW)
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    log("기번 %d대 · 비행 중 %d대 · 진행 중 구간 %d · 새로 끝난 구간 %d · 바뀐 파일 %d" % (len(st["regs"]), n, len(st["cur"]), sum(len(v) for v in new.values()), ch))
    lp = os.path.join(outdir, "log.txt")
    old = open(lp, encoding="utf-8").read().splitlines()[-499:] if os.path.exists(lp) else []
    open(lp, "w", encoding="utf-8").write("\n".join(old + [K(NOW) + " " + " | ".join(LOG)]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
