/**
 * 운항 도우미 - 공항버스 실시간 도착 중계 (Google Apps Script, 통계용과 별도 프로젝트)
 *
 * 왜 필요한가: 공공데이터 인증키를 앱에 넣으면 누구나 볼 수 있으므로,
 *   키는 이 스크립트의 '스크립트 속성'에만 두고 앱은 이 웹 앱 주소로만 묻습니다.
 *
 * 설정 (한 번만)
 *   1) script.google.com → 새 프로젝트 → 이 파일 내용을 붙여넣기 → 저장
 *   2) 왼쪽 ⚙ 프로젝트 설정 → 스크립트 속성 → 속성 추가
 *        이름: DATA_GO_KR_KEY   값: 공공데이터포털 일반 인증키(Decoding)
 *   3) 배포 → 새 배포 → 유형: 웹 앱 → 실행: 나 / 액세스: 모든 사용자 → 배포
 *   4) 나온 웹 앱 주소(https://script.google.com/macros/s/…/exec)를 알려 주세요.
 *
 * 요청:  ?s=s&r=노선ID&st=정류장ID&o=순번   (s=s 서울, s=g 경기, s=t 인천 · 국토교통부 TAGO)
 *        ?s=f&fl=KE017                        (인천공항 운항현황: 그 편의 출발·도착 예정/변경 시각·터미널·게이트·상태, 60초 캐시)
 *        ?s=u                                 (사용량: 날짜별 실제 API 호출 수 · 캐시 재사용 수 · 오류 수, 최근 30일. &fmt=json 이면 JSON)
 * 응답:  {"ok":true,"at":"…","b":[{"m":분,"left":남은정류장,"plate":"차량번호","last":막차여부,"seat":빈자리},…]}
 *
 * 같은 노선(서울)·정류장(경기·인천)은 30초 동안 저장해 두고 재사용 → 공공데이터 하루 호출 한도 절약
 * 인천은 인천시 API 가 해외(구글) 서버에 응답하지 않아 TAGO 사용. 키에 'TAGO 버스도착정보' 활용신청 필요
 */
var CACHE_SEC = 30;

