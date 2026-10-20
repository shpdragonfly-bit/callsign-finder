"""공항행 시간표 출처 점검 (2차): 운영사 홈페이지 robots·첫 화면 + TAGO 고속/시외버스 API → probe/bg/
인증키는 환경변수 DATA_GO_KR_KEY 에서만 읽고 파일·로그에 남기지 않습니다."""
import datetime as dt, json, os, re, urllib.parse, urllib.request, urllib.error
OUT = "probe/bg"; os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (callsign-finder timetable check)"
KEY = urllib.parse.unquote(os.environ.get("DATA_GO_KR_KEY", "").strip())

SITES = {
    "klimo": "http://www.klimousine.com",
    "kal": "https://www.kallimousine.com",
    "kal2": "http://www.kallimousine.co.kr",
    "ggab": "http://www.ggairportbus.co.kr",
    "ggab2": "https://ggairportbus.co.kr",
    "sunjin": "https://www.sunjinexpress.com",
    "buspia": "http://www.buspia.co.kr",
    "knbus": "http://www.knbus.co.kr",
    "kgbus": "http://www.kgbus.co.kr",
    "kgbus2": "http://www.kyungkibus.co.kr",
    "daewon": "http://www.daewonbus.co.kr",
    "ichbis": "https://bus.incheon.go.kr",
}


def get(url, n=300000):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return "%s %s %s\n%s" % (r.status, r.geturl(), r.headers.get("Content-Type"), r.read()[:n].decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try: b = e.read()[:3000].decode("utf-8", "replace")
        except Exception: b = ""
        return "HTTP %s %s\n%s" % (e.code, url, b)
    except Exception as e:
        return "ERR %r" % e


summ = {}
for k, base in ({} if os.environ.get("SKIP_SITES") else SITES).items():
    home = get(base)
    rob = get(base.rstrip("/") + "/robots.txt", 4000)
    open(os.path.join(OUT, k + ".html.txt"), "w", encoding="utf-8").write(home)
    links = sorted(set(re.findall(r'href=["\']([^"\'#]+)["\'][^>]*>([^<]{0,40})', home)))
    hit = [h + " " + t.strip() for h, t in links if re.search(r"시간|노선|운행|route|time|약관|term", h + t, re.I)]
    summ[k] = {"home": home[:160], "robots": rob[:600], "links": hit[:80]}
    print(k, home[:100].replace("\n", " "))

# TAGO 고속·시외버스 (공공데이터) — 공항행 출발 시각
def api(name, url, params):
    p = dict(params); p["serviceKey"] = KEY; p.setdefault("_type", "json"); p.setdefault("numOfRows", "200")
    body = get(url + "?" + urllib.parse.urlencode(p), 200000)
    if KEY:
        body = body.replace(KEY, "***").replace(urllib.parse.quote(KEY, safe=""), "***")
    open(os.path.join(OUT, "api_" + name + ".txt"), "w", encoding="utf-8").write(body)
    summ["api_" + name] = body[:400]
    print(name, body[:120].replace("\n", " "))
    return body

today = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y%m%d")
B = "https://apis.data.go.kr/1613000/"
def items(body):
    try:
        j = json.loads(body.split("\n", 1)[1]); it = j["response"]["body"]["items"]
        it = it["item"] if isinstance(it, dict) else []
        return it if isinstance(it, list) else [it]
    except Exception:
        return []
terms = {}
for svc, op in (("SuburbsBusInfo", "GetSuberbsBusTrminlList"), ("ExpBusInfo", "GetExpBusTrminlList")):
    allt = []
    for pg in range(1, 8):
        b = api("%s_term_p%d" % (svc, pg), B + svc + "/" + op, {"pageNo": str(pg), "numOfRows": "1000"})
        it = items(b)
        allt += it
        if len(it) < 1000:
            break
    terms[svc] = allt
    json.dump(allt, open(os.path.join(OUT, "terms_%s.json" % svc), "w", encoding="utf-8"), ensure_ascii=False)
    summ[svc + "_terms"] = len(allt)
    summ[svc + "_air"] = [t for t in allt if "공항" in str(t.get("terminalNm", ""))]
exp = terms.get("ExpBusInfo") or []
eair = [t for t in exp if "인천공항" in str(t.get("terminalNm", ""))]
for nm in ("강릉", "동대구", "부산", "광주", "전주", "대전", "청주", "천안", "포항", "울산", "창원", "진주", "목포", "순천", "여수", "춘천", "원주", "속초", "안동", "유성"):
    dep = [t for t in exp if str(t.get("terminalNm", "")).startswith(nm)]
    for d in dep[:3]:
        for a in eair:
            b = api("esched_%s_%s" % (d["terminalId"], a["terminalId"]), B + "ExpBusInfo/GetStrtpntAlocFndExpbusInfo",
                    {"depTerminalId": d["terminalId"], "arrTerminalId": a["terminalId"], "depPlandTime": today})
            it = items(b)
            if it:
                summ["esched_%s_%s" % (d["terminalNm"], a["terminalNm"])] = [len(it), it[:3]]
sub = terms.get("SuburbsBusInfo") or []
air = [t for t in sub if "인천공항" in str(t.get("terminalNm", ""))]
for nm in ("강릉", "동대구", "청주", "천안", "전주"):
    dep = [t for t in sub if str(t.get("terminalNm", "")).startswith(nm)]
    for a in air[:2]:
        if dep:
            b = api("sched_%s_%s" % (nm, a["terminalId"]), B + "SuburbsBusInfo/GetStrtpntAlocFndSuberbsBusInfo",
                    {"depTerminalId": dep[0]["terminalId"], "arrTerminalId": a["terminalId"], "depPlandTime": today})
            summ["sched_%s_%s" % (nm, a["terminalNm"])] = [dep[0], items(b)[:40]]
json.dump(summ, open(os.path.join(OUT, "_summary_api.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
