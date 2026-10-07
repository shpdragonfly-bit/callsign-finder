#!/usr/bin/env python3
"""
Call Sign 데이터 업데이트 도구 (인터넷 연결 상태에서 실행)

  python3 updater/update.py              # 노선 + 기종 수집 후 web/data.json, web/data.js 갱신
  python3 updater/update.py --no-adsb    # 기종(ADS-B) 수집 생략, 노선만 갱신
  python3 updater/update.py --serve      # 갱신 후 같은 Wi-Fi의 폰/패드에서 접속할 수 있게 웹서버 실행

데이터 출처
  - 노선(Call Sign → 출발/도착): Virtual Radar Server standing-data (GitHub 공개 CSV)
  - 공항 정보: 같은 저장소의 airports CSV
  - 기종: adsb.lol / airplanes.live 공개 API에서 현재 비행 중인 항공기를 기종별로 조회해
          Call Sign별로 관측된 기종을 누적 (data/observations.json)

표준 라이브러리만 사용하므로 별도 설치가 필요 없습니다 (Python 3.8+).
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import public_schedule  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "airlines.json")
OVERRIDES = os.path.join(ROOT, "config", "overrides.csv")
OBS_FILE = os.path.join(ROOT, "data", "observations.json")
SCHED_CACHE = os.path.join(ROOT, "data", "public_cache.json")
WEB_DIR = os.path.join(ROOT, "web")

VRS_RAW = "https://raw.githubusercontent.com/vradarserver/standing-data/main"
ADSB_APIS = [
    "https://api.adsb.lol/v2/type/{t}",
    "https://api.airplanes.live/v2/type/{t}",
]
UA = "callsign-finder/1.0 (offline callsign lookup; contact via GitHub)"
OBS_KEEP_DAYS = 120      # 이보다 오래된 기종 관측은 삭제
PRIMARY_WINDOW_DAYS = 45  # 대표 기종 산정에 쓰는 최근 기간

TYPE_NAMES = {
    "A21N": "Airbus A321neo", "A320": "Airbus A320", "A321": "Airbus A321",
    "A332": "Airbus A330-200", "A333": "Airbus A330-300", "A339": "Airbus A330-900neo",
    "A359": "Airbus A350-900", "A35K": "Airbus A350-1000", "A388": "Airbus A380-800",
    "B38M": "Boeing 737 MAX 8", "B39M": "Boeing 737 MAX 9", "B738": "Boeing 737-800",
    "B739": "Boeing 737-900(ER)", "B744": "Boeing 747-400", "B748": "Boeing 747-8",
    "B763": "Boeing 767-300", "B772": "Boeing 777-200(ER)", "B77L": "Boeing 777-200LR/777F",
    "B77W": "Boeing 777-300ER", "B788": "Boeing 787-8", "B789": "Boeing 787-9",
    "B78X": "Boeing 787-10", "BCS1": "Airbus A220-100", "BCS3": "Airbus A220-300",
    "A20N": "Airbus A320neo", "B773": "Boeing 777-300",
}


def log(msg):
    print(msg, flush=True)


def http_get(url, timeout=30, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # 네트워크 오류
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"다운로드 실패: {url} ({last})")


class VrsSource:
    """VRS standing-data를 인터넷(raw.githubusercontent) 또는 로컬 clone에서 읽음."""

    def __init__(self, local_dir=None):
        self.local_dir = local_dir

    def read(self, rel):
        if self.local_dir:
            p = os.path.join(self.local_dir, rel)
            if not os.path.exists(p):
                return None
            with open(p, "rb") as f:
                data = f.read()
        else:
            data = http_get(f"{VRS_RAW}/{rel}")
            if data is None:
                return None
        return data.decode("utf-8-sig")


def parse_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


def normalize_callsign(cs):
    cs = re.sub(r"\s+", "", (cs or "").upper())
    m = re.match(r"^([A-Z]{3})0*([0-9]+[A-Z]*)$", cs)
    if m:
        return m.group(1) + m.group(2)
    return cs


def load_routes(src, airline):
    icao = airline["icao"]
    text = src.read(f"routes/schema-01/{icao[0]}/{icao}-all.csv")
    if text is None:
        log(f"  ! {icao}: 노선 파일이 없습니다")
        return {}
    routes = {}
    for row in parse_csv(text):
        cs = normalize_callsign(row.get("Callsign"))
        codes = [c for c in (row.get("AirportCodes") or "").split("-") if c]
        if cs and len(codes) >= 2:
            routes[cs] = codes
    log(f"  {icao}: 노선 {len(routes)}건")
    return routes


def num(v, nd):
    try:
        x = round(float(v), nd)
        return int(x) if nd == 0 else x
    except (TypeError, ValueError):
        return None


def load_airports(src, codes):
    prefixes = sorted({c[:2] for c in codes if len(c) >= 2})
    airports = {}
    for i, pre in enumerate(prefixes, 1):
        text = src.read(f"airports/schema-01/{pre[0]}/{pre}.csv")
        if text:
            for row in parse_csv(text):
                code = row.get("Code")
                if code in codes:
                    airports[code] = [
                        row.get("IATA") or "",
                        row.get("Name") or "",
                        row.get("Location") or "",
                        row.get("CountryISO2") or "",
                        num(row.get("Latitude"), 4),     # 위도 (일출·일몰 계산용)
                        num(row.get("Longitude"), 4),    # 경도
                        num(row.get("AltitudeFeet"), 0), # 표고 ft
                    ]
        if not src.local_dir and i % 20 == 0:
            log(f"  공항 파일 {i}/{len(prefixes)}")
    log(f"  공항 {len(airports)}/{len(codes)}곳 정보 확보")
    return airports


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def sweep_adsb(type_list, prefixes, obs, today):
    """기종별 현재 비행중 항공기를 조회해 대상 항공사 Call Sign의 기종을 기록."""
    seen = 0
    ok_types = 0
    for t in type_list:
        payload = None
        for api in ADSB_APIS:
            try:
                raw = http_get(api.format(t=t), timeout=25, retries=1)
                if raw:
                    payload = json.loads(raw)
                    break
            except Exception as e:
                log(f"    {t}: {api.split('/')[2]} 실패 ({e.__class__.__name__})")
        if payload is None:
            continue
        ok_types += 1
        for ac in payload.get("ac") or []:
            cs = normalize_callsign(ac.get("flight"))
            if not cs or not cs.startswith(prefixes):
                continue
            typ = (ac.get("t") or t).upper()
            reg = (ac.get("r") or "").upper()
            rec = obs.setdefault(cs, {}).setdefault(typ, {"count": 0, "first": today, "last": ""})
            if rec["last"] != today:  # 하루 1회만 카운트
                rec["count"] += 1
            rec["last"] = today
            if reg:
                rec["reg"] = reg
            seen += 1
        time.sleep(1.0)  # 공개 API 예의상 간격
    log(f"  ADS-B: 기종 {ok_types}/{len(type_list)}종 조회, 대상 항공편 관측 {seen}건")
    return ok_types


def prune_obs(obs, today):
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=OBS_KEEP_DAYS)).isoformat()
    for cs in list(obs):
        for t in list(obs[cs]):
            if obs[cs][t]["last"] < cutoff:
                del obs[cs][t]
        if not obs[cs]:
            del obs[cs]


def rank_types(type_obs, today):
    """최근 관측 빈도 → 최근성 순으로 정렬한 기종 목록."""
    recent = (dt.date.fromisoformat(today) - dt.timedelta(days=PRIMARY_WINDOW_DAYS)).isoformat()
    items = []
    for t, r in type_obs.items():
        items.append((r["last"] >= recent, r["count"], r["last"], t, r))
    items.sort(reverse=True)
    return [{"t": t, "n": r["count"], "last": r["last"], "reg": r.get("reg", "")}
            for _, _, _, t, r in items]


def load_overrides():
    out = {}
    if not os.path.exists(OVERRIDES):
        return out
    with open(OVERRIDES, encoding="utf-8-sig") as f:
        lines = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    for row in csv.DictReader(lines):
        cs = normalize_callsign(row.get("callsign"))
        if cs:
            out[cs] = {k: (row.get(k) or "").strip().upper() for k in ("route", "type")}
            out[cs]["memo"] = (row.get("memo") or "").strip()
    return out


def main():
    ap = argparse.ArgumentParser(description="Call Sign 데이터 업데이트")
    ap.add_argument("--no-adsb", action="store_true", help="기종(ADS-B) 수집 생략")
    ap.add_argument("--vrs-dir", help="VRS standing-data 로컬 clone 경로 (오프라인 테스트용)")
    ap.add_argument("--serve", action="store_true", help="갱신 후 웹서버 실행 (같은 Wi-Fi 기기 접속용)")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    cfg = load_json(CONFIG, None)
    if not cfg:
        sys.exit(f"설정 파일이 없습니다: {CONFIG}")
    airlines = [a for a in cfg["airlines"] if a.get("enabled")]
    if not airlines:
        sys.exit("enabled=true 인 항공사가 없습니다 (config/airlines.json)")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    src = VrsSource(args.vrs_dir)

    log("[1/5] 노선 데이터 수집 (VRS standing-data)")
    routes = {}
    for a in airlines:
        routes.update(load_routes(src, a))

    log("[2/5] 기종 관측 수집 (ADS-B)")
    obs = load_json(OBS_FILE, {})
    prefixes = tuple(a["icao"] for a in airlines)
    adsb_ok = False
    if args.no_adsb:
        log("  생략 (--no-adsb)")
    else:
        adsb_ok = sweep_adsb(cfg.get("type_sweep", []), prefixes, obs, today) > 0
    prune_obs(obs, today)
    os.makedirs(os.path.dirname(OBS_FILE), exist_ok=True)
    with open(OBS_FILE, "w", encoding="utf-8") as f:
        json.dump(obs, f, ensure_ascii=False, indent=0, sort_keys=True)

    log("[3/5] 운항 스케줄 수집 (공공데이터포털)")
    now = dt.datetime.now(dt.timezone.utc)
    sched = public_schedule.build(public_schedule.collect(airlines, SCHED_CACHE, now), now)
    sched = {k: v for k, v in sched.items() if k.startswith(prefixes)}
    log("  스케줄 확보 %d편" % len(sched))

    log("[4/5] 병합 및 수동 보정 적용")
    overrides = load_overrides()
    callsigns = set(routes) | {c for c in obs if c.startswith(prefixes)} | set(overrides) | set(sched)
    flights = {}
    for cs in sorted(callsigns):
        f = {}
        if cs in routes:
            f["r"] = routes[cs]
        types = rank_types(obs.get(cs, {}), today)
        if types:
            f["ty"] = types[:4]
        ov = overrides.get(cs)
        if ov:
            if ov["route"]:
                f["r"] = [c for c in ov["route"].split("-") if c]
            if ov["type"]:
                f["ty"] = [{"t": ov["type"], "n": 0, "last": "", "reg": "", "manual": True}] + \
                          [t for t in f.get("ty", []) if t["t"] != ov["type"]][:3]
            if ov["memo"]:
                f["memo"] = ov["memo"]
        if cs in sched:
            f["sch"] = sched[cs]
        if f:
            flights[cs] = f

    codes = {c for f in flights.values() for c in f.get("r", [])}
    log("[5/5] 공항 정보 수집")
    airports = load_airports(src, codes)

    with_type = sum(1 for f in flights.values() if f.get("ty"))
    data = {
        "version": 1,
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "airlines": {a["icao"]: {k: a.get(k, "") for k in ("iata", "name", "name_en", "telephony")}
                     for a in airlines},
        "type_names": TYPE_NAMES,
        "stats": {"flights": len(flights), "with_type": with_type, "adsb_updated": adsb_ok,
                  "with_sched": sum(1 for f in flights.values() if f.get("sch"))},
        "sources": ["VRS standing-data (routes, airports)", "adsb.lol / airplanes.live (aircraft types)",
                    "공공데이터포털: 인천국제공항공사·한국공항공사 (schedules)"],
        "airports": airports,
        "flights": flights,
    }
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(WEB_DIR, "data.json"), "w", encoding="utf-8") as f:
        f.write(body)
    with open(os.path.join(WEB_DIR, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.CALLSIGN_DATA=" + body + ";\n")
    log(f"\n완료: Call Sign {len(flights)}건 (기종 확보 {with_type}건), 공항 {len(airports)}곳")
    log(f"  → {os.path.join(WEB_DIR, 'index.html')} 를 브라우저로 열면 오프라인에서 조회됩니다.")

    if args.serve:
        serve(args.port)


def serve(port):
    import http.server
    import socket
    import functools
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=WEB_DIR)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "이 PC의 IP"
    log(f"\n웹서버 실행 중: http://localhost:{port}  /  같은 Wi-Fi 기기: http://{ip}:{port}")
    log("종료하려면 Ctrl+C")
    http.server.ThreadingHTTPServer(("0.0.0.0", port), handler).serve_forever()


if __name__ == "__main__":
    main()
