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
 * 요청:  ?s=s&r=노선ID&st=정류장ID&o=순번   (s=s 서울, s=g 경기)
 * 응답:  {"ok":true,"at":"…","b":[{"m":분,"left":남은정류장,"plate":"차량번호","last":막차여부,"seat":빈자리},…]}
 *
 * 같은 노선(서울)·정류장(경기)은 30초 동안 저장해 두고 재사용 → 공공데이터 하루 호출 한도 절약
 */
var CACHE_SEC = 30;

function doGet(e) {
  var p = (e && e.parameter) || {};
  var out;
  try {
    if (!/^[sg]$/.test(p.s || "") || !/^\d{6,12}$/.test(p.r || "") || !/^\d{6,12}$/.test(p.st || "") || !/^\d{1,3}$/.test(p.o || "")) {
      out = { ok: false, err: "bad request" };
    } else {
      out = p.s === "s" ? seoul_(p.r, p.st, +p.o) : gbis_(p.r, p.st, +p.o);
    }
  } catch (err) {
    out = { ok: false, err: String(err).slice(0, 200) };
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
  if (hit) return JSON.parse(hit);
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

// 편집기에서 ▶ 실행해 보는 시험용 (서울 6001 서울역 · 인천공항 방향)
function test() {
  Logger.log(JSON.stringify(seoul_("100100412", "101000230", 39)));
}
