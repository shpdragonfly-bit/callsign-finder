"""인천공항 운항현황 API: 편명 하나만 조회되는지(flight_id) + 응답 항목(터미널·게이트·체크인·주기장 등) 확인. 키 저장 안 함."""
import json, os, urllib.parse, urllib.request, datetime as dt
KEY = os.environ.get("DATA_GO_KR_KEY", ""); k = urllib.parse.quote(KEY, safe="")
OUT = "probe/icn_flt"; os.makedirs(OUT, exist_ok=True)
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 probe"}), timeout=40) as r:
            return str(r.status), r.read().decode("utf-8", "replace")
    except Exception as e:
        b = ""
        try: b = e.read().decode("utf-8", "replace")[:1500]
        except Exception: pass
        return "ERR %s" % e, b
B = "https://apis.data.go.kr/B551177"
res = {}
for name, u in [
  ("all_dep_flt", f"{B}/statusOfAllFltDeOdp/getFltDeparturesDeOdp?serviceKey={k}&type=json&numOfRows=10&pageNo=1&flight_id=KE017"),
  ("all_dep_flt2", f"{B}/statusOfAllFltDeOdp/getFltDeparturesDeOdp?serviceKey={k}&type=json&numOfRows=10&pageNo=1&flightId=KE017"),
  ("all_dep_plain", f"{B}/statusOfAllFltDeOdp/getFltDeparturesDeOdp?serviceKey={k}&type=json&numOfRows=3&pageNo=1&passengerOrCargo=P"),
  ("all_arr_flt", f"{B}/statusOfAllFltDeOdp/getFltArrivalsDeOdp?serviceKey={k}&type=json&numOfRows=10&pageNo=1&flight_id=KE018"),
  ("pax_dep_flt", f"{B}/StatusOfPassengerFlightsDeOdp/getPassengerDeparturesDeOdp?serviceKey={k}&type=json&numOfRows=10&pageNo=1&flight_id=KE017"),
  ("pax_arr_flt", f"{B}/StatusOfPassengerFlightsDeOdp/getPassengerArrivalsDeOdp?serviceKey={k}&type=json&numOfRows=10&pageNo=1&flight_id=KE018"),
]:
    st, b = get(u); b = b.replace(k, "KEY")
    open(os.path.join(OUT, name + ".txt"), "w", encoding="utf-8").write(st + "\n" + b[:20000])
    try:
        d = json.loads(b); body = d["response"]["body"]; it = body.get("items") or []
        it = it.get("item", it) if isinstance(it, dict) else it; it = it if isinstance(it, list) else [it]
        res[name] = {"status": st, "total": body.get("totalCount"), "n": len(it), "keys": sorted(it[0].keys()) if it else [], "first": it[0] if it else None}
    except Exception as e:
        res[name] = {"status": st, "head": b[:300]}
json.dump(res, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({n: [v.get("status"), v.get("total"), v.get("n")] for n, v in res.items()}))
