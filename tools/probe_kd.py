"""KD운송그룹(경기고속·대원고속) 공항버스 시간표 이미지 받기 → probe/kd/ (이미지 + index.json)"""
import hashlib, html, json, os, re, time, urllib.parse, urllib.request
OUT = "probe/kd"; os.makedirs(OUT, exist_ok=True)
B = "https://www.buspia.co.kr"
UA = "Mozilla/5.0 (callsign-finder timetable check)"
def get(u, raw=False):
    req = urllib.request.Request(u, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        b = r.read()
    return b if raw else b.decode("utf-8", "replace")
page = get(B + "/subpage/bus/air_info.php")
open(os.path.join(OUT, "air_info.html"), "w", encoding="utf-8").write(page)
# 노선 블록: '공항3200' 같은 제목 다음에 AllService('27')
idx = []
for m in re.finditer(r"AllService\('(\d+)'\)", page):
    seg = re.sub(r"<[^>]+>", " ", page[max(0, m.start() - 3000):m.start()])
    seg = html.unescape(re.sub(r"\s+", " ", seg))
    t = re.findall(r"공항\s*([A-Z]?\d{3,4}(?:-\d)?|N\d{4})?", seg)
    idx.append({"seq": m.group(1), "ctx": seg[-160:]})
res = []
for it in idx:
    try:
        pop = get(B + "/subpage/bus/air_allTimePop.php?seq=" + it["seq"])
        srcs = re.findall(r'<img[^>]+src="([^"]+)"', pop)
        for k, s in enumerate(srcs):
            url = urllib.parse.urljoin(B + "/subpage/bus/", urllib.parse.quote(s, safe="/:%"))
            img = get(url, raw=True)
            fn = "%s_%d%s" % (it["seq"], k, os.path.splitext(s)[1] or ".jpg")
            open(os.path.join(OUT, fn), "wb").write(img)
            res.append(dict(it, src=s, file=fn, sha1=hashlib.sha1(img).hexdigest()[:12], bytes=len(img)))
            print(it["seq"], s, len(img))
        time.sleep(1)
    except Exception as e:
        res.append(dict(it, err=repr(e)))
        print(it["seq"], "ERR", e)
json.dump(res, open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
