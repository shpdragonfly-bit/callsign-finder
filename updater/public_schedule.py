"""
공공데이터포털 운항 스케줄 수집 (인증키: 환경변수 DATA_GO_KR_KEY)

  - 인천국제공항공사 항공기 운항 현황 상세 조회 (statusOfAllFltDeOdp)
      여객·화물, 출발·도착, 조회일 기준 D-3 ~ D+6. 예정/변경 시각, 기종(IATA), 등록부호, 게이트
  - 한국공항공사 항공기 운항 스케줄 정보 (flight-schedule /dom, /int)
      김포·김해·제주 등 14개 공항의 시즌 스케줄: 운항 요일, 예정 시각, 운항 기간

결과는 data/public_cache.json 에 보관해서, 다음 수집이 실패해도 마지막 성공값을 씁니다.
시각은 모두 UTC 'YYYYMMDDHHMM' 으로 변환해 저장합니다 (원본은 한국시각).
"""
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ICN_URL = "https://apis.data.go.kr/B551177/statusOfAllFltDeOdp/{op}"
KAC_URL = "https://apis.data.go.kr/B551178/flight-schedule/{op}"
KST = dt.timezone(dt.timedelta(hours=9))
UA = "callsign-finder/1.0"

# 공항 API의 IATA 기종코드 → ICAO 기종코드
IATA_EQUIP = {
    # 74J = 747-8I (대한항공 표기)
    "748": "B748", "74H": "B748", "74J": "B748", "74N": "B748", "744": "B744", "74F": "B744", "74Y": "B744", "74X": "B744",
    "77W": "B77W", "772": "B772", "77L": "B77L", "77F": "B77L", "77X": "B77L", "773": "B773",
    "788": "B788", "789": "B789", "781": "B78X", "78J": "B78X",
    "738": "B738", "739": "B739", "7M8": "B38M", "7M9": "B39M", "763": "B763",
    "388": "A388", "332": "A332", "333": "A333", "339": "A339", "359": "A359", "351": "A35K",
    "321": "A321", "32Q": "A21N", "32N": "A20N", "320": "A320", "221": "BCS1", "223": "BCS3",
}


def log(msg):
    print(msg, flush=True)


def _get_json(url, params, key, retries=2):
    q = dict(params)
    q["serviceKey"] = key
    full = url + "?" + urllib.parse.urlencode(q)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (401, 403):
                break
        except Exception as e:
            last = e.__class__.__name__
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last)


def _items(resp):
    body = (resp.get("response") or {}).get("body") or {}
    it = body.get("items") or []
    if isinstance(it, dict):
        it = it.get("item") or []
    if isinstance(it, dict):
        it = [it]
    return int(body.get("totalCount") or 0), it


def _paged(url, params, key, rows=1000, max_pages=60):
    out, page = [], 1
    while page <= max_pages:
        total, items = _items(_get_json(url, dict(params, pageNo=page, numOfRows=rows, type="json"), key))
        out.extend(items)
        if not items or len(out) >= total:
            break
        page += 1
        time.sleep(0.5)
    return out


def kst_to_utc(s):
    """'YYYYMMDDHHMM' (KST) → 'YYYYMMDDHHMM' (UTC)"""
    if not s or len(s) < 12:
        return ""
    t = dt.datetime.strptime(s[:12], "%Y%m%d%H%M").replace(tzinfo=KST)
    return t.astimezone(dt.timezone.utc).strftime("%Y%m%d%H%M")


def flight_to_callsign(fid, iata_map):
    """'KE017' → 'KAL17' (설정된 항공사만)"""
    m = re.match(r"^([A-Z0-9]{2})0*(\d+[A-Z]?)$", (fid or "").strip().upper())
    if not m or m.group(1) not in iata_map:
        return None
    return iata_map[m.group(1)] + m.group(2)


def fetch_icn(key, iata_map):
    """인천공항 D-3 ~ D+6 운항편 → {callsign: [instance...]}"""
    out = {}
    calls = 0
    for op, io in (("getFltDeparturesDeOdp", "D"), ("getFltArrivalsDeOdp", "A")):
        for pc in ("P", "C"):
            items = _paged(ICN_URL.format(op=op), {"passengerOrCargo": pc}, key)
            calls += 1
            for x in items:
                if (x.get("codeshare") or "").lower() == "slave":
                    continue                                  # 코드셰어 판매편은 제외 (운항편만)
                cs = flight_to_callsign(x.get("flightId"), iata_map)
                if not cs:
                    continue
                sub = (x.get("aircraftSubtype") or "").strip().upper()
                out.setdefault(cs, []).append({
                    "t": kst_to_utc(x.get("scheduleDatetime")),          # 예정 (UTC)
                    "e": kst_to_utc(x.get("estimatedDatetime")),         # 변경 (UTC)
                    "io": io,                                            # D=인천 출발, A=인천 도착
                    "ap": (x.get("airportCode") or "").upper(),          # 상대 공항 IATA
                    "ty": IATA_EQUIP.get(sub, sub),
                    "reg": (x.get("aircraftRegNo") or "").strip().upper(),
                    "gate": (x.get("gateNumber") or "").strip(),
                    "st": (x.get("remark") or "").strip(),
                    "pc": "C" if pc == "C" else "P",
                })
            log("  인천공항 %s/%s: %d건" % ("출발" if io == "D" else "도착", "화물" if pc == "C" else "여객", len(items)))
    for cs in out:
        uniq = {(i["t"], i["io"]): i for i in out[cs]}
        out[cs] = sorted(uniq.values(), key=lambda i: i["t"])
    return out


