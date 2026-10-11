"""실시간 도착 중계(Apps Script) 동작 점검 → probe/bus_rt/relay.txt"""
import json, os, urllib.request
URL = "https://script.google.com/macros/s/AKfycbzTAeL3aNCqJmxqog74kBSE5nhEfoeXI3xEFBwj4bY6nDm9XsfW-4dtoy0q4qRvxbNP/exec"
os.makedirs("probe/bus_rt", exist_ok=True)
Q = {"seoul_6001_seoulst": "?s=s&r=100100412&st=101000230&o=39",
     "seoul_6002_first": "?s=s&r=100100413&st=0&o=1",
     "gbis_8844_onam": "?s=g&r=241005890&st=222000718&o=6",
     "gbis_7000_first": "?s=g&r=241006580&st=0&o=1",
     "bad": "?s=x"}
bs = json.load(open("probe/bus_rt/busstops.json", encoding="utf-8"))["routes"]
for name, n in [("seoul_6002_first", "6002(청량리역)"), ("gbis_7000_first", "7000(안산)")]:
    r = bs[n]; s = r["stops"][len(r["stops"]) // 2]
    Q[name] = f"?s={r['src']}&r={r['id']}&st={s[1]}&o={s[0]}"
out = []
for name, q in Q.items():
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + q, headers={"User-Agent": "probe"}), timeout=60) as r:
            out.append(f"## {name} {q}\n{r.status}\n{r.read().decode('utf-8', 'replace')[:1500]}\n")
    except Exception as e:
        out.append(f"## {name} {q}\nERR {e}\n")
open("probe/bus_rt/relay.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
