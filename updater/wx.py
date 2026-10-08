#!/usr/bin/env python3
"""
NOAA aviationweather.gov 에서 METAR / TAF 수집 → web/wx.json

  python3 updater/wx.py

- 대상 공항: web/data.json 에 있는 공항 (ICAO 4자리)
- 인증키 불필요. 브라우저에서 직접 부를 수 없는 API(CORS 미지원)라 서버에서 받아 배포합니다.
- 자주 바뀌는 자료라 저장소에 커밋하지 않고, 배포할 때마다 새로 만듭니다 (GitHub Actions 매시간).
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "web", "data.json")
OUT = os.path.join(ROOT, "web", "wx.json")
API = "https://aviationweather.gov/api/data/{kind}?ids={ids}&format=json"
UA = "callsign-finder/1.0 (offline flight assist)"
CHUNK = 100


def get(kind, ids):
    url = API.format(kind=kind, ids=urllib.parse.quote(",".join(ids), safe=","))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace").strip()
            return json.loads(body) if body else []
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    print("  ! %s 실패: %s" % (kind, last))
    return None


def main():
    data = json.load(open(DATA, encoding="utf-8"))
    icaos = sorted(k for k in data.get("airports", {}) if re.fullmatch(r"[A-Z]{4}", k))
    wx, ok = {}, 0
    for i in range(0, len(icaos), CHUNK):
        part = icaos[i:i + CHUNK]
        metars = get("metar", part)
        tafs = get("taf", part)
        if metars is None and tafs is None:
            continue
        ok += 1
        for m in metars or []:
            e = wx.setdefault(m.get("icaoId"), {})
            if e.get("mo", 0) < (m.get("obsTime") or 0):       # 같은 공항이 여러 개면 최신 관측
                e.update(m=m.get("rawOb", ""), mo=m.get("obsTime"), cat=m.get("fltCat") or "")
        for t in tafs or []:
            e = wx.setdefault(t.get("icaoId"), {})
            issued = t.get("issueTime") or ""
            if e.get("ti", "") >= issued:
                continue
            e.update(t=t.get("rawTAF", ""), ti=issued, vf=t.get("validTimeFrom"), vt=t.get("validTimeTo"),
                     f=[[f.get("timeFrom"), f.get("timeTo"), f.get("fcstChange") or "", f.get("probability") or 0]
                        for f in t.get("fcsts") or []])
        time.sleep(1)
    if not ok:
        print("기상 자료를 받지 못했습니다 (wx.json 유지)")
        return 1
    out = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "NOAA aviationweather.gov", "wx": wx}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("기상: 공항 %d곳 중 METAR %d · TAF %d" % (len(icaos), sum(1 for v in wx.values() if v.get("m")),
                                                 sum(1 for v in wx.values() if v.get("t"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
