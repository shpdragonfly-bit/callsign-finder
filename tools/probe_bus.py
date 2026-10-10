"""출퇴근 탭 자료원 점검: 후보 API 호출 결과(앞부분)와 공공데이터포털 명세 페이지를 probe/bus/ 에 저장. 인증키 값은 저장하지 않음."""
import os, re, json, urllib.request, urllib.parse
KEY = os.environ.get("DATA_GO_KR_KEY", "")
OUT = "probe/bus"; os.makedirs(OUT, exist_ok=True)
def get(url, n=4000):
    url = url.replace("http://apis.data.go.kr", "https://apis.data.go.kr")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 callsign-finder probe"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return "%s %s\n%s" % (r.status, r.headers.get("Content-Type"), r.read().decode("utf-8", "replace")[:n])
    except Exception as e:
        body = ""
        try: body = e.read().decode("utf-8", "replace")[:3000]
        except Exception: pass
        return "ERR %s\n%s" % (e, body)
k = urllib.parse.quote(KEY, safe="")
CALLS = {
  "icn_businfo_area1": f"https://apis.data.go.kr/B551177/BusInformation/getBusInfo?serviceKey={k}&type=json&numOfRows=3&pageNo=1&area=1",
  "icn_businfo_noarea": f"https://apis.data.go.kr/B551177/BusInformation/getBusInfo?serviceKey={k}&type=json&numOfRows=3&pageNo=1",
  "icn_businfo_v2": f"http://apis.data.go.kr/B551177/BusInformation/getBusInfo?serviceKey={k}&type=json&numOfRows=3&pageNo=1&area=2",
  "icn_shtb_pred": f"https://apis.data.go.kr/B551177/ShtbusInfo/getShtbArrivalPredInfo?serviceKey={k}&type=json&numOfRows=5&pageNo=1&routeId=11100009",
  "seoul_route_6001": f"http://ws.bus.go.kr/api/rest/busRouteInfo/getBusRouteList?serviceKey={k}&strSrch=6001&resultType=json",
  "gbis_route_8844": f"https://apis.data.go.kr/6410000/busrouteservice/v2/getBusRouteListv2?serviceKey={k}&keyword=8844&format=json",
  "gbis_route_8844_v1": f"https://apis.data.go.kr/6410000/busrouteservice/getBusRouteList?serviceKey={k}&keyword=8844",
}
res = {}
for name, url in CALLS.items():
    txt = get(url); res[name] = txt.replace(k, "KEY")[:4000]
PAGES = {"page_15095015": "https://www.data.go.kr/data/15095015/openapi.do",
         "page_15098224": "https://www.data.go.kr/data/15098224/openapi.do",
         "search_bus": "https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=%EC%9D%B8%EC%B2%9C%EA%B5%AD%EC%A0%9C%EA%B3%B5%ED%95%AD%EA%B3%B5%EC%82%AC%20%EB%B2%84%EC%8A%A4&recmSe=N&publicDataPk=&brm=&instt=&svcType=&kwrdArray=&extsn=&coreDataNmArray="}
for name, url in PAGES.items():
    html = get(url, 400000)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text); text = re.sub(r"[ \t\r\f\v]+", " ", text); text = re.sub(r"\n\s*\n+", "\n", text)
    res[name] = text[:12000]
for n, t in res.items():
    open(os.path.join(OUT, n + ".txt"), "w", encoding="utf-8").write(t)
print({n: t[:120] for n, t in res.items()})