function doGet(e) {
  var p = (e && e.parameter) || {};
  var out;
  if (p.s === "u") return usage_(p.fmt === "json");
  var svc = /^[sgtf]$/.test(p.s || "") ? p.s : "";
  try {
    if (p.s === "f") {                                   // 인천공항 편명 실시간 (출발·도착)
      if (!/^[A-Z0-9]{2}\d{1,4}[A-Z]?$/.test(p.fl || "")) out = { ok: false, err: "bad request" };
      else { try { out = flight_(p.fl); } catch (fe) { out = { ok: false, err: String(fe).slice(0, 200) }; count_("f", "e"); } }
      out.at = new Date().toISOString();
      return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
    }
    var idRe = p.s === "t" ? /^ICB\d{6,12}$/ : /^\d{6,12}$/;
    if (!/^[sgt]$/.test(p.s || "") || !idRe.test(p.r || "") || !idRe.test(p.st || "") || !/^\d{1,3}$/.test(p.o || "")) {
      out = { ok: false, err: "bad request" };
    } else {
      out = p.s === "s" ? seoul_(p.r, p.st, +p.o) : p.s === "g" ? gbis_(p.r, p.st, +p.o) : tago_(p.r, p.st);
    }
  } catch (err) {
    out = { ok: false, err: String(err).slice(0, 200) };
    if (svc) count_(svc, "e");
  }
  out.at = new Date().toISOString();
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

function key_() {
  var k = PropertiesService.getScriptProperties().getProperty("DATA_GO_KR_KEY");
  if (!k) throw new Error("스크립트 속성 DATA_GO_KR_KEY 가 없습니다");
  return encodeURIComponent(k);
}

function fetchJson_(cacheKey, url) {
  var cache = CacheService.getScriptCache(), hit = cache.get(cacheKey);
  if (hit) { count_(cacheKey.charAt(0), "c"); return JSON.parse(hit); }
  count_(cacheKey.charAt(0), "a");
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  if (res.getResponseCode() !== 200) throw new Error("HTTP " + res.getResponseCode());
  var txt = res.getContentText();
  var d = JSON.parse(txt);
  try { if (txt.length < 90000) cache.put(cacheKey, txt, CACHE_SEC); } catch (x) {}
  return d;
}

// 서울: 노선 전체 도착정보 한 번에 (노선별 캐시) → 해당 순번만 꺼냄
function seoul_(route, st, ord) {
  var d = fetchJson_("s" + route, "http://ws.bus.go.kr/api/rest/arrive/getArrInfoByRouteAll?serviceKey=" + key_() + "&busRouteId=" + route + "&resultType=json");
  var items = (d.msgBody && d.msgBody.itemList) || [];
  var it = null;
  for (var i = 0; i < items.length; i++) if (+items[i].staOrd === ord) { it = items[i]; break; }
  if (!it) for (var j = 0; j < items.length; j++) if (String(items[j].stId) === String(st)) { it = items[j]; break; }
  if (!it) return { ok: true, b: [], msg: "정류장 정보 없음" };
  var b = [];
  [1, 2].forEach(function (n) {
    var sec = +it["traTime" + n], msg = it["arrmsg" + n] || "";
    if (/운행종료|출발대기/.test(msg) || !(+it["vehId" + n])) { if (n === 1 && msg) b.msg = msg; return; }
    var left = (msg.match(/\[(\d+)번째 전\]/) || [])[1];
    b.push({ m: Math.max(0, Math.round(sec / 60)), left: left ? +left : (/곧 도착/.test(msg) ? 0 : null), plate: (it["plainNo" + n] || "").trim(), last: it["isLast" + n] === "1" });
  });
  return { ok: true, b: b, msg: b.msg || "" };
}

// 경기: 정류장·노선 도착 1건 (정류장별 캐시)
function gbis_(route, st, ord) {
  var d = fetchJson_("g" + route + "_" + st + "_" + ord, "https://apis.data.go.kr/6410000/busarrivalservice/v2/getBusArrivalItemv2?serviceKey=" + key_() + "&stationId=" + st + "&routeId=" + route + "&staOrder=" + ord + "&format=json");
  var body = (d.response && d.response.msgBody) || {}, it = body.busArrivalItem;
  if (Array.isArray(it)) it = it[0];
  if (!it) return { ok: true, b: [], msg: "도착 정보 없음" };
  var b = [];
  [1, 2].forEach(function (n) {
    var m = it["predictTime" + n];
    if (m === "" || m == null) return;
    b.push({ m: +m, left: it["locationNo" + n] === "" ? null : +it["locationNo" + n], plate: String(it["plateNo" + n] || "").trim(), seat: it["remainSeatCnt" + n] === "" || +it["remainSeatCnt" + n] < 0 ? null : +it["remainSeatCnt" + n] });
  });
  return { ok: true, b: b, msg: b.length ? "" : (it.flag === "PASS" ? "도착 예정 버스 없음" : "") };
}

// 인천(TAGO): 정류장의 모든 노선 도착 (정류장별 캐시 → 같은 정류장 여러 노선이 한 번 호출로) → 해당 노선만
function tago_(route, st) {
  var d = fetchJson_("t" + st, "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList?serviceKey=" + key_() + "&_type=json&cityCode=23&numOfRows=60&pageNo=1&nodeId=" + st);
  var h = (d.response && d.response.header) || {};
  if (String(h.resultCode) !== "00") throw new Error("TAGO " + h.resultCode + " " + (h.resultMsg || ""));
  var it = (((d.response || {}).body || {}).items || {}).item || [];
  if (!Array.isArray(it)) it = [it];
  var b = it.filter(function (x) { return String(x.routeid) === route; })
    .sort(function (x, y) { return +x.arrtime - +y.arrtime; }).slice(0, 2)
    .map(function (x) { return { m: Math.max(0, Math.round(+x.arrtime / 60)), left: x.arrprevstationcnt === "" || x.arrprevstationcnt == null ? null : +x.arrprevstationcnt }; });
  return { ok: true, b: b, msg: b.length ? "" : "도착 예정 버스 없음" };
}

// 인천공항 운항현황 (편명으로 조회): 시각은 KST → UTC 'yyyyMMddHHmm' 로 바꿔 앱과 같은 형식
function flight_(fl) {
  var c = CacheService.getScriptCache(), hit = c.get("f" + fl);
  if (hit) { count_("f", "c"); return JSON.parse(hit); }
  var z = function (s) { if (!s || !/^\d{12}$/.test(s)) return ""; var d = new Date(Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8), +s.slice(8, 10) - 9, +s.slice(10, 12))); return Utilities.formatDate(d, "UTC", "yyyyMMddHHmm"); };
  var out = [];
  [["getFltDeparturesDeOdp", "D"], ["getFltArrivalsDeOdp", "A"]].forEach(function (op) {
    count_("f", "a");
    var res = UrlFetchApp.fetch("https://apis.data.go.kr/B551177/statusOfAllFltDeOdp/" + op[0] + "?serviceKey=" + key_() + "&type=json&numOfRows=30&pageNo=1&flightId=" + fl, { muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) throw new Error("ICN HTTP " + res.getResponseCode());
    var it = ((JSON.parse(res.getContentText()).response || {}).body || {}).items || [];
    if (!Array.isArray(it)) it = it.item ? [].concat(it.item) : [];
    it.forEach(function (x) {
      if (String(x.codeshare || "").toLowerCase() === "slave") return;
      out.push({ t: z(x.scheduleDatetime), e: z(x.estimatedDatetime), io: op[1], ap: x.airportCode || "", term: x.terminalId || "", gate: x.gateNumber || "", chk: x.chkinRange || "", st: x.remark || "" });
    });
  });
  out.sort(function (a, b) { return a.t < b.t ? -1 : 1; });
  var r = { ok: true, f: out };
  try { c.put("f" + fl, JSON.stringify(r), 60); } catch (x) {}
  return r;
}

