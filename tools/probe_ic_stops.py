"""인천 공항버스 노선만 TAGO 로 정류장 수집 → probe/bus_ic/ic_stops.json (진행 기록 출력). 키 저장 안 함."""
import json, os, sys, time, urllib.request
sys.path.insert(0, "updater")
import busstops as B
def get(url):
    for a in range(2):
        try:
            B.CALLS += 1
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "callsign-finder"}), timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("  retry", a, str(e)[:60], flush=True); time.sleep(3)
    return None
B.get = get
bus = json.load(open("web/bus.json", encoding="utf-8"))
out, miss, t0 = {}, [], time.time()
for r in bus["routes"]:
    if r.get("a") != "인천": continue
    num, label = B.split(r["n"])
    g = B.tago(num, label)
    print(f"{r['n']}: {'OK ' + g['id'] + ' ' + str(len(g['stops'])) if g else 'miss'} ({time.time()-t0:.0f}s)", flush=True)
    if g: out[r["n"]] = g
    else: miss.append(r["n"])
os.makedirs("probe/bus_ic", exist_ok=True)
json.dump({"routes": out, "missing": miss, "calls": B.CALLS}, open("probe/bus_ic/ic_stops.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
