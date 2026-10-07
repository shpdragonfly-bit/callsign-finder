#!/usr/bin/env python3
"""
공공데이터포털 API 명세 수집 (연동 준비용, 1회성)
- 검색 결과에서 인천국제공항공사/한국공항공사 운항 관련 오픈API 목록(ID, 제목)을 모으고
- 각 API의 명세(openapi.json)를 probe/specs/ 에 저장
인증키를 사용하지 않습니다.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe", "specs")
UA = "Mozilla/5.0 (callsign-finder probe)"
KEYWORDS = ["인천국제공항공사 운항", "인천국제공항공사 화물편", "한국공항공사 운항", "한국공항공사 스케줄"]
KNOWN = ["15140153", "15158949", "15158625", "15158950", "15159598", "15160195", "15158628", "15158851",
         "15095066", "15095061", "15156559"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main():
    os.makedirs(OUT, exist_ok=True)
    found = {}
    for kw in KEYWORDS:
        for page in (1, 2):
            url = ("https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=API&currentPage=%d&perPage=40&keyword=%s"
                   % (page, urllib.parse.quote(kw)))
            try:
                html = get(url)
            except Exception as e:
                print("search fail", kw, page, e)
                continue
            for m in re.finditer(r'/data/(\d{8})/openapi\.do[^>]*>\s*(?:<[^>]+>\s*)*([^<]{3,120})', html):
                found.setdefault(m.group(1), m.group(2).strip())
            time.sleep(1)
    for k in KNOWN:
        found.setdefault(k, "")
    index = {}
    for did, title in sorted(found.items()):
        spec_url = "https://www.data.go.kr/catalog/%s/openapi.json" % did
        try:
            body = get(spec_url)
            spec = json.loads(body)
            info = spec.get("info", {})
            servers = [s.get("url") for s in spec.get("servers", [])] or [spec.get("host", "") + spec.get("basePath", "")]
            index[did] = {"title": title or info.get("title", ""), "spec_title": info.get("title", ""),
                          "servers": servers, "paths": list((spec.get("paths") or {}).keys())}
            org = info.get("title", "") + title
            if "공항" in org or "항공" in org or "운항" in org:
                with open(os.path.join(OUT, did + ".json"), "w", encoding="utf-8") as f:
                    json.dump(spec, f, ensure_ascii=False, indent=1)
            print("ok", did, index[did]["spec_title"], servers)
        except Exception as e:
            index[did] = {"title": title, "error": str(e)[:200]}
            print("spec fail", did, e)
        time.sleep(0.5)
    with open(os.path.join(OUT, "_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
