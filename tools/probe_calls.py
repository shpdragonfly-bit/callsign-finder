#!/usr/bin/env python3
"""
probe/calls.json 에 적힌 API를 인증키로 호출해 응답 앞부분을 probe/calls/ 에 저장 (연동 준비용)
인증키는 환경변수 DATA_GO_KR_KEY 에서만 읽고, 파일·로그에 남기지 않습니다.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "probe", "calls")


def main():
    key = urllib.parse.unquote(os.environ.get("DATA_GO_KR_KEY", "").strip())
    os.makedirs(OUT, exist_ok=True)
    calls = json.load(open(os.path.join(ROOT, "probe", "calls.json"), encoding="utf-8"))
    summary = {}
    for c in calls:
        params = dict(c.get("params", {}))
        params[c.get("key_param", "serviceKey")] = key
        url = c["url"] + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "callsign-finder probe"})
            with urllib.request.urlopen(req, timeout=40) as r:
                status, body = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            status, body = -1, repr(e)
        if key:
            body = body.replace(key, "***").replace(urllib.parse.quote(key, safe=""), "***")
        with open(os.path.join(OUT, c["name"] + ".txt"), "w", encoding="utf-8") as f:
            f.write(body[:60000])
        summary[c["name"]] = {"status": status, "length": len(body), "head": body[:300]}
        print(c["name"], status, len(body))
    with open(os.path.join(OUT, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
