// Service worker: cachea la interfaz para que la PWA abra al instante.
// data.json siempre se pide a la red primero (con respaldo en cache).
const CACHE = 'bot-qqq-v7';
const SHELL = ['./bot.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.pathname.endsWith('data.json')) {
    // Red primero; si no hay conexion, ultima copia guardada
    e.respondWith(
      fetch(e.request).then(r => {
        const copia = r.clone();
        caches.open(CACHE).then(c => c.put('data.json', copia));
        return r;
      }).catch(() => caches.match('data.json'))
    );
  } else {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
