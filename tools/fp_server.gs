/**
 * 운항 도우미 - 비행준비(공항별 이·착륙 유의사항) 서버 (Google Apps Script, 다른 프로젝트와 별도)
 *
 * 하는 일
 *   - 이 PC 의 업로드 스크립트(tools/fp_sync.ps1)가 공항별 '중요' 항목만 올려 놓음 (비밀키 필요)
 *   - 앱은 공항 하나 · 이륙 또는 착륙 하나씩만 요청해서 받음. 전체를 한 번에 주는 기능은 없음
 *   - 기기마다 하루(한국 날짜) 서로 다른 공항 10곳까지 (같은 공항 다시 받기는 횟수에 안 셈)
 *
 * 설정 (한 번만)
 *   1) script.google.com → 새 프로젝트 → 이 파일 내용을 붙여넣기 → 저장 (프로젝트 이름은 자유)
 *   2) ⚙ 프로젝트 설정 → 스크립트 속성 → 속성 추가
 *        이름: UPLOAD_KEY   값: 아무도 모르는 긴 문자열 (PC 의 config\fpdata.local.env 의 FP_KEY 와 같게)
 *   3) 편집기 위쪽 함수 선택에서 setup 을 고르고 ▶실행 → 권한 허용 (자료를 담을 스프레드시트를 내 드라이브에 만듦)
 *   4) 배포 → 새 배포 → 유형: 웹 앱 → 실행: 나 / 액세스: 모든 사용자 → 배포 → 웹 앱 주소를 알려 주세요
 *
 * 요청 (GET)
 *   ?a=list                                   → 자료가 있는 공항 코드 목록 (내용 없음)
 *   ?a=get&icao=RJTT&role=arr&co=아시아나항공&d=기기토큰 → 그 공항의 착륙(arr) 또는 이륙(dep) 중요 항목
 *   ?a=ping                                   → 서버 상태
 * 업로드 (POST, 본문 JSON) {"key":"…","airports":[…],"remove":[{"company":"…","icao":"…"}],"updated":"…"}
 */
var DAILY_LIMIT = 10;                 // 기기당 하루 서로 다른 공항 수
var GLOBAL_LIMIT = 3000;              // 전체 하루 조회 상한 (이상한 대량 조회 막기)
var SHEET = "airports", HEAD = ["company", "icao", "iata", "eff_date", "date_label", "version", "dep", "arr", "chg_dep", "chg_arr", "updated"];

function setup() {
  var p = PropertiesService.getScriptProperties();
  if (!p.getProperty("UPLOAD_KEY")) throw new Error("먼저 스크립트 속성 UPLOAD_KEY 를 넣어 주세요");
  if (!p.getProperty("SHEET_ID")) {
    var ss = SpreadsheetApp.create("FLT Assist 비행준비 자료 (공유 금지)");
    var sh = ss.getSheets()[0].setName(SHEET);
    sh.getRange("A:K").setNumberFormat("@");          // 날짜·버전(2.0)을 글자 그대로 저장
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]);
    p.setProperty("SHEET_ID", ss.getId());
  }
  return "준비 완료";
}

