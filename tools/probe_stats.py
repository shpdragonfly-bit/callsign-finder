"""통계 웹 앱 수신 점검: 테스트 기록 1건을 보내고 응답을 probe/stats.txt 에 저장"""
import json, os, urllib.request, datetime as dt
URL = "https://script.google.com/macros/s/AKfycbxpGH2YmVEU-CAiY-NTD7F1z94H63G3m3gJC5EssXrtgWjDwKipnEVTb-Ivz0oPQiNI/exec"
body = {"v": 1, "d": "testprobe01", "dev": "TEST", "ver": "probe",
        "e": [{"t": dt.datetime.now(dt.timezone.utc).isoformat(), "a": "실행", "al": "KAL", "m": "테스트"}]}
req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "text/plain"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        res = "%s %s" % (r.status, r.read().decode("utf-8", "replace")[:300])
except Exception as e:
    res = "ERR %s" % e
os.makedirs("probe", exist_ok=True)
open("probe/stats.txt", "w").write(res + "\n")
print(res)
