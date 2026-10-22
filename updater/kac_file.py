#!/usr/bin/env python3
"""
한국공항공사 국제선 항공기스케줄 (공공데이터포털 파일 15003087) → data/kac_intl.json

  python3 updater/kac_file.py [--force]

- 김포·김해·제주 등 한국공항공사 공항의 국제선: 편마다 출발공항 현지 출발시각 · 도착시각 · 운항요일 · 기간
  (인천공항 편은 이 자료에 없음 → AeroDataBox 로 따로)
- 공공데이터포털의 '파일 내려받기'와 같은 절차로 받음 (로그인 불필요, 이용허락 제한 없음).
  포털이 보안 문자(captcha)를 요구하면 받지 않고 기존 파일을 그대로 둠 (우회하지 않음)
- 7일마다 확인. 운항요일은 항공 스케줄 표준대로 출발지 현지 날짜 기준
"""
import datetime as dt
import http.cookiejar
import io
import csv
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "kac_intl.json")
PK, DPK = "15003087", "uddi:04431332-ce66-452f-8c1f-d864269214c1"
B = "https://www.data.go.kr"
UA = "Mozilla/5.0 (callsign-finder weekly schedule check)"
WD = {"월": "1", "화": "2", "수": "3", "목": "4", "금": "5", "토": "6", "일": "7"}

jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(path, data=None, ajax=False):
    h = {"User-Agent": UA, "Referer": "%s/data/%s/fileData.do" % (B, PK)}
    if ajax:
        h.update({"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    r = urllib.request.Request(B + path, data=urllib.parse.urlencode(data).encode() if data is not None else None, headers=h)
    with op.open(r, timeout=60) as f:
        return f.read()


def age_days():
    try:
        g = json.load(open(OUT, encoding="utf-8"))["checked"]
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(g, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).days
    except Exception:
        return 1e9


def main():
    if "--force" not in sys.argv and age_days() < 7:
        print("한국공항공사 국제선 스케줄 파일: 최근에 확인함 → 건너뜀")
        return 0
    req("/data/%s/fileData.do" % PK)                                   # 세션 쿠키
    info = json.loads(req("/tcs/dss/selectFileDataDownload.do", {"publicDataDetailPk": DPK, "publicDataPk": PK, "atchFileId": "",
                                                                   "fileDetailSn": "1", "publicDataTyCode": "PR0051"}, ajax=True))
    if not info.get("status"):
        print("파일 정보 받기 실패"); return 1
    fid, sn = info["atchFileId"], info["fileDetailSn"]
    lim = json.loads(req("/cmm/cmm/check-limit.json", {"atchFileId": fid, "fileDetailSn": sn}, ajax=True))
    if lim.get("needCaptcha"):
        print("포털이 보안 문자를 요구 → 받지 않고 기존 파일 유지"); return 1
    raw = req("/cmm/cmm/fileDownload.do?" + urllib.parse.urlencode({"atchFileId": fid, "fileDetailSn": sn, "dataNm": "한국공항공사_국제선 항공기스케줄"}))
    for enc in ("utf-8-sig", "cp949"):
        try:
            txt = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        fn = (r.get("운항편명") or "").strip().upper()
        if not fn:
            continue
        rows.append({"fn": fn, "dep": (r.get("출발공항") or "").strip(), "arr": (r.get("도착공항") or "").strip(),
                     "std": (r.get("출발시간") or "").replace(":", "").strip(), "sta": (r.get("도착시간") or "").replace(":", "").strip(),
                     "wd": "".join(sorted({WD[c] for c in (r.get("운항요일") or "") if c in WD})),
                     "from": (r.get("시작일자") or "").replace("-", "")[:8], "to": (r.get("종료일자") or "").replace("-", "")[:8]})
    if not rows:
        print("파일에 행이 없음 → 기존 파일 유지"); return 1
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"checked": now, "file": fid, "rows": rows}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("한국공항공사 국제선 스케줄: %d행 (기간 %s ~ %s)" % (len(rows), min(r["from"] for r in rows), max(r["to"] for r in rows)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("한국공항공사 국제선 스케줄 파일 실패: %s (기존 파일 유지)" % e)
        sys.exit(0)
