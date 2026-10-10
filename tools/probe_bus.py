"""출퇴근 탭 자료원 점검: 후보 API 호출 결과(앞부분)와 공공데이터포털 명세 페이지를 probe/bus/ 에 저장. 인증키 값은 저장하지 않음."""
import os, re, json, urllib.request, urllib.parse
KEY = os.environ.get("DATA_GO_KR_KEY", "")
OUT = "probe/bus"; os.makedirs(OUT, exist_ok=True)
def get(url, n=12000):
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
  "icn_businfo_all": f"https://apis.data.go.kr/B551177/BusInformation/getBusInfo?serviceKey={k}&type=json&numOfRows=500&pageNo=1",
  "icn_shtb_pred": f"https://apis.data.go.kr/B551177/ShtbusInfo/getShtbArrivalPredInfo?serviceKey={k}&type=json&numOfRows=50&pageNo=1&routeId=11100009",
  "icn_shtb_pred_noroute": f"https://apis.data.go.kr/B551177/ShtbusInfo/getShtbArrivalPredInfo?serviceKey={k}&type=json&numOfRows=200&pageNo=1",
  "seoul_route_6001": f"http://ws.bus.go.kr/api/rest/busRouteInfo/getBusRouteList?serviceKey={k}&strSrch=6001&resultType=json",
  "seoul_route_6002": f"http://ws.bus.go.kr/api/rest/busRouteInfo/getBusRouteList?serviceKey={k}&strSrch=6002&resultType=json",
  "gbis_route_8844": f"https://apis.data.go.kr/6410000/busrouteservice/v2/getBusRouteListv2?serviceKey={k}&keyword=8844&format=json",
  "incheon_route_list": f"https://apis.data.go.kr/6280000/busRouteService/getBusRouteNo?serviceKey={k}&numOfRows=5&pageNo=1&routeNo=306",
  "tago_route_icn": f"https://apis.data.go.kr/1613000/BusRouteInfoInqireService/getRouteNoList?serviceKey={k}&cityCode=23&routeNo=6001&_type=json",
}
res = {}
for name, url in CALLS.items():
    txt = get(url, 200000 if name == "icn_businfo_all" else 12000); res[name] = txt.replace(k, "KEY")[:60000] if name == "icn_businfo_all" else txt.replace(k, "KEY")[:12000]

for n, t in res.items():
    open(os.path.join(OUT, n + ".txt"), "w", encoding="utf-8").write(t)
print({n: t[:120] for n, t in res.items()})