function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
function sheet_() {
  var id = PropertiesService.getScriptProperties().getProperty("SHEET_ID");
  if (!id) throw new Error("setup 을 먼저 실행하세요");
  return SpreadsheetApp.openById(id).getSheetByName(SHEET);
}
function rows_() {
  var sh = sheet_(), n = sh.getLastRow();
  if (n < 2) return [];
  return sh.getRange(2, 1, n - 1, HEAD.length).getValues().map(function (r, i) {
    var o = { _row: i + 2 }; HEAD.forEach(function (h, j) { o[h] = r[j]; }); return o;
  });
}
// 글자로 저장한 값 그대로 (혹시 날짜로 바뀌어 있으면 한국 날짜 11 SEP 26 모양으로)
function plain_(x) {
  if (x instanceof Date) return Utilities.formatDate(x, "Asia/Seoul", "dd MMM yy").toUpperCase();
  return String(x == null ? "" : x).replace(/^'/, "");
}
function kstDay_() { return Utilities.formatDate(new Date(), "Asia/Seoul", "yyyyMMdd"); }

function doGet(e) {
  var p = (e && e.parameter) || {}, a = p.a || "";
  try {
    if (a === "ping") return json_({ ok: true, at: new Date().toISOString() });
    if (a === "list") {
      var c = CacheService.getScriptCache(), hit = c.get("list");
      if (hit) return json_(JSON.parse(hit));
      var list = rows_().map(function (r) { return { icao: r.icao, iata: r.iata, company: r.company }; });
      var out = { ok: true, airports: list, at: new Date().toISOString() };
      c.put("list", JSON.stringify(out), 600);
      return json_(out);
    }
    if (a === "get") return json_(get_(p));
    return json_({ ok: false, err: "bad" });
  } catch (err) {
    return json_({ ok: false, err: "server", msg: String(err).slice(0, 150) });
  }
}

function get_(p) {
  var icao = String(p.icao || "").toUpperCase(), role = p.role, dev = String(p.d || "");
  if (!/^[A-Z]{4}$/.test(icao) || !/^(dep|arr)$/.test(role) || !/^[A-Za-z0-9_-]{16,64}$/.test(dev)) return { ok: false, err: "bad" };
  var rs = rows_().filter(function (r) { return r.icao === icao; });
  if (p.co) { var m = rs.filter(function (r) { return r.company === p.co; }); if (m.length) rs = m; else rs = []; }
  if (!rs.length) return { ok: false, err: "none", icao: icao };
  // 기기별 하루 한도 (서로 다른 공항 수). 같은 공항은 다시 받아도 그대로
  var lock = LockService.getScriptLock(); lock.waitLock(10000);
  try {
    var props = PropertiesService.getScriptProperties(), day = kstDay_(), k = "u" + day + ":" + dev;
    if (props.getProperty("cleaned") !== day) { cleanup_(); props.setProperty("cleaned", day); }
    var seen = JSON.parse(props.getProperty(k) || "[]");
    if (seen.indexOf(icao) < 0) {
      if (seen.length >= DAILY_LIMIT) return { ok: false, err: "limit", limit: DAILY_LIMIT };
      var gk = "g" + day, g = +(props.getProperty(gk) || 0);
      if (g >= GLOBAL_LIMIT) return { ok: false, err: "busy" };
      seen.push(icao); props.setProperty(k, JSON.stringify(seen)); props.setProperty(gk, String(g + 1));
    }
    var left = DAILY_LIMIT - seen.length;
  } finally { lock.releaseLock(); }
  var r = rs[0];
  return {
    ok: true, icao: r.icao, iata: r.iata, company: r.company, role: role,
    date_label: plain_(r.date_label), eff_date: plain_(r.eff_date), version: plain_(r.version),
    items: JSON.parse(r[role] || "[]"), changes: JSON.parse(r["chg_" + role] || "[]"),
    left: left, at: new Date().toISOString()
  };
}

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    var key = PropertiesService.getScriptProperties().getProperty("UPLOAD_KEY");
    if (!key || body.key !== key) return json_({ ok: false, err: "key" });
    var lock = LockService.getScriptLock(); lock.waitLock(20000);
    try {
      var sh = sheet_(), rows = rows_(), now = new Date().toISOString(), put = 0, del = 0;
      var find = function (co, icao) { for (var i = 0; i < rows.length; i++) if (rows[i].company === co && rows[i].icao === icao) return rows[i]; return null; };
      (body.airports || []).forEach(function (a) {
        if (!a || !/^[A-Z]{4}$/.test(a.icao || "")) return;
        // 날짜(11 SEP 26)·버전(2.0)을 스프레드시트가 날짜·숫자로 바꾸지 않게 앞에 ' 를 붙여 글자로 저장
        var txt = function (x) { x = String(x == null ? "" : x); return x ? "'" + x : ""; };
        var v = [a.company || "", a.icao, a.iata || "", txt(a.eff_date), txt(a.date_label), txt(a.version),
          JSON.stringify(a.dep || []), JSON.stringify(a.arr || []), JSON.stringify(a.chg_dep || []), JSON.stringify(a.chg_arr || []), now];
        var r = find(v[0], v[1]);
        if (r) sh.getRange(r._row, 1, 1, HEAD.length).setValues([v]);
        else { sh.appendRow(v); rows = rows_(); }
        put++;
      });
      var gone = (body.remove || []).map(function (x) { return x ? find(x.company, x.icao) : null; }).filter(Boolean)
        .sort(function (x, y) { return y._row - x._row; });
      gone.forEach(function (r) { sh.deleteRow(r._row); del++; });
      CacheService.getScriptCache().remove("list");
      cleanup_();
      return json_({ ok: true, put: put, removed: del, total: rows_().length });
    } finally { lock.releaseLock(); }
  } catch (err) {
    return json_({ ok: false, err: "server", msg: String(err).slice(0, 150) });
  }
}

// 지난 날짜의 조회 기록 지우기 (오늘 것만 남김)
function cleanup_() {
  var props = PropertiesService.getScriptProperties(), all = props.getProperties(), day = kstDay_();
  Object.keys(all).forEach(function (k) { if (/^[ug]\d{8}/.test(k) && k.slice(1, 9) !== day) props.deleteProperty(k); });
}
