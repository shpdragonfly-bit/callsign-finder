"""인천 버스 API: 데이터셋 페이지에서 요청 주소·오퍼레이션 뽑기 + 주소 변형 시험 (키 값은 저장 안 함)."""
import json, os, re, time, urllib.parse, urllib.request, html as H
OUT = "probe/bus_ic/spec"; os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (callsign-finder probe)"
KEY = os.environ.get("DATA_GO_KR_KEY", ""); k = urllib.parse.quote(KEY, safe="")
def get(u, t=30):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=t) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        b = ""
        try: b = e.read().decode("utf-8", "replace")[:2000]
        except Exception: pass
        return "ERR %s" % e, b
pages = {}
for did in ["15059084", "15058487", "15056529", "15059206"]:
    st, b = get(f"https://www.data.go.kr/data/{did}/openapi.do")
    txt = H.unescape(re.sub(r"<script.*?</script>|<style.*?</style>", " ", b, flags=re.S))
    urls = sorted(set(re.findall(r"https?://apis\.data\.go\.kr/6280000/[A-Za-z0-9_/]+", txt)))
    ops = sorted(set(re.findall(r"\b(get[A-Z][A-Za-z0-9]+)\b", txt)))
    plain = re.sub(r"<[^>]+>", " ", txt); plain = re.sub(r"\s+", " ", plain)
    i = plain.find("요청주소")
    pages[did] = {"status": str(st), "urls": urls, "ops": ops, "around": plain[max(0, i - 200): i + 1500] if i >= 0 else plain[:1500]}
    open(os.path.join(OUT, f"page_{did}.html"), "w", encoding="utf-8").write(b[:300000])
    time.sleep(1)
json.dump(pages, open(os.path.join(OUT, "pages.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# 명세 샘플 값으로 시험 (승인 직후 '04 HTTP 에러'가 키 등록 지연인지 확인)
tries = {}
B = "https://apis.data.go.kr/6280000"
for path, q in [("busRouteService/getBusRouteSectionList", "routeId=169000096"), ("busRouteService/getBusRouteNo", "routeNo=306"),
                ("busArrivalService/getAllRouteBusArrivalList", "bstopId=165000111"), ("busStationService/getBusStationNmList", "bstopNm=%EC%9D%B8%EC%B2%9C%EA%B3%B5%ED%95%AD"),
                ("busLocationService/getBusRouteLocation", "routeId=165000111")]:
    st, b = get(f"{B}/{path}?serviceKey={k}&pageNo=1&numOfRows=5&{q}")
    tries[path] = [str(st), re.sub(r"\s+", " ", b.replace(k, "KEY").replace(KEY, "KEY"))[:600]]
    time.sleep(0.5)
json.dump(tries, open(os.path.join(OUT, "tries.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({d: {"urls": p["urls"], "ops": p["ops"]} for d, p in pages.items()}, ensure_ascii=False))
