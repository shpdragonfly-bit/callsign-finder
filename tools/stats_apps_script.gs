/**
 * 운항 도우미 — 익명 사용 통계 수신 (Google Apps Script)
 *
 * 사용법: Google 시트 → 확장 프로그램 → Apps Script 에 이 코드를 그대로 붙여넣고 저장 →
 *        배포 → 새 배포 → 웹 앱 (실행: 나 / 액세스: 모든 사용자) → 웹 앱 URL 복사
 *
 * 앱이 보내는 것: 익명 기기번호, 동작(실행·검색 등), 항공사 탭, 세부(편조 종류 등), 기기 종류, 앱 버전, 사용 시각,
 *               개발 예정 기능 요청과 사용자가 직접 적은 의견
 *
 * 코드를 고친 뒤에는: 배포 → 배포 관리 → ✏️ 수정 → 버전 "새 버전" → 배포 (웹 앱 URL 은 그대로)
 * 받지 않는 것: 검색한 편명, 이름, 위치
 *
 * 주간 메일 (사용자 요청·의견 모아 받기): 편집기 위쪽에서 setupWeekly 선택 → ▶ 실행 (권한 허용) 한 번이면
 *   매주 월요일 오전 9시쯤 지난 7일 의견을 이 스크립트 주인 메일로 보냅니다. 의견이 없으면 보내지 않습니다.
 *   바로 시험: weeklyDigest 선택 → ▶ 실행.  끄기: stopWeekly 실행.
 */
const SHEET = "기록";
const HEAD = ["수신시각", "사용시각", "기기번호", "동작", "항공사", "세부", "기기", "앱버전", "의견"];
const ACTIONS = ["실행", "검색", "공항검색", "비행시간", "요청", "의견", "오류"];   // 오류: 앱 익명 오류 보고(파일:줄 · 메시지)

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out("bad json"); }
  if (!body || body.v !== 1 || !/^[a-z0-9]{6,16}$/.test(body.d || "") || !Array.isArray(body.e)) return out("bad");
  const now = new Date();
  const rows = body.e.slice(0, 300)
    .filter((x) => x && ACTIONS.indexOf(x.a) >= 0)
    .map((x) => [now, safeDate(x.t, now), body.d, x.a, cut(x.al, 8), cut(x.m, 20), cut(body.dev, 12), cut(body.ver, 12), clean(x.c)]);
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
    sh.setFrozenRows(1);
  }
  if (sh.getRange(1, HEAD.length).getValue() !== HEAD[HEAD.length - 1])   // 예전 시트에 새 열 제목 추가
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]).setFontWeight("bold");
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
  s.getRange("P1").setValue("기능 요청 (기기 수)");
  s.getRange("P2").setFormula("=QUERY(기록!A2:I, \"select F, count(C) where D='요청' group by F order by count(C) desc label F '기능', count(C) '요청'\", 0)");
  s.getRange("S1").setValue("의견 (최근 순)");
  s.getRange("S2").setFormula("=IFERROR(SORT(FILTER({기록!B2:B, 기록!F2:F, 기록!I2:I}, 기록!D2:D=\"의견\"), 1, FALSE), \"아직 없음\")");
  s.setColumnWidth(21, 360);
  s.getRange("A1").setFontWeight("bold").setFontSize(13);
}

/** 주간 메일 켜기 (한 번만 실행) */
function setupWeekly() {
  stopWeekly();
  ScriptApp.newTrigger("weeklyDigest").timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(9).inTimezone("Asia/Seoul").create();
  Logger.log("매주 월요일 09시 주간 메일을 켰습니다");
}
/** 주간 메일 끄기 */
function stopWeekly() {
  ScriptApp.getProjectTriggers().filter((t) => t.getHandlerFunction() === "weeklyDigest").forEach((t) => ScriptApp.deleteTrigger(t));
}
/** 지난 7일 의견·기능 요청을 모아 메일로 보냄 */
function weeklyDigest() {
  const sh = sheet(), last = sh.getLastRow();
  if (last < 2) return;
  const since = new Date(Date.now() - 7 * 24 * 3600e3);
  const rows = sh.getRange(2, 1, last - 1, HEAD.length).getValues().filter((r) => r[0] >= since && (r[3] === "의견" || r[3] === "요청"));
  const ops = rows.filter((r) => r[3] === "의견" && String(r[8]).trim());
  const reqs = {};
  rows.filter((r) => r[3] === "요청").forEach((r) => { reqs[r[5]] = reqs[r[5]] || {}; reqs[r[5]][r[2]] = 1; });
  if (!ops.length && !Object.keys(reqs).length) { Logger.log("지난 7일 의견·요청 없음 - 메일 안 보냄"); return; }
  const tz = "Asia/Seoul", fmt = (d) => Utilities.formatDate(new Date(d), tz, "MM/dd HH:mm");
  const kind = (m) => String(m).replace(/^메뉴-/, "") || "의견";   // 기능요청·오류신고·기타의견, 개발 예정 탭 의견은 기능 키(PKG-AI 등)
  let txt = `운항 도우미 · 지난 7일 사용자 의견 ${ops.length}건\n(${fmt(since)} ~ ${fmt(new Date())})\n\n`;
  const groups = {};
  ops.forEach((r) => { const k = kind(r[5]); (groups[k] = groups[k] || []).push(r); });
  Object.keys(groups).forEach((k) => {
    txt += `■ ${k} (${groups[k].length})\n`;
    groups[k].forEach((r) => { txt += `  - ${fmt(r[1])} · ${r[6]} ${r[7]}\n    ${String(r[8]).replace(/^'/, "")}\n`; });
    txt += "\n";
  });
  const rk = Object.keys(reqs);
  if (rk.length) { txt += "■ 개발 예정 기능 요청 (기기 수)\n"; rk.forEach((k) => { txt += `  - ${k}: ${Object.keys(reqs[k]).length}\n`; }); txt += "\n"; }
  txt += "전체 기록: " + SpreadsheetApp.getActiveSpreadsheet().getUrl();
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), `[운항 도우미] 주간 사용자 의견 ${ops.length}건`, txt);
}

function safeDate(t, fallback) { const d = new Date(t); return isNaN(d) || d > fallback ? fallback : d; }
// 의견: 수식으로 해석되지 않도록 = + - @ 로 시작하면 앞에 ' 를 붙임
function clean(v) { const t = cut(v, 300); return /^[=+\-@]/.test(t) ? "'" + t : t; }
function cut(v, n) { return String(v == null ? "" : v).slice(0, n); }
function out(s) { return ContentService.createTextOutput(s); }
