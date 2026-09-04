const CACHE = "pm25-v2";
const SHELL = ["/", "/index.html", "/app.js", "/charts.js", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) {
    // network-first, fall back to last cached API response when offline
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          if (r.ok && r.status === 200) {
            const clone = r.clone();
            caches.open(CACHE).then((c) => c.put(e.request, clone));
          }
          return r;
        })
        .catch(async () => {
          const cached = await caches.match(e.request);
          if (!cached) throw new Error("no cached response");
          const headers = new Headers(cached.headers);
          headers.set("X-PM25-Cached", "1");
          return new Response(await cached.blob(), { status: 200, headers });
        })
    );
  } else {
    // cache-first for the app shell
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
