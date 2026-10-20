"""서울공항리무진 시간표 수집 가능 여부 점검: robots.txt · 노선 목록 · 정류장별 시간표 HTML 을 probe/sab/ 에 저장"""
import os, urllib.request
OUT = "probe/sab"; os.makedirs(OUT, exist_ok=True)
UA = "callsign-finder/1.0 (offline flight assist; timetable check)"
PAGES = {"robots.txt": "https://www.seoulairbus.com/robots.txt", "bus.html": "https://www.seoulairbus.com/bus",
         "bus_6300.html": "https://www.seoulairbus.com/bus/6300", "tt_5_0.html": "https://www.seoulairbus.com/timetableAll/5/0",
         "tt_5_1.html": "https://www.seoulairbus.com/timetableAll/5/1", "terms.html": "https://www.seoulairbus.com/terms"}
for name, url in PAGES.items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            body = "%s %s\n%s" % (r.status, r.headers.get("Content-Type"), r.read().decode("utf-8", "replace"))
    except Exception as e:
        body = "ERR %r" % e
        try: body += "\n" + e.read().decode("utf-8", "replace")[:3000]
        except Exception: pass
    open(os.path.join(OUT, name + ".txt"), "w", encoding="utf-8").write(body[:400000])
    print(name, body[:80].replace("\n", " "))