// ── 사용량 세기 ──────────────────────────────────────────────
// 스크립트 속성 "u_YYYYMMDD"(한국 날짜) = {"t":{"a":실제 API 호출,"c":캐시 재사용,"e":오류}, …}
// s=서울 · g=경기 · t=인천(TAGO) · f=인천공항 운항. 사용자 정보는 저장하지 않음. 30일 지나면 지움
var SVC_NAME = { s: "서울 버스", g: "경기 버스", t: "인천 버스(TAGO)", f: "인천공항 운항" };
var SVC_LIMIT = { t: 1000 };   // 개발계정 하루 한도(알려진 것만) → 화면에 % 표시

function count_(svc, kind) {
  if (!SVC_NAME[svc]) return;
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(800)) return;                       // 바쁘면 이번 1건은 건너뜀 (응답이 우선)
  try {
    var props = PropertiesService.getScriptProperties();
    var day = Utilities.formatDate(new Date(), "Asia/Seoul", "yyyyMMdd"), k = "u_" + day;
    var d = JSON.parse(props.getProperty(k) || "{}");
    if (!d[svc]) d[svc] = { a: 0, c: 0, e: 0 };
    d[svc][kind] = (d[svc][kind] || 0) + 1;
    props.setProperty(k, JSON.stringify(d));
    if (props.getProperty("u_last") !== day) {           // 하루 한 번 오래된 날짜 정리
      var old = Utilities.formatDate(new Date(Date.now() - 30 * 864e5), "Asia/Seoul", "yyyyMMdd");
      Object.keys(props.getProperties()).forEach(function (x) { if (/^u_\d{8}$/.test(x) && x.slice(2) < old) props.deleteProperty(x); });
      props.setProperty("u_last", day);
    }
  } catch (x) {
  } finally { lock.releaseLock(); }
}

function usage_(json) {
  var all = PropertiesService.getScriptProperties().getProperties();
  var days = Object.keys(all).filter(function (x) { return /^u_\d{8}$/.test(x); }).sort().reverse();
  var rows = days.map(function (k) { return { day: k.slice(2), d: JSON.parse(all[k] || "{}") }; });
  if (json) return ContentService.createTextOutput(JSON.stringify({ ok: true, limit: SVC_LIMIT, days: rows })).setMimeType(ContentService.MimeType.JSON);
  var svcs = ["t", "s", "g", "f"];
  var h = '<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:14px system-ui,sans-serif;margin:16px;color:#0B2545}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #D3DFEA;padding:6px 4px;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{font-size:12px;color:#5D7590}small{color:#5D7590}.w{color:#C2410C;font-weight:700}</style>';
  h += "<h3>중계 서버 사용량 (한국 날짜)</h3><p><small>숫자 = 실제 공공데이터 API 호출 수 · 괄호 = 캐시 재사용 · 빨강 = 오류. 인천공항 운항은 조회 1번에 API 2번(출발·도착).</small></p><table><tr><th>날짜</th>";
  svcs.forEach(function (s) { h += "<th>" + SVC_NAME[s] + "</th>"; });
  h += "</tr>";
  rows.forEach(function (r) {
    h += "<tr><td>" + r.day.slice(4, 6) + "/" + r.day.slice(6) + "</td>";
    svcs.forEach(function (s) {
      var x = r.d[s] || { a: 0, c: 0, e: 0 }, lim = SVC_LIMIT[s];
      var pct = lim ? " <small" + (x.a >= lim * 0.8 ? ' class="w"' : "") + ">" + Math.round(x.a * 100 / lim) + "%</small>" : "";
      h += "<td><b>" + x.a + "</b>" + pct + " <small>(" + x.c + ")</small>" + (x.e ? ' <span class="w">⚠' + x.e + "</span>" : "") + "</td>";
    });
    h += "</tr>";
  });
  if (!rows.length) h += '<tr><td colspan="5"><small>아직 기록이 없습니다.</small></td></tr>';
  return HtmlService.createHtmlOutput(h + "</table>").setTitle("중계 서버 사용량");
}

// 편집기에서 ▶ 실행해 보는 시험용 (서울 6001 서울역 · 인천공항 방향)
function test() {
  Logger.log(JSON.stringify(seoul_("100100412", "101000230", 39)));
  Logger.log(JSON.stringify(tago_("ICB365000068", "ICB368001264")));      // 인천 306 · LG마그나
  Logger.log(JSON.stringify(flight_("KE017")));                            // 인천공항 KE017 실시간
  Logger.log(usage_(true).getContent());                                   // 오늘 사용량
}