def _wd(row, prefix):
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return "".join(str(i + 1) for i, n in enumerate(names) if (row.get(prefix + n) or "").upper() == "Y")


def _date(s):
    return (s or "")[:10].replace("-", "")


def fetch_kac(key, iata_map, today):
    """한국공항공사 시즌 스케줄 (오늘 유효한 것) → {callsign: [season...]}"""
    out = {}
    ymd = today.strftime("%Y%m%d")
    for iata in iata_map:
        # 한국공항공사 API는 한 번에 100건 이하로 요청해야 함
        dom = _paged(KAC_URL.format(op="dom"), {"schAirLine": iata, "schDate": ymd}, key, rows=100)
        for x in dom:
            cs = flight_to_callsign(x.get("domesticNum"), iata_map)
            if not cs or not (_date(x.get("domesticStdate")) <= ymd <= _date(x.get("domesticEddate"))):
                continue
            out.setdefault(cs, []).append({
                "kind": "dom", "dep": x.get("startcityCode") or "", "arr": x.get("arrivalcityCode") or "",
                "std": x.get("domesticStartTime") or "", "sta": x.get("domesticArrivalTime") or "",
                "wd": _wd(x, "domestic"), "from": _date(x.get("domesticStdate")), "to": _date(x.get("domesticEddate")),
            })
        intl = _paged(KAC_URL.format(op="int"), {"schAirLine": iata, "schDate": ymd}, key, rows=100)
        for x in intl:
            cs = flight_to_callsign(x.get("internationalNum"), iata_map)
            if not cs or not (_date(x.get("internationalStdate")) <= ymd <= _date(x.get("internationalEddate"))):
                continue
            # OUT: a(한국 공항) 출발 → b, 시각=출발 현지시각 / IN: b → a 도착, 시각=도착 현지시각
            out.setdefault(cs, []).append({
                "kind": "int", "io": x.get("internationalIoType") or "",
                "a": x.get("airportCode") or "", "b": x.get("cityCode") or "",
                "time": x.get("internationalTime") or "",
                "wd": _wd(x, "international"), "from": _date(x.get("internationalStdate")), "to": _date(x.get("internationalEddate")),
            })
        log("  한국공항공사 %s: 국내선 %d건, 국제선 %d건 (오늘 유효 %d편)" % (iata, len(dom), len(intl), len(out)))
    return out


def collect(airlines, cache_path, now):
    """수집 후 캐시 반영. 키가 없거나 실패하면 캐시(마지막 성공값)를 그대로 반환."""
    key = urllib.parse.unquote(os.environ.get("DATA_GO_KR_KEY", "").strip())
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = {}
    if not key:
        log("  인증키(DATA_GO_KR_KEY) 없음 → 스케줄 수집 생략")
        return cache
    iata_map = {a["iata"]: a["icao"] for a in airlines if a.get("iata")}
    today_kst = now.astimezone(KST).date()
    try:
        cache["icn"] = fetch_icn(key, iata_map)
        cache["icn_at"] = now.strftime("%Y-%m-%dT%H:%MZ")
    except Exception as e:
        log("  ! 인천공항 수집 실패: %s (이전 값 유지)" % e)
    if cache.get("kac_date") != today_kst.isoformat() or not cache.get("kac"):   # 시즌 스케줄은 하루 한 번
        try:
            cache["kac"] = fetch_kac(key, iata_map, today_kst)
            cache["kac_date"] = today_kst.isoformat()
        except Exception as e:
            log("  ! 한국공항공사 수집 실패: %s (이전 값 유지)" % e)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    return cache


def build(cache, now):
    """data.json 에 넣을 편별 스케줄 {callsign: {...}}"""
    out = {}
    cutoff = (now - dt.timedelta(hours=24)).strftime("%Y%m%d%H%M")   # 하루 전 이후 편만
    for cs, inst in (cache.get("icn") or {}).items():
        days = set()
        for i in inst:
            if i["t"]:
                kst = dt.datetime.strptime(i["t"], "%Y%m%d%H%M").replace(tzinfo=dt.timezone.utc).astimezone(KST)
                days.add(kst.isoweekday())
        keep = [[i["t"], i["e"], i["io"], i["ap"], i["ty"], i["reg"], i["gate"], i["st"]] for i in inst if i["t"] >= cutoff]
        out[cs] = {"wd": "".join(str(d) for d in sorted(days)), "src": "ICN", "inst": keep,
                   "cargo": any(i.get("pc") == "C" for i in inst)}
    for cs, seasons in (cache.get("kac") or {}).items():
        e = out.setdefault(cs, {})
        uniq = []
        for x in seasons:
            if x not in uniq:
                uniq.append(x)
        e["season"] = uniq[:4]
        if not e.get("wd"):
            wd = set()
            for s in seasons:
                wd.update(s["wd"])
            e["wd"] = "".join(sorted(wd))
            e["src"] = "KAC"
    return out
