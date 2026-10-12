/**
 * 운항 도우미 - 근무표 동기화 서버 (Google Apps Script, 다른 스크립트와 별도)
 *
 * 하는 일
 *   - 같은 '내 아이디'를 쓰는 기기끼리 근무표를 맞춤 (사용자가 켠 경우만)
 *   - 근무표는 기기에서 '연결 코드'로 암호화된 덩어리로만 받음 → 서버·운영자는 내용을 읽을 수 없음
 *   - 연결 코드 자체는 받지 않음. 본인 확인값(연결 코드에서 만든 해시)으로 아이디 주인만 쓰고 읽고 지움
 *   - 지난달~다음 두 달(4개월)만 기기가 보내고, 120일 동안 갱신 없는 사본은 자동 삭제
 *
 * 설정 (한 번만)
 *   1) script.google.com → 새 프로젝트 → 이 파일 내용을 붙여넣기 → 저장 (이름 예: FLT Assist 근무표 동기화)
 *   2) 편집기 위쪽 함수 선택에서 setup 을 고르고 ▶실행 → 권한 허용 (자료를 담을 스프레드시트를 내 드라이브에 만듦)
 *   3) 배포 → 새 배포 → 유형: 웹 앱 → 실행: 나 / 액세스: 모든 사용자 → 배포 → 웹 앱 주소를 알려 주세요
 *   (스크립트 속성에 넣을 비밀값은 없습니다)
 *
 * 요청 (POST, 본문 JSON 글자)
 *   {"a":"ping"}
 *   {"a":"put","id":"ABC234","h":"<64자리>","ts":"2026-10-12T07:00:00.000Z","blob":"…"}   → 저장 (덮어쓰기)
 *   {"a":"get","id":"…","h":"…","since":"…"}   → since 보다 새로우면 blob, 아니면 ts 만
 *   {"a":"del","id":"…","h":"…"}               → 서버 사본 삭제
 *
 * 공유 그룹 (그룹당 4명, 1인당 5개, 내용은 그룹 비밀키로 기기에서 암호화 → 서버는 못 읽음)
 *   reg                      → 내 아이디 등록 (초대받으려면 먼저 등록돼 있어야 함)
 *   gcreate                  → 새 그룹 (만든 사람 = 관리자)
 *   glist                    → 내가 속한 그룹·멤버 아이디·대기 중 초대
 *   ginvite {gid,target,tok} → 관리자가 상대 아이디 지정 초대 (24시간). 등록된 아이디만
 *   gcancel {gid,target}     → 초대 취소
 *   gjoin   {gid,tok}        → 초대받은 그 아이디만 참가
 *   gleave  {gid[,target]}   → 나가기 (관리자는 target 으로 내보내기). 나간 사람 공유본 삭제
 *   gput    {gid,ts,blob}    → 그룹에 내 근무표(암호화) 올리기
 *   gget    {gids:[…],since:{gid:{id:ts}}} → 멤버들 공유본 (since 보다 새 것만 내용 포함)
 *   pull    {since, gids, gsince}  → get + gget 를 한 번에 (앱을 열 때 요청 수 절반)
 *   읽기(get·gget·glist·pull)는 이미 등록된 아이디면 잠금 없이 처리 → 동시에 많이 열어도 줄 서지 않음
 *   (그룹 시트는 처음 쓸 때 자동으로 만듦 — setup 다시 실행할 필요 없음)
 */
var SHEET = "sync", HEAD = ["id", "vh", "ts", "size", "updated", "b1", "b2", "b3", "b4"];
var PART = 45000, MAX_BLOB = PART * 4;     // 셀 하나 5만 자 제한 → 4칸까지 나눠 저장
var PUT_LIMIT = 150;                       // 아이디당 6시간 저장 횟수
var MAX_ROWS = 5000, KEEP_DAYS = 120;
var AB = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
var G_MAX = 4, G_PER_USER = 5, INVITE_H = 24;
var NEW_ID_DAY = 500;                      // 하루 새로 등록되는 아이디 상한 (가짜 아이디 대량 등록 막기)
var TABLES = {
  ids: ["id", "vh", "created", "seen"],
  groups: ["gid", "owner", "members", "created", "updated"],
  invites: ["gid", "target", "th", "by", "exp"],
  shares: ["gid", "id", "ts", "updated", "b1", "b2"]
};

