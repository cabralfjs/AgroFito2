const CACHE_NAME = 'agrofito-v2';
const CORE_ASSETS = [
  './',
  './index.html',
  './usos.html',
  './produtos.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './xlsx.min.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

function isCoreAsset(url) {
  const path = new URL(url).pathname;
  return CORE_ASSETS.some((a) => path.endsWith(a.replace('./', '/')) || path === '/' );
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  // Ficheiros da própria app (HTML, JS, ícones, manifest) — quase nunca
  // mudam, por isso servimos logo da cache (rápido) e só vamos à rede
  // se ainda não estiverem lá. Isto é o que estava a faltar antes, e o
  // que causava a lentidão: tudo ia à rede primeiro, incluindo o
  // xlsx.min.js (~1 MB) em todas as visitas.
  if (isCoreAsset(event.request.url)) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
          return response;
        });
      })
    );
    return;
  }

  // Tudo o resto (os dados JSON do SIFITO) — rede primeiro, para
  // ficarem sempre atualizados quando há ligação; cache só como
  // reserva para quando está offline.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
