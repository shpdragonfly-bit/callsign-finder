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
  "shtb_time_wd": f"https://apis.data.go.kr/B551177/ShtbusInfo/getShtbTimeInfo?serviceKey={k}&type=json&day_type=1&numOfRows=5000&pageNo=1",
  "shtb_time_we": f"https://apis.data.go.kr/B551177/ShtbusInfo/getShtbTimeInfo?serviceKey={k}&type=json&day_type=2&numOfRows=5000&pageNo=1",
  "shtb_pred_now": f"https://apis.data.go.kr/B551177/ShtbusInfo/getShtbArrivalPredInfo?serviceKey={k}&type=json&numOfRows=500&pageNo=1",
}
res = {}
for name, url in CALLS.items():
    txt = get(url, 3000000); res[name] = txt.replace(k, "KEY")

for n, t in res.items():
    open(os.path.join(OUT, n + ".txt"), "w", encoding="utf-8").write(t)
print({n: t[:120] for n, t in res.items()})
