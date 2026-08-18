/* MAGMAX Scanner - service worker
   La app vive completa en index.html; el resto es opcional. */
const CACHE = "magmax-v4";
const ARCHIVOS = ["./", "./index.html", "./manifest.json", "./icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c =>
      // uno por uno: si alguno falta, los demas igual se cachean
      Promise.all(ARCHIVOS.map(u => c.add(u).catch(() => null)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// red primero para el HTML (para que una version nueva llegue sola),
// cache primero para lo demas.
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const esHTML = e.request.mode === "navigate" ||
                 (e.request.headers.get("accept") || "").includes("text/html");
  if (esHTML) {
    e.respondWith(
      fetch(e.request).then(r => {
        const copia = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, copia));
        return r;
      }).catch(() => caches.match(e.request).then(x => x || caches.match("./index.html")))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      if (r && r.status === 200 && r.type === "basic") {
        const copia = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, copia));
      }
      return r;
    }).catch(() => null))
  );
});
