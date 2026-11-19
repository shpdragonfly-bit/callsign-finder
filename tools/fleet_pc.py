"""
기번별 운항 기록을 PC 개발 서버에서 15분마다 수집 → GitHub fleet 브랜치에 올림 (GitHub 예약 실행이 몇 시간씩 밀려서)

  py -3 tools\\fleet_pc.py          한 번 수집 + 올리기 (작업 스케줄러가 15분마다 실행)
  py -3 tools\\fleet_pc.py --check  설정만 확인

필요한 것
  - config\\local.env 에  GH_FLEET_TOKEN=…  (GitHub 세분화 토큰: 이 저장소만 · Contents 읽기/쓰기). 화면·기록에 출력하지 않음
작업 폴더 (저장소에 올리지 않음)
  private\\fleet\\       fleet 브랜치와 같은 내용 (state.json · reg\\ · index.json · recent.json · byflt.json · log.txt)
  private\\fleet_src\\   main 의 최신 공공데이터 · 앱 데이터 (3시간마다 새로 받음)
올리기: GitHub API 로 바뀐 파일만 담은 커밋 1개를 만들어 fleet 브랜치를 덮어씀 (브랜치 기록은 늘 1개 → 저장소가 불어나지 않음)
"""
import datetime as dt, hashlib, io, json, os, subprocess, sys, time, urllib.request, urllib.error, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "shpdragonfly-bit/callsign-finder"
OUT = os.path.join(ROOT, "private", "fleet")
SRC = os.path.join(ROOT, "private", "fleet_src")
PUSHED = os.path.join(ROOT, "private", "fleet_pushed.json")
LOGF = os.path.join(ROOT, "private", "fleet_pc.log")
RAW = "https://raw.githubusercontent.com/%s/main/" % REPO
UA = "callsign-finder-pc/1.0"


def log(m):
    line = "%s %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), m)
    print(line)
    try:
        old = open(LOGF, encoding="utf-8").read().splitlines()[-999:] if os.path.exists(LOGF) else []
        open(LOGF, "w", encoding="utf-8").write("\n".join(old + [line]) + "\n")
    except Exception:
        pass


def token():
    p = os.path.join(ROOT, "config", "local.env")
    try:
        for ln in open(p, encoding="utf-8-sig"):
            k, _, v = ln.strip().partition("=")
            if k.strip() == "GH_FLEET_TOKEN" and v.strip():
                return v.strip().strip('"')
    except Exception:
        pass
    return ""


