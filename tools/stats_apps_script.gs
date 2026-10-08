/**
 * 운항 도우미 — 익명 사용 통계 수신 (Google Apps Script)
 *
 * 사용법: Google 시트 → 확장 프로그램 → Apps Script 에 이 코드를 그대로 붙여넣고 저장 →
 *        배포 → 새 배포 → 웹 앱 (실행: 나 / 액세스: 모든 사용자) → 웹 앱 URL 복사
 *
 * 앱이 보내는 것: 익명 기기번호, 동작(실행·검색 등), 항공사 탭, 세부(편조 종류 등), 기기 종류, 앱 버전, 사용 시각
 * 받지 않는 것: 검색한 편명, 이름, 위치
 */
const SHEET = "기록";
const HEAD = ["수신시각", "사용시각", "기기번호", "동작", "항공사", "세부", "기기", "앱버전"];
const ACTIONS = ["실행", "검색", "공항검색", "비행시간"];

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out("bad json"); }
  if (!body || body.v !== 1 || !/^[a-z0-9]{6,16}$/.test(body.d || "") || !Array.isArray(body.e)) return out("bad");
  const now = new Date();
  const rows = body.e.slice(0, 300)
    .filter((x) => x && ACTIONS.indexOf(x.a) >= 0)
    .map((x) => [now, safeDate(x.t, now), body.d, x.a, cut(x.al, 8), cut(x.m, 20), cut(body.dev, 12), cut(body.ver, 12)]);
  if (!rows.length) return out("empty");
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = sheet();
    sh.getRange(sh.getLastRow() + 1, 1, rows.length, HEAD.length).setValues(rows);
  } finally { lock.releaseLock(); }
  return out("ok " + rows.length);
}

function doGet() { return out("운항 도우미 통계 수신 중"); }

function sheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET);
  if (!sh) {
    sh = ss.insertSheet(SHEET, 0);
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]).setFontWeight("bold");
    sh.setFrozenRows(1);
  }
  return sh;
}

/** 처음 한 번 실행: 기록 시트와 요약 시트를 만듭니다 (편집기 위쪽에서 setup 선택 후 ▶ 실행) */
function setup() {
  sheet();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let s = ss.getSheetByName("요약");
  if (!s) s = ss.insertSheet("요약", 1);
  s.clear();
  const f = [
    ["운항 도우미 사용 통계", ""],
    ["전체 기기 수 (사용자 수 추정)", "=COUNTUNIQUE(기록!C2:C)"],
    ["최근 30일 사용 기기 수", "=COUNTUNIQUE(FILTER(기록!C2:C, 기록!B2:B>=TODAY()-30))"],
    ["최근 7일 사용 기기 수", "=COUNTUNIQUE(FILTER(기록!C2:C, 기록!B2:B>=TODAY()-7))"],
    ["전체 실행 횟수", "=COUNTIF(기록!D2:D,\"실행\")"],
    ["", ""],
    ["항공사별 실행 (주로 쓰는 탭)", ""],
  ];
  s.getRange(1, 1, f.length, 2).setValues(f);
  s.getRange("A8").setFormula("=QUERY(기록!A2:H, \"select E, count(D) where D='실행' group by E order by count(D) desc label E '항공사', count(D) '실행'\", 0)");
  s.getRange("D1").setValue("동작별 횟수");
  s.getRange("D2").setFormula("=QUERY(기록!A2:H, \"select D, count(D) where D<>'' group by D order by count(D) desc label D '동작', count(D) '횟수'\", 0)");
  s.getRange("G1").setValue("월별 실행");
  s.getRange("G2").setFormula("=QUERY({ARRAYFORMULA(TEXT(기록!B2:B,\"yyyy-mm\")), 기록!D2:D}, \"select Col1, count(Col2) where Col2='실행' group by Col1 order by Col1 desc label Col1 '월', count(Col2) '실행'\", 0)");
  s.getRange("J1").setValue("기기 종류 (실행 기준)");
  s.getRange("J2").setFormula("=QUERY(기록!A2:H, \"select G, count(D) where D='실행' group by G label G '기기', count(D) '실행'\", 0)");
  s.getRange("M1").setValue("세부 (편조 종류 등)");
  s.getRange("M2").setFormula("=QUERY(기록!A2:H, \"select F, count(D) where F<>'' group by F order by count(D) desc label F '세부', count(D) '횟수'\", 0)");
  s.getRange("A1").setFontWeight("bold").setFontSize(13);
}

function safeDate(t, fallback) { const d = new Date(t); return isNaN(d) || d > fallback ? fallback : d; }
function cut(v, n) { return String(v == null ? "" : v).slice(0, n); }
function out(s) { return ContentService.createTextOutput(s); }
