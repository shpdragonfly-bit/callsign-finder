#!/usr/bin/env python3
"""
환율 수집 → web/fx.json  (원화 기준: 외화 1단위 = 몇 원)

  python3 updater/fx.py

- 1순위: 한국수출입은행 현재환율 API (매매기준율, 약 23개 통화). 키: 환경변수 EXIM_KEY (GitHub Secret 또는 config/local.env)
  · 영업일 11시 무렵 이후에만 값이 있고, 주말·공휴일은 빈 목록 → 최근 영업일까지 최대 7일 거슬러 올라감
- 2순위: open.er-api.com (키 불필요, 160여 개 통화, 하루 1회 갱신) — 수출입은행에 없는 통화를 채움
  · 이용 조건: 화면에 출처 표시 ("Rates By Exchange Rate API")
- 둘 다 실패하면 지금 배포된 fx.json 을 그대로 다시 씀 (앱에는 마지막 값 + 기준일이 보임)
- 자주 바뀌는 자료라 저장소에 커밋하지 않고, 배포할 때마다 새로 만듭니다 (wx.json 과 같은 방식).
"""
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "fx.json")
LIVE = "https://shpdragonfly-bit.github.io/callsign-finder/fx.json"
EXIM = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON?authkey={key}&searchdate={d}&data=AP01"
ER = "https://open.er-api.com/v6/latest/KRW"
UA = "callsign-finder/1.0 (offline flight assist)"
KST = dt.timezone(dt.timedelta(hours=9))

# config/local.env (이 PC 전용, GitHub 미포함) 의 KEY=값 을 환경변수로 읽음. 이미 있는 환경변수가 우선
_env = os.path.join(ROOT, "config", "local.env")
if os.path.exists(_env):
    for line in open(_env, encoding="utf-8-sig"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip()


def fetch(url, timeout=30, tries=3, ctx=None):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode("utf-8", "replace") or "null")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def exim():
    """수출입은행 매매기준율 → ({통화: 원}, 'YYYY-MM-DD')"""
    key = os.environ.get("EXIM_KEY", "").strip()
    if not key:
        print("  수출입은행: EXIM_KEY 없음 → 건너뜀")
        return {}, ""
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")                 # 기관 서버의 구형 암호 설정 대비
    today = dt.datetime.now(KST).date()
    for back in range(8):
        d = today - dt.timedelta(days=back)
        try:
            rows = fetch(EXIM.format(key=urllib.parse.quote(key), d=d.strftime("%Y%m%d")), ctx=ctx, tries=2)
        except Exception as e:
            print("  수출입은행 실패: %s" % type(e).__name__)   # 키가 로그에 남지 않게 URL 은 출력하지 않음
            return {}, ""
        if not isinstance(rows, list) or not rows:
            continue
        if rows[0].get("result") not in (1, "1"):
            print("  수출입은행 응답 오류 (result=%s) — 키 확인 필요" % rows[0].get("result"))
            return {}, ""
        out = {}
        for r in rows:
            unit = str(r.get("cur_unit", "")).strip()
            v = num(r.get("deal_bas_r"))
            if not unit or not v or unit.startswith("KRW"):
                continue
            code, per = unit, 1
            if "(" in unit:                                  # JPY(100), IDR(100)
                code, n = unit.split("(", 1)
                per = int(num(n.rstrip(")")) or 1)
            code = {"CNH": "CNY"}.get(code.strip(), code.strip())
            out[code] = round(v / per, 6)
        print("  수출입은행: %d개 통화 (%s)" % (len(out), d.isoformat()))
        return out, d.isoformat()
    print("  수출입은행: 최근 7일 자료 없음")
    return {}, ""


def er_api():
    """open.er-api.com → ({통화: 원}, 'YYYY-MM-DD')"""
    try:
        j = fetch(ER)
    except Exception as e:
        print("  er-api 실패: %s" % e)
        return {}, ""
    if not j or j.get("result") != "success":
        print("  er-api 응답 오류")
        return {}, ""
    out = {}
    for c, r in (j.get("rates") or {}).items():
        if c != "KRW" and r:
            out[c] = round(1 / float(r), 6)
    when = dt.datetime.fromtimestamp(j.get("time_last_update_unix", 0), dt.timezone.utc).astimezone(KST).date().isoformat()
    print("  er-api: %d개 통화 (%s)" % (len(out), when))
    return out, when


def main():
    print("환율 수집")
    ex, exd = exim()
    er, erd = er_api()
    if not ex and not er:
        try:                                                  # 둘 다 실패: 배포 중인 값을 유지
            old = fetch(LIVE, tries=2)
            if old and old.get("r"):
                json.dump(old, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
                print("  수집 실패 → 기존 fx.json 유지 (%s)" % old.get("generated"))
                return 0
        except Exception as e:
            print("  기존 fx.json 도 못 받음: %s" % e)
        return 1
    rates = dict(er)
    rates.update(ex)                                          # 같은 통화는 수출입은행 값 우선
    data = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exim": exd, "er": erd,                               # 기준일
        "x": sorted(ex),                                      # 수출입은행 값을 쓴 통화
        "r": {k: rates[k] for k in sorted(rates)},
    }
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("  저장: %s (%d개 통화)" % (os.path.relpath(OUT, ROOT), len(rates)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