def http(url, data=None, method=None, tok="", timeout=60, raw=False):
    h = {"User-Agent": UA}
    if tok:
        h.update({"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    body = json.dumps(data).encode() if data is not None else None
    if body:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        return b if raw else json.loads(b.decode("utf-8") or "{}")


def bootstrap():
    """처음 한 번: 지금 fleet 브랜치 내용을 받아 이어서 수집"""
    if os.path.exists(os.path.join(OUT, "state.json")):
        return
    os.makedirs(OUT, exist_ok=True)
    try:
        z = zipfile.ZipFile(io.BytesIO(http("https://codeload.github.com/%s/zip/refs/heads/fleet" % REPO, raw=True, timeout=120)))
        n = 0
        for nm in z.namelist():
            rel = nm.split("/", 1)[1] if "/" in nm else ""
            if not rel or nm.endswith("/"):
                continue
            dst = os.path.join(OUT, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(z.read(nm)); n += 1
        log("처음 설정: fleet 브랜치 파일 %d개 받음" % n)
        snap = {}                                      # 받은 그대로는 다시 올리지 않음
        for dp, _, fs in os.walk(OUT):
            for f in fs:
                full = os.path.join(dp, f)
                snap[os.path.relpath(full, OUT).replace(os.sep, "/")] = blob_sha(open(full, "rb").read())
        json.dump(snap, open(PUSHED, "w", encoding="utf-8"))
    except Exception as e:
        log("fleet 브랜치를 받지 못해 새로 시작 (%s)" % type(e).__name__)


def refresh_src():
    """main 의 최신 인천공항 자료 · 앱 데이터 · 기종 관측 (3시간마다)"""
    os.makedirs(SRC, exist_ok=True)
    for rel in ("data/public_cache.json", "web/data.json", "data/observations.json"):
        p = os.path.join(SRC, rel.split("/")[-1])
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < 3 * 3600:
            continue
        try:
            b = http(RAW + rel, raw=True, timeout=120)
            json.loads(b.decode("utf-8"))
            open(p, "wb").write(b)
        except Exception as e:
            log("  %s 받기 실패 (%s) — 이전 것 사용" % (rel, type(e).__name__))


def _merge_reg(docs):
    """같은 기번 파일 여러 판 합치기: 구간은 (콜사인, 이륙) 같으면 하나(착륙을 더 늦게까지 본 쪽), 인천 기록은 (콜사인, 예정시각) 같으면 실제 시각 있는 쪽"""
    out = {"reg": docs[0].get("reg")}
    legs, icn = {}, {}
    for d in docs:
        for x in d.get("legs", []):
            k = (x.get("c"), x.get("o"))
            if k not in legs or x.get("n", "") > legs[k].get("n", ""):
                legs[k] = x
        for x in d.get("icn", []):
            k = (x.get("c"), x.get("t"))
            o = icn.get(k)
            if not o or (x.get("e") and not o.get("e")) or (x.get("st") and not o.get("st")):
                icn[k] = x
        for f in ("ty", "al"):
            if d.get(f):
                out[f] = d[f]
    out["legs"] = sorted(legs.values(), key=lambda x: x.get("o", ""))
    out["icn"] = sorted(icn.values(), key=lambda x: x.get("t", ""))
    return out


def cleanup_conflicts():
    """클라우드 동기화(Nextcloud 등) 충돌 사본 정리: 기번 파일은 원래 파일에 합치고, 사본은 모두 private\\_to_delete\\ 로 옮김"""
    import re, shutil
    priv = os.path.join(ROOT, "private")
    trash = os.path.join(priv, "_to_delete")
    pat = re.compile(r"^(.*?) \((?:conflicted copy|충돌)[^)]*\)(\.[A-Za-z0-9]+)$")
    found = []
    for dp, dns, fs in os.walk(priv):
        if os.path.abspath(dp).startswith(os.path.abspath(trash)):
            continue
        for f in fs:
            m = pat.match(f)
            if m:
                found.append((dp, f, m.group(1) + m.group(2)))
    if not found:
        return
    merged = moved = added = 0
    for dp, f, orig in found:
        full, ofull = os.path.join(dp, f), os.path.join(dp, orig)
        if os.path.normpath(dp) == os.path.normpath(os.path.join(OUT, "reg")) and orig.endswith(".json"):
            try:
                c = json.load(open(full, encoding="utf-8"))
                o = json.load(open(ofull, encoding="utf-8")) if os.path.exists(ofull) else {"reg": c.get("reg"), "legs": [], "icn": []}
                n0 = len(o.get("legs", [])) + len(o.get("icn", []))
                m = _merge_reg([o, c])
                added += len(m["legs"]) + len(m["icn"]) - n0
                json.dump(m, open(ofull, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
                merged += 1
            except Exception as e:
                log("  합치기 실패 %s (%s) — 사본은 그대로 둠" % (f, type(e).__name__))
                continue
        dst = os.path.join(trash, os.path.relpath(full, priv))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.move(full, dst); moved += 1
        except Exception as e:
            log("  옮기기 실패 %s (%s)" % (f, type(e).__name__))
    log("충돌 사본 정리: 기번 파일 %d개 합침(기록 %d건 되살림), 사본 %d개 → private\\_to_delete" % (merged, added, moved))


def blob_sha(b):
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def push(tok):
    """바뀐 파일만 담아 fleet 브랜치를 커밋 1개로 덮어씀"""
    old = json.load(open(PUSHED, encoding="utf-8")) if os.path.exists(PUSHED) else {}
    cur, changed = {}, []
    for dp, _, fs in os.walk(OUT):
        for f in fs:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, OUT).replace(os.sep, "/")
            if rel.startswith(".git") or "(conflicted copy" in rel or "(충돌" in rel:   # 클라우드 동기화 충돌 사본은 올리지 않음
                continue
            b = open(full, "rb").read()
            cur[rel] = blob_sha(b)
            if old.get(rel) != cur[rel]:
                changed.append((rel, b))
    if not changed:
        return 0
    api = "https://api.github.com/repos/%s/git/" % REPO
    try:
        ref = http(api + "ref/heads/fleet", tok=tok)
        base = http(api + "commits/" + ref["object"]["sha"], tok=tok)["tree"]["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        base = None
    ents = [{"path": rel, "mode": "100644", "type": "blob", "content": b.decode("utf-8")} for rel, b in changed]
    if base:                                           # 브랜치에 올라간 충돌 사본 등 PC 에 없는 파일은 지움
        try:
            have = {t["path"] for t in http(api + "trees/" + base + "?recursive=1", tok=tok, timeout=120).get("tree", []) if t.get("type") == "blob"}
            ents += [{"path": pth, "mode": "100644", "type": "blob", "sha": None} for pth in sorted(have - set(cur)) if "(conflicted copy" in pth or "(충돌" in pth]
        except Exception:
            pass
    if not ents:
        return 0
    tree = http(api + "trees", {"base_tree": base, "tree": ents} if base else {"tree": ents}, tok=tok, timeout=180)["sha"]
    com = http(api + "commits", {"message": "fleet %s (PC)" % dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "tree": tree, "parents": []}, tok=tok)["sha"]
    try:
        http(api + "refs/heads/fleet", {"sha": com, "force": True}, method="PATCH", tok=tok)
    except urllib.error.HTTPError as e:
        if e.code != 422:
            raise
        http(api + "refs", {"ref": "refs/heads/fleet", "sha": com}, tok=tok)
    json.dump(cur, open(PUSHED, "w", encoding="utf-8"))
    return len(changed)


def main():
    tok = token()
    if not tok:
        log("GH_FLEET_TOKEN 이 config\\local.env 에 없습니다. 설정 안내를 확인하세요.")
        return 2
    if "--check" in sys.argv:
        try:
            r = http("https://api.github.com/repos/%s" % REPO, tok=tok)
            ok = (r.get("permissions") or {}).get("push")
            log("토큰 확인: 저장소 %s · 올리기 권한 %s" % (r.get("full_name"), "있음" if ok else "없음(Contents 읽기/쓰기 필요)"))
            return 0 if ok else 3
        except urllib.error.HTTPError as e:
            log("토큰 확인 실패: HTTP %s (토큰 값 · 저장소 선택 · 만료 확인)" % e.code)
            return 3
    cleanup_conflicts()
    bootstrap()
    refresh_src()
    env = dict(os.environ, FLEET_ICN=os.path.join(SRC, "public_cache.json"), FLEET_DATA=os.path.join(SRC, "data.json"), FLEET_OBS=os.path.join(SRC, "observations.json"), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "updater", "fleet.py"), OUT], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    last = [l for l in (r.stdout or "").splitlines() if l.strip()][-1:] or [(r.stderr or "").strip()[-200:]]
    try:
        n = push(tok)
        log("수집 %s · 올린 파일 %d개" % (last[0], n))
    except urllib.error.HTTPError as e:
        log("수집 %s · 올리기 실패 HTTP %s" % (last[0], e.code))
        return 1
    except Exception as e:
        log("수집 %s · 올리기 실패 %s" % (last[0], type(e).__name__))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