function setup() {
  var p = PropertiesService.getScriptProperties();
  if (!p.getProperty("SHEET_ID")) {
    var ss = SpreadsheetApp.create("FLT Assist 근무표 동기화 (암호화 자료 · 공유 금지)");
    var sh = ss.getSheets()[0].setName(SHEET);
    sh.getRange("A:I").setNumberFormat("@");
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
function hex_(bytes) { return bytes.map(function (b) { return ("0" + (b & 255).toString(16)).slice(-2); }).join(""); }
function sha_(s) { return hex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, s, Utilities.Charset.UTF_8)); }
// 본인 확인값 h(연결 코드의 아이디 해시 전체, 64자리 16진수) → 공개 아이디 6자리. 앱의 idOf 와 같은 계산
function idOfH_(h) {
  var out = "";
  for (var i = 0; i < 6; i++) out += AB[parseInt(h.substr(i * 8, 8), 16) % AB.length];
  return out;
}
function find_(sh, id) {
  var n = sh.getLastRow(); if (n < 2) return null;
  var ids = sh.getRange(2, 1, n - 1, 1).getValues();
  for (var i = 0; i < ids.length; i++) if (String(ids[i][0]).replace(/^'/, "") === id) return i + 2;
  return null;
}
function rowObj_(sh, r) {
  var v = sh.getRange(r, 1, 1, HEAD.length).getValues()[0], o = {};
  HEAD.forEach(function (h, j) { o[h] = String(v[j] == null ? "" : v[j]).replace(/^'/, ""); });
  return o;
}

function doGet() { return json_({ ok: true, svc: "roster", at: new Date().toISOString() }); }

function doPost(e) {
  try {
    var q = JSON.parse((e && e.postData && e.postData.contents) || "{}"), a = q.a || "";
    if (a === "ping") return json_({ ok: true, at: new Date().toISOString() });
    var id = String(q.id || ""), h = String(q.h || "").toLowerCase();
    if (!/^[A-Z2-9]{6}$/.test(id) || !/^[0-9a-f]{64}$/.test(h)) return json_({ ok: false, err: "bad" });
    if (idOfH_(h) !== id) return json_({ ok: false, err: "auth" });
    var vh = sha_("flt-assist-sync-v1:" + h);
    if (/^(pull|get|gget|glist)$/.test(a)) {          // 읽기: 등록된 아이디면 잠금 없이
      var me = tab_("ids").rows.filter(function (r) { return r.id === id; })[0];
      if (me && me.vh !== vh) return json_({ ok: false, err: "auth" });
      if (me) return json_(read_(a, q, id, vh));
    }
    var lock = LockService.getScriptLock(); lock.waitLock(15000);
    try {
      var rg = reg_(id, vh); if (rg !== "ok") return json_({ ok: false, err: rg });
      if (/^(pull|get|gget|glist)$/.test(a)) return json_(read_(a, q, id, vh));
      if (/^(reg|gcreate|glist|ginvite|gcancel|gjoin|gleave|gput)$/.test(a)) { var res = group_(a, q, id); if (Math.random() < 0.02) gclean_(); return json_(res); }
      var sh = sheet_(), r = find_(sh, id), cur = r ? rowObj_(sh, r) : null;
      if (cur && cur.vh !== vh) return json_({ ok: false, err: "auth" });
      if (a === "del") {
        if (r) sh.deleteRow(r);
        return json_({ ok: true, removed: !!r });
      }
      if (a === "put") {
        var blob = String(q.blob || ""), ts = String(q.ts || "");
        if (!blob || blob.length > MAX_BLOB || !/^[A-Za-z0-9+/=._-]+$/.test(blob)) return json_({ ok: false, err: "size" });
        if (!/^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(ts)) return json_({ ok: false, err: "bad" });
        var c = CacheService.getScriptCache(), ck = "p:" + id, n = +(c.get(ck) || 0);
        if (n >= PUT_LIMIT) return json_({ ok: false, err: "limit" });
        c.put(ck, String(n + 1), 21600);
        if (!r && sh.getLastRow() - 1 >= MAX_ROWS) { cleanup_(sh); if (sh.getLastRow() - 1 >= MAX_ROWS) return json_({ ok: false, err: "busy" }); }
        var parts = [0, 1, 2, 3].map(function (i) { var s = blob.substr(i * PART, PART); return s ? "'" + s : ""; });
        var v = ["'" + id, "'" + vh, "'" + ts, String(blob.length), "'" + new Date().toISOString()].concat(parts);
        if (r) sh.getRange(r, 1, 1, HEAD.length).setValues([v]); else sh.appendRow(v);
        if (Math.random() < 0.02) cleanup_(sh);
        return json_({ ok: true, ts: ts });
      }
      return json_({ ok: false, err: "bad" });
    } finally { lock.releaseLock(); }
  } catch (err) {
    return json_({ ok: false, err: "server", msg: String(err).slice(0, 150) });
  }
}

// ---------- 표(시트) 도우미 ----------
function tab_(name) {
  var ss = SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty("SHEET_ID"));
  var sh = ss.getSheetByName(name), head = TABLES[name];
  if (!sh) { sh = ss.insertSheet(name); sh.getRange("A:F").setNumberFormat("@"); sh.getRange(1, 1, 1, head.length).setValues([head]); }
  var n = sh.getLastRow(), rows = n < 2 ? [] : sh.getRange(2, 1, n - 1, head.length).getValues().map(function (r, i) {
    var o = { _r: i + 2 }; head.forEach(function (h, j) { o[h] = String(r[j] == null ? "" : r[j]).replace(/^'/, ""); }); return o;
  });
  return {
    rows: rows,
    put: function (o) {
      var v = head.map(function (h) { var x = o[h] == null ? "" : String(o[h]); return x && !/^\d+$/.test(x) ? "'" + x : x; });
      if (o._r) sh.getRange(o._r, 1, 1, head.length).setValues([v]); else { sh.appendRow(v); o._r = sh.getLastRow(); }
    },
    del: function (list) { list.map(function (o) { return o._r; }).sort(function (a, b) { return b - a; }).forEach(function (r) { sh.deleteRow(r); }); }
  };
}
// 아이디 등록부: 처음 본 아이디는 본인 확인값으로 등록, 이후엔 같은 값만
function reg_(id, vh) {
  var t = tab_("ids"), me = t.rows.filter(function (r) { return r.id === id; })[0], now = new Date().toISOString();
  if (me) { if (me.vh !== vh) return "auth"; if (me.seen.slice(0, 10) !== now.slice(0, 10)) { me.seen = now; t.put(me); } return "ok"; }
  if (t.rows.filter(function (r) { return r.created.slice(0, 10) === now.slice(0, 10); }).length >= NEW_ID_DAY) return "busy";
  t.put({ id: id, vh: vh, created: now, seen: now }); return "ok";
}
// 읽기 전용 요청
function syncGet_(id, vh, since) {
  var sh = sheet_(), r = find_(sh, id), cur = r ? rowObj_(sh, r) : null;
  if (cur && cur.vh !== vh) return { ok: false, err: "auth" };
  if (!cur) return { ok: true, none: true };
  if (since && String(since) >= cur.ts) return { ok: true, ts: cur.ts, same: true };
  return { ok: true, ts: cur.ts, blob: cur.b1 + cur.b2 + cur.b3 + cur.b4 };
}
function read_(a, q, id, vh) {
  if (a === "get") return syncGet_(id, vh, q.since);
  if (a === "gget") return gget_(q, id);
  if (a === "glist") return group_("glist", q, id);
  return { ok: true, sync: q.nosync ? null : syncGet_(id, vh, q.since), groups: q.gids && q.gids.length ? gget_({ gids: q.gids, since: q.gsince || {} }, id).groups : {} };
}
function rnd_(n) { var s = ""; while (s.length < n) { var u = Utilities.getUuid().replace(/-/g, ""); for (var i = 0; i < u.length && s.length < n; i += 2) s += AB[parseInt(u.substr(i, 2), 16) % AB.length]; } return s; }
function mem_(g) { return g.members ? g.members.split(",") : []; }

function group_(a, q, id) {
  var G = tab_("groups"), now = new Date().toISOString();
  var mine = G.rows.filter(function (g) { return mem_(g).indexOf(id) >= 0; });
  var one = function () { return G.rows.filter(function (g) { return g.gid === String(q.gid || ""); })[0]; };
  if (a === "reg") return { ok: true };
  if (a === "gcreate") {
    if (mine.length >= G_PER_USER) return { ok: false, err: "max" };
    var gid = rnd_(12); G.put({ gid: gid, owner: id, members: id, created: now, updated: now });
    return { ok: true, gid: gid };
  }
  if (a === "glist") {
    var I = tab_("invites");
    return { ok: true, groups: mine.map(function (g) {
      return { gid: g.gid, owner: g.owner, members: mem_(g), pend: I.rows.filter(function (v) { return v.gid === g.gid && v.exp > now; }).map(function (v) { return v.target; }) };
    }) };
  }
  if (a === "gjoin") {
    var I2 = tab_("invites"), th = sha_("flt-assist-invite-v1:" + String(q.tok || ""));
    var inv = I2.rows.filter(function (v) { return v.gid === String(q.gid || "") && v.th === th; })[0];
    if (!inv || inv.exp <= now) return { ok: false, err: "invite" };
    if (inv.target !== id) return { ok: false, err: "notyou" };
    var g = one(); if (!g) return { ok: false, err: "nogroup" };
    var m = mem_(g);
    if (m.indexOf(id) < 0) {
      if (mine.length >= G_PER_USER) return { ok: false, err: "max" };
      if (m.length >= G_MAX) return { ok: false, err: "full" };
      m.push(id); g.members = m.join(","); g.updated = now; G.put(g);
    }
    I2.del([inv]);
    return { ok: true, gid: g.gid, owner: g.owner, members: m };
  }
  var g2 = one(); if (!g2 || mem_(g2).indexOf(id) < 0) return { ok: false, err: "notmember" };
  var m2 = mem_(g2);
  if (a === "ginvite" || a === "gcancel") {
    if (g2.owner !== id) return { ok: false, err: "owner" };
    var target = String(q.target || "").toUpperCase(), I3 = tab_("invites");
    if (!/^[A-Z2-9]{6}$/.test(target)) return { ok: false, err: "bad" };
    var old = I3.rows.filter(function (v) { return v.gid === g2.gid && (v.target === target || v.exp <= now); });
    I3.del(old);
    if (a === "gcancel") return { ok: true };
    if (m2.indexOf(target) >= 0) return { ok: false, err: "already" };
    if (!tab_("ids").rows.some(function (r) { return r.id === target; })) return { ok: false, err: "unreg" };
    var pend = I3.rows.filter(function (v) { return v.gid === g2.gid && v.exp > now && v.target !== target; }).length;
    if (m2.length + pend >= G_MAX) return { ok: false, err: "full" };
    if (!/^[A-Z2-9]{10,40}$/.test(String(q.tok || ""))) return { ok: false, err: "bad" };
    var exp = new Date(Date.now() + INVITE_H * 3600e3).toISOString();
    tab_("invites").put({ gid: g2.gid, target: target, th: sha_("flt-assist-invite-v1:" + q.tok), by: id, exp: exp });
    return { ok: true, exp: exp };
  }
  if (a === "gleave") {
    var who = q.target ? String(q.target).toUpperCase() : id;
    if (who !== id && g2.owner !== id) return { ok: false, err: "owner" };
    var S = tab_("shares"); S.del(S.rows.filter(function (r) { return r.gid === g2.gid && r.id === who; }));
    m2 = m2.filter(function (x) { return x !== who; });
    if (!m2.length) { G.del([g2]); var I4 = tab_("invites"); I4.del(I4.rows.filter(function (v) { return v.gid === g2.gid; })); return { ok: true, gone: true }; }
    g2.members = m2.join(","); if (g2.owner === who) g2.owner = m2[0]; g2.updated = now; G.put(g2);
    return { ok: true };
  }
  if (a === "gput") {
    var blob = String(q.blob || ""), ts = String(q.ts || "");
    if (!blob || blob.length > PART * 2 || !/^[A-Za-z0-9+/=._-]+$/.test(blob) || !/^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(ts)) return { ok: false, err: "size" };
    var c = CacheService.getScriptCache(), ck = "g:" + id, n = +(c.get(ck) || 0);
    if (n >= PUT_LIMIT * 2) return { ok: false, err: "limit" }; c.put(ck, String(n + 1), 21600);
    var S2 = tab_("shares"), r = S2.rows.filter(function (x) { return x.gid === g2.gid && x.id === id; })[0] || {};
    r.gid = g2.gid; r.id = id; r.ts = ts; r.updated = now; r.b1 = blob.substr(0, PART); r.b2 = blob.substr(PART);
    S2.put(r);
    return { ok: true, ts: ts };
  }
  return { ok: false, err: "bad" };
}
// 여러 그룹 공유본 한 번에 (멤버인 그룹만)
function gget_(q, id) {
  var G = tab_("groups").rows, S = tab_("shares").rows, I = tab_("invites").rows, since = q.since || {}, out = {}, now = new Date().toISOString();
  (q.gids || []).slice(0, G_PER_USER).forEach(function (gid) {
    var g = G.filter(function (x) { return x.gid === gid; })[0];
    if (!g || mem_(g).indexOf(id) < 0) { out[gid] = { ok: false, err: "notmember" }; return; }
    var sn = since[gid] || {};
    out[gid] = { ok: true, owner: g.owner, members: mem_(g), pend: I.filter(function (v) { return v.gid === gid && v.exp > now; }).map(function (v) { return v.target; }), sh: S.filter(function (r) { return r.gid === gid && mem_(g).indexOf(r.id) >= 0; }).map(function (r) {
      return sn[r.id] && sn[r.id] >= r.ts ? { id: r.id, ts: r.ts, same: true } : { id: r.id, ts: r.ts, blob: r.b1 + r.b2 };
    }) };
  });
  return { ok: true, groups: out };
}

// 오래 갱신 없는 사본 지우기
function gclean_() {
  var now = new Date().toISOString(), lim = new Date(Date.now() - KEEP_DAYS * 864e5).toISOString();
  var I = tab_("invites"); I.del(I.rows.filter(function (v) { return v.exp <= now; }));
  var S = tab_("shares"); S.del(S.rows.filter(function (r) { return r.updated < lim; }));
}
function cleanup_(sh) {
  var n = sh.getLastRow(); if (n < 2) return;
  var lim = new Date(Date.now() - KEEP_DAYS * 864e5).toISOString();
  var v = sh.getRange(2, 1, n - 1, 5).getValues();
  for (var i = v.length - 1; i >= 0; i--) if (String(v[i][4]).replace(/^'/, "") < lim) sh.deleteRow(i + 2);
}
