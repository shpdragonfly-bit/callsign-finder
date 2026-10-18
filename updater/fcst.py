#!/usr/bin/env python3
"""
공항 도시 일반 날씨 7일 예보 (Open-Meteo) → web/fcst.json

  python3 updater/fcst.py

- 대상: web/data.json 의 공항 (위경도 있는 ICAO 4자리)
- 인증키 불필요. 무료 이용은 비상업용 · 화면에 출처 "Weather data by Open-Meteo.com" 표시 (CC BY 4.0)
- 하루 4번(6시간마다)만 새로 받음. 그 사이 배포(매시간 기상 갱신)에서는 지금 배포된 fcst.json 을 그대로 다시 씀
  → 무료 한도(하루 10,000회, 공항 1곳 = 1회로 계산) 안에서 여유 있게 운영
- 자주 바뀌는 자료라 저장소에 커밋하지 않고, 배포할 때마다 만듭니다 (wx.json 과 같은 방식).

출력 형식 (공항별, 현지 날짜 기준 하루 1칸, 오늘부터 8일):
  {"generated": "...Z", "d": {"KLAX": {"t": "2026-10-18", "c": [날씨코드], "hi": [최고°C], "lo": [최저°C],
                                       "p": [강수확률%], "w": [최대풍속kt], "g": [최대돌풍kt], "wd": [주풍향°]}}}
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
OUT = os.path.join(ROOT, "web", "fcst.json")
LIVE = "https://shpdragonfly-bit.github.io/callsign-finder/fcst.json"
API = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
       "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
       "wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant"
       "&timezone=auto&forecast_days=8&wind_speed_unit=kn")
UA = "callsign-finder/1.0 (offline flight assist; non-commercial)"
CHUNK = 50
REFRESH_H = 5.5          # 배포된 예보가 이보다 오래되면 새로 받음


def fetch(url, timeout=60, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace") or "null")
        except Exception as e:
            last = e
            time.sleep(3 * (i + 1))
    raise last


def live():
    try:
        j = fetch(LIVE, timeout=30, tries=2)
        return j if j and j.get("d") else None
    except Exception:
        return None


def age_h(j):
    try:
        g = dt.datetime.strptime(j["generated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - g).total_seconds() / 3600
    except Exception:
        return 1e9


def rnd(a, n=0):
    return [None if v is None else (round(v) if n == 0 else round(v, n)) for v in (a or [])]


def main():
    force = "--force" in sys.argv
    old = None if force else live()
    if old and age_h(old) < REFRESH_H:
        json.dump(old, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print("예보: 배포된 자료 유지 (%.1f시간 전)" % age_h(old))
        return 0

    data = json.load(open(DATA, encoding="utf-8"))
    pts = []
    for k, v in sorted(data.get("airports", {}).items()):
        if re.fullmatch(r"[A-Z]{4}", k) and len(v) > 5 and v[4] is not None and v[5] is not None:
            pts.append((k, round(float(v[4]), 3), round(float(v[5]), 3)))
    print("예보 수집: 공항 %d곳" % len(pts))
    out, fail = {}, 0
    for i in range(0, len(pts), CHUNK):
        part = pts[i:i + CHUNK]
        url = API.format(lat=",".join(str(p[1]) for p in part), lon=",".join(str(p[2]) for p in part))
        try:
            res = fetch(url)
        except Exception as e:
            print("  ! %d~%d 실패: %s" % (i, i + len(part), e))
            fail += len(part)
            continue
        if isinstance(res, dict):                           # 1곳만 요청하면 목록이 아닌 하나로 옴
            res = [res]
        for (code, _, _), r in zip(part, res or []):
            d = (r or {}).get("daily") or {}
            t = d.get("time") or []
            if not t:
                continue
            out[code] = {
                "t": t[0],
                "c": rnd(d.get("weather_code")),
                "hi": rnd(d.get("temperature_2m_max")),
                "lo": rnd(d.get("temperature_2m_min")),
                "p": rnd(d.get("precipitation_probability_max")),
                "w": rnd(d.get("wind_speed_10m_max")),
                "g": rnd(d.get("wind_gusts_10m_max")),
                "wd": rnd(d.get("wind_direction_10m_dominant")),
            }
        time.sleep(1)
    if not out:
        if old:                                             # 전부 실패: 오래됐어도 기존 자료 유지
            json.dump(old, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            print("  수집 실패 → 기존 fcst.json 유지")
            return 0
        print("  수집 실패")
        return 1
    res = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "d": out}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("  저장: %s (%d곳, 실패 %d곳, %.0fKB)" % (os.path.relpath(OUT, ROOT), len(out), fail, os.path.getsize(OUT) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
