/* Laboratorio MNQ - service worker con alcance /backtest/ */
const CACHE = 'labmnq-v1';
const ARCHIVOS = ['./','./index.html','./manifest.json','./icon.svg','./icon-maskable.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ARCHIVOS))
    .then(() => self.skipWaiting()).catch(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (e.request.url.indexOf('fonts.g') !== -1) {
    e.respondWith(fetch(e.request).then(r => {
      const copia = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, copia)).catch(() => {});
      return r;
    }).catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
    if (r && r.status === 200 && r.type === 'basic') {
      const copia = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, copia)).catch(() => {});
    }
    return r;
  })));
});
