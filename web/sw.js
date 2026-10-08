// 오프라인 지원용 Service Worker
// 온라인이면 항상 최신 파일을 받아 캐시에 저장하고, 오프라인이면 캐시에서 제공합니다.
const CACHE = "callsign-v27";
const SHELL = ["./", "index.html", "data.js", "data.json", "manifest.webmanifest", "icon.svg", "icon-180.png", "icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function withTimeout(p, ms) {
  return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  const url = new URL(req.url);
  url.search = "";                       // data.json?t=… 도 같은 캐시 항목으로 저장
  const key = req.mode === "navigate" ? new URL("index.html", self.registration.scope).href : url.href;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const res = await withTimeout(fetch(req), 6000);
      if (res.ok) cache.put(key, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(key, { ignoreSearch: true });
      if (hit) return hit;
      throw err;
    }
  })());
});

// 페이지에서 "최신 데이터 받기" 후 data.js 도 새로 캐시
self.addEventListener("message", (e) => {
  if (e.data === "refresh") {
    caches.open(CACHE).then((c) => c.add("data.js")).catch(() => {});
  }
});
