"""공항02/03 셔틀 시간표(xlsx, 정류장별 9개) → web/index.html 의 SHUTTLE_DATA 갱신
   공항01 셔틀 시간표(여객동측(3C)·여객서측(13C)·탑승장 1~7번) → SHUTTLE1_DATA 갱신

사용법 (PC):  python tools/shuttle_xlsx.py 시간표폴더\\*.xlsx
- 인천공항 순환버스 시간표 양식(A열 시, B~열 HH:MM, 03번은 'HH:MM(급)')을 읽습니다.
- 02번은 정류장 사이 간격이 일정해서 예약주차장1 시각 + 터미널 도착 시각만 저장하고 나머지는 계산합니다.
- 03번(시간표에 '(급)' 표시)은 장기3·장기5 시각을 저장합니다 (장기4 = 장기3 + 1분).
- 간격이 달라지면 경고를 출력하니 웹 코드의 OFF 값도 같이 고쳐야 합니다.
"""
import json, re, sys, glob, collections
from pathlib import Path
import openpyxl

KEYS1 = {"여객동측": "C3", "여객서측": "C13", **{f"탑승장 {i}번": f"S{i}" for i in range(1, 8)}}
OFF1 = {"C13": 3, "S1": 6, "S2": 7, "S3": 8, "S4": 10, "S5": 11, "S6": 12, "S7": 13}   # 3C 출발 기준 (분)
KEYS = {"제2여객터미널": "T2", "정비단지": "MT", "예약주차장1": "R1", "예약주차장2": "R2",
        "장기탑승장1": "L1", "장기탑승장2": "L2", "장기탑승장3": "L3", "장기탑승장4": "L4", "장기탑승장5": "L5"}
OFF = {"R2": 2, "L1": 7, "L2": 9, "L3": 11, "L4": 12, "L5": 15}   # 예약주차장1 기준 (분)


def read(path):
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    key = next((v for k, v in {**KEYS, **KEYS1}.items() if ws.title.startswith(k)), None)
    if not key:
        raise SystemExit(f"정류장 이름을 모르는 시트: {ws.title} ({path})")
    eff = re.search(r"\[\s*(\d{6})", str(ws["A1"].value or ""))
    norm, exp = [], []
    for row in ws.iter_rows(min_row=5):
        for c in row[1:]:
            m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(\(급\))?", str(c.value or ""))
            if m:
                t = int(m[1]) * 60 + int(m[2])
                (exp if m[3] else norm).append(t)
    return key, sorted(norm), sorted(exp), eff[1] if eff else ""


def put(marker, end, data):
    js = json.dumps(data, separators=(",", ":"))
    html = Path(__file__).resolve().parent.parent / "web" / "index.html"
    src = html.read_text(encoding="utf-8")
    new, n = re.subn(r"(/\*" + marker + r"\*/).*?(/\*" + end + r"\*/)", lambda m: m[1] + js + m[2], src, flags=re.S)
    if n != 1:
        raise SystemExit(f"index.html 에서 /*{marker}*/ 표시를 찾지 못했습니다")
    html.write_text(new, encoding="utf-8")


def main(paths):
    S, X, eff, eff1 = {}, {}, set(), set()
    for p in paths:
        k, n, e, f = read(p)
        S[k], X[k] = n, e
        (eff1 if k in KEYS1.values() else eff).add(f)
    if "C3" in S:                                       # 공항01
        c3 = S["C3"]
        for k, o in OFF1.items():
            if k in S:
                c = collections.Counter(t - r for t, r in zip(S[k], c3))
                if len(S[k]) != len(c3) or len(c) > 1 or o not in c:
                    print(f"경고: 01번 {k} 간격 {dict(c)} (예상 {o}분) - 웹 코드 T1_OFF 도 확인", file=sys.stderr)
        put("SHUTTLE1_DATA", "END1", {"from": sorted(eff1)[-1], "c3": c3})
        print(f"갱신: 01 {len(c3)}회, 시행 {sorted(eff1)[-1]}")
    if "R1" not in S:
        return
    miss = [k for k in KEYS.values() if k not in S]
    if miss:
        raise SystemExit(f"빠진 정류장: {miss}")
    r1 = S["R1"]
    for k, o in OFF.items():
        c = collections.Counter(t - r for t, r in zip(S[k], r1))
        if len(S[k]) != len(r1) or len(c) > 1:
            print(f"경고: {k} 간격 {dict(c)} / {len(S[k])}회 (예약1 {len(r1)}회) - 시간표 오타인지 확인", file=sys.stderr)
    c = collections.Counter(t - S["L5"][i] for i, t in enumerate(S["T2"]) if i < len(S["L5"]))
    print(f"T2 도착 - 장기5: {dict(c)}", file=sys.stderr)
    data = {"from": sorted(eff)[-1], "r1": r1, "t2": S["T2"], "mt": S["MT"], "x3": X["L3"], "x5": X["L5"]}
    put("SHUTTLE_DATA", "END", data)
    print(f"갱신: 02 {len(r1)}회, 03(급) {len(X['L3'])}회, 시행 {data['from']}")


if __name__ == "__main__":
    args = [p for a in sys.argv[1:] for p in glob.glob(a)]
    if not args:
        raise SystemExit(__doc__)
    main(args)
