// Service worker: makes the app installable, launches instantly, and receives
// photos shared from the phone's normal camera/gallery app.
//
// Caching strategy is deliberately conservative. Nutrition data must never be
// served stale, so /api and /media are always network-only -- a wrong calorie
// total is worse than an error message.

// Injected by the server from the static files' own mtimes and sizes, so a
// changed asset invalidates the cache automatically. Bumping a constant by
// hand was the previous scheme and it was forgotten on the first update,
// which left installed clients running old JS against new HTML.
const VERSION = '__BUILD_ID__';
const SHELL_CACHE = `shell-${VERSION}`;
const SHARE_CACHE = 'shared-image';
const SHARE_KEY = '/__shared-image';

const SHELL = [
  '/', '/log', '/workout', '/capture', '/progress',
  '/static/css/app.css',
  '/static/js/api.js',
  '/static/js/dashboard.js',
  '/static/js/log.js',
  '/static/js/workout.js',
  '/static/js/capture.js',
  '/static/js/progress.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // addAll is atomic: one 404 would discard the whole cache, so failures are
    // tolerated per-entry instead.
    await Promise.allSettled(SHELL.map((url) => cache.add(url)));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((n) => n.startsWith('shell-') && n !== SHELL_CACHE)
        .map((n) => caches.delete(n)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // --- Android share target: a photo shared into the app ---
  if (request.method === 'POST' && url.pathname === '/share-target') {
    event.respondWith(handleShare(request));
    return;
  }

  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Live data is never served from cache.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) return;

  // Pages: network first, cache as fallback, so the shell still opens when the
  // homelab is unreachable and the user gets a real error instead of a blank tab.
  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(request);
        const cache = await caches.open(SHELL_CACHE);
        cache.put(request, fresh.clone());
        return fresh;
      } catch {
        return (await caches.match(request)) || (await caches.match('/')) || Response.error();
      }
    })());
    return;
  }

  // Static assets: cache first, refreshed in the background.
  event.respondWith((async () => {
    const hit = await caches.match(request);
    if (hit) {
      event.waitUntil((async () => {
        try {
          const fresh = await fetch(request);
          const cache = await caches.open(SHELL_CACHE);
          await cache.put(request, fresh);
        } catch { /* offline: keep the cached copy */ }
      })());
      return hit;
    }
    return fetch(request);
  })());
});

/**
 * Stash the shared photo in a cache and bounce to the logger, which picks it up.
 * A redirect is required here: the share POST must not leave the user on a
 * blank response, and the file cannot be passed through a URL.
 */
async function handleShare(request) {
  try {
    const form = await request.formData();
    const file = form.get('image');
    if (file && file.size) {
      const cache = await caches.open(SHARE_CACHE);
      await cache.put(
        SHARE_KEY,
        new Response(file, {
          headers: {
            'Content-Type': file.type || 'image/jpeg',
            'X-Filename': encodeURIComponent(file.name || 'shared.jpg'),
          },
        }),
      );
      return Response.redirect('/log?share=1', 303);
    }
  } catch { /* fall through to a plain open */ }
  return Response.redirect('/log', 303);
}
