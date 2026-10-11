"""공항02/03 셔틀 시간표(xlsx, 정류장별 9개) → web/index.html 의 SHUTTLE_DATA 갱신

사용법 (PC):  python tools/shuttle_xlsx.py 시간표폴더\\*.xlsx
- 인천공항 순환버스 시간표 양식(A열 시, B~열 HH:MM, 급행은 'HH:MM(급)')을 읽습니다.
- 02번은 정류장 사이 간격이 일정해서 예약주차장1 시각 + 터미널 도착 시각만 저장하고 나머지는 계산합니다.
- 03번(급)은 장기3·장기5 시각을 저장합니다 (장기4 = 장기3 + 1분).
- 간격이 달라지면 경고를 출력하니 웹 코드의 OFF 값도 같이 고쳐야 합니다.
"""
import json, re, sys, glob, collections
from pathlib import Path
import openpyxl

KEYS = {"제2여객터미널": "T2", "정비단지": "MT", "예약주차장1": "R1", "예약주차장2": "R2",
        "장기탑승장1": "L1", "장기탑승장2": "L2", "장기탑승장3": "L3", "장기탑승장4": "L4", "장기탑승장5": "L5"}
OFF = {"R2": 2, "L1": 7, "L2": 9, "L3": 11, "L4": 12, "L5": 15}   # 예약주차장1 기준 (분)


def read(path):
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    key = next((v for k, v in KEYS.items() if ws.title.startswith(k)), None)
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


def main(paths):
    S, X, eff = {}, {}, set()
    for p in paths:
        k, n, e, f = read(p)
        S[k], X[k] = n, e
        eff.add(f)
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
    js = json.dumps(data, separators=(",", ":"))
    html = Path(__file__).resolve().parent.parent / "web" / "index.html"
    src = html.read_text(encoding="utf-8")
    new, n = re.subn(r"(/\*SHUTTLE_DATA\*/).*?(/\*END\*/)", lambda m: m[1] + js + m[2], src, flags=re.S)
    if n != 1:
        raise SystemExit("index.html 에서 /*SHUTTLE_DATA*/ 표시를 찾지 못했습니다")
    html.write_text(new, encoding="utf-8")
    print(f"갱신: 02 {len(r1)}회, 03(급) {len(X['L3'])}회, 시행 {data['from']}")


if __name__ == "__main__":
    args = [p for a in sys.argv[1:] for p in glob.glob(a)]
    if not args:
        raise SystemExit(__doc__)
    main(args)
