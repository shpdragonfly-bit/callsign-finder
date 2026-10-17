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
    "738": "B738", "739": "B739", "73H": "B738", "73J": "B739", "737": "B737", "7M8": "B38M", "7M9": "B39M", "763": "B763",
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
                body = r.read().decode("utf-8", "replace")
            if "OpenAPI_ServiceResponse" in body or body.lstrip().startswith("<"):
                m = re.search(r'(?:errMsg|returnAuthMsg)["\s:>]+"?([^"<]+)', body)
                last = "API 오류: %s (%s)" % (m.group(1).strip() if m else body[:80], urllib.parse.urlparse(url).path)
                if "LIMITED" in body or "SERVICE_KEY" in body:
                    break                                  # 트래픽 초과·키 오류는 재시도 무의미
            else:
                return json.loads(body)
        except urllib.error.HTTPError as e:
            last = "HTTP %s %s" % (e.code, urllib.parse.urlparse(url).path)
            if e.code in (401, 403):
                break
        except Exception as e:
            last = "%s %s" % (e.__class__.__name__, str(e)[:120])
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
                    "term": (x.get("terminalId") or "").strip(),         # P01=T1 · P02=탑승동 · P03=T2
                    "chk": (x.get("chkinRange") or "").strip() if io == "D" else "",   # 체크인 카운터 (출발편)
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
        if intl and not getattr(fetch_kac, "_logged", False):          # 응답 칸 이름 기록 (기종 칸이 있는지 확인용)
            fetch_kac._logged = True
            log("  한국공항공사 국제선 응답 칸: %s" % ",".join(sorted(intl[0].keys())))
            if dom:
                log("  한국공항공사 국내선 응답 칸: %s" % ",".join(sorted(dom[0].keys())))
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


HIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "type_history.json")
HIST_KEEP_DAYS = 120


def _load_hist():
    try:
        return json.load(open(HIST_FILE, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"since": "", "h": {}}


def history_since():
    return _load_hist().get("since", "")


def update_history(icn, today_kst):
    """편별 기종이 처음·마지막으로 보인 날짜 (인천공항 스케줄, 한국 날짜) → 신규 투입 판단용"""
    hist = _load_hist()
    h = hist.setdefault("h", {})
    for cs, inst in (icn or {}).items():
        for i in inst:
            ty = (i.get("ty") or "").strip()
            if not ty or not i.get("t"):
                continue
            d = dt.datetime.strptime(i["t"], "%Y%m%d%H%M").replace(tzinfo=dt.timezone.utc).astimezone(KST).strftime("%Y%m%d")
            r = h.setdefault(cs, {}).setdefault(ty, [d, d])
            r[0], r[1] = min(r[0], d), max(r[1], d)
            if not hist.get("since") or d < hist["since"]:
                hist["since"] = d
    cut = (today_kst - dt.timedelta(days=HIST_KEEP_DAYS)).strftime("%Y%m%d")
    for cs in list(h):
        for ty in list(h[cs]):
            if h[cs][ty][1] < cut:
                del h[cs][ty]
        if not h[cs]:
            del h[cs]
    os.makedirs(os.path.dirname(HIST_FILE), exist_ok=True)
    with open(HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hist


def next_season_start(today):
    """IATA 시즌 시작일: 3월 마지막 일요일(하계) / 10월 마지막 일요일(동계) 중 오늘 이후 가장 가까운 날"""
    def last_sun(y, m):
        d = dt.date(y, m, 31)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)
    c = sorted(x for y in (today.year, today.year + 1) for x in (last_sun(y, 3), last_sun(y, 10)) if x > today)
    return c[0]


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
        update_history(cache["icn"], today_kst)
    except Exception as e:
        log("  ! 인천공항 수집 실패: %s (이전 값 유지)" % e)
        cache.setdefault("errors", {})["icn"] = "%s %s" % (now.strftime("%Y-%m-%dT%H:%MZ"), e)
    al_key = ",".join(sorted(iata_map))
    # 시즌 스케줄은 하루 한 번 (항공사 구성이 바뀌면 즉시 다시)
    if cache.get("kac_date") != today_kst.isoformat() or not cache.get("kac") or cache.get("kac_airlines") != al_key:
        try:
            cache["kac"] = fetch_kac(key, iata_map, today_kst)
            cache["kac_date"] = today_kst.isoformat()
            cache["kac_airlines"] = al_key
        except Exception as e:
            log("  ! 한국공항공사 수집 실패: %s (이전 값 유지)" % e)
            cache.setdefault("errors", {})["kac"] = "%s %s" % (now.strftime("%Y-%m-%dT%H:%MZ"), e)
    # 다음 시즌 운항표 (시작 45일 전부터, 하루 한 번) → 신규 취항 · 종료 판단
    ns = next_season_start(today_kst)
    if (ns - today_kst).days <= 45:
        if cache.get("kac_next_date") != today_kst.isoformat() or cache.get("kac_next_start") != ns.isoformat():
            try:
                cache["kac_next"] = fetch_kac(key, iata_map, ns)
                cache["kac_next_date"] = today_kst.isoformat()
                cache["kac_next_start"] = ns.isoformat()
            except Exception as e:
                log("  ! 한국공항공사 다음 시즌 수집 실패: %s (이전 값 유지)" % e)
    else:
        cache.pop("kac_next", None); cache.pop("kac_next_start", None)
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
        keep = [[i["t"], i["e"], i["io"], i["ap"], i["ty"], i["reg"], i["gate"], i["st"], i.get("term", ""), i.get("chk", "")] for i in inst if i["t"] >= cutoff]
        out[cs] = {"wd": "".join(str(d) for d in sorted(days)), "src": "ICN", "inst": keep,
                   "cargo": any(i.get("pc") == "C" for i in inst)}
    hist = _load_hist().get("h", {})
    for cs, tys in hist.items():                        # 기종별 처음 보인 날 (신규 투입 판단)
        out.setdefault(cs, {})["tf"] = {t: r[0] for t, r in tys.items()}
    # 다음 시즌 운항표가 실제로 올라왔을 때만 사용: 그 시즌에 새로 시작하는(from ≥ 시작일) 편이 지금 시즌 편의 30% 이상
    # (아직 등록 전이면 API 가 지금 시즌 중 기간이 걸친 편만 돌려줘서, 나머지가 모두 '종료'로 잘못 보임)
    nxt_ok = False
    if cache.get("kac_next_start"):
        ns0 = cache["kac_next_start"].replace("-", "")
        fresh = sum(1 for se in (cache.get("kac_next") or {}).values() if any((x.get("from") or "") >= ns0 for x in se))
        nxt_ok = fresh >= 0.3 * max(1, len(cache.get("kac") or {}))
        log("  다음 시즌(%s) 운항표: %d편 중 새 시즌 등록 %d편 → %s" % (ns0, len(cache.get("kac_next") or {}), fresh, "사용" if nxt_ok else "아직 미등록 · 표시 안 함"))
    if nxt_ok:
        ns = cache["kac_next_start"].replace("-", "")
        for cs, seasons in (cache.get("kac_next") or {}).items():
            uniq = []
            for x in seasons:
                if x not in uniq:
                    uniq.append(x)
            out.setdefault(cs, {})["next"] = uniq[:4]
        out["_next_start"] = ns
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
