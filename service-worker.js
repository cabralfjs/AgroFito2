const CACHE_NAME = 'agrofito-v3';

// Só ficheiros verdadeiramente estáticos (raramente ou nunca mudam) ficam
// em cache-primeiro. As páginas HTML SAÍRAM daqui de propósito - ver a
// função fetch mais abaixo.
const CORE_ASSETS = [
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './xlsx.min.js'
];

// Páginas da própria app: mudam com frequência (o site está em
// desenvolvimento ativo), por isso vão sempre à rede primeiro para
// garantir que quem visita recebe a versão mais recente. A cópia em
// cache só serve de reserva para quando não há ligação.
const NETWORK_FIRST_PAGES = [
  './',
  './index.html',
  './usos.html',
  './produtos.html'
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

function matchesList(url, list) {
  const path = new URL(url).pathname;
  return list.some((a) => path.endsWith(a.replace('./', '/')) || path === '/');
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  // Páginas HTML da app: rede primeiro, cache como reserva offline.
  if (matchesList(event.request.url, NETWORK_FIRST_PAGES)) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Ficheiros verdadeiramente estáticos: cache primeiro, rede só se
  // ainda não estiverem guardados.
  if (matchesList(event.request.url, CORE_ASSETS)) {
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

  // Tudo o resto (dados JSON do SIFITO, ficheiros de LMR) — rede
  // primeiro, para ficarem sempre atualizados quando há ligação; cache
  // só como reserva para quando está offline.
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
