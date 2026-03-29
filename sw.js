// ═══════════════════════════════════════════════
//  RECKON 1.O  —  Service Worker  (v2)
// ═══════════════════════════════════════════════
const CACHE_NAME = 'reckon-v1';

// Pages / assets to cache for offline shell
const ASSETS = [
    '/',
    '/index.html',
    '/leaderboard.html',
    '/schedule.html',
    '/help.html',
    '/team-dashboard.html',
    '/gallery.html',
    '/judge.html',
    '/admin.html',
    '/logo.jpg',
    'https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.js',
    'https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;700;900&family=Exo+2:wght@300;400;600;700&family=Rajdhani:wght@400;500;600;700&display=swap'
];

// ── INSTALL: cache shell ──
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(ASSETS).catch(err => {
                console.warn('[SW] Some shell URLs failed to cache:', err);
            });
        })
    );
    self.skipWaiting();
});

// ── ACTIVATE: clean old caches ──
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// ── FETCH: network-first for API, cache-first for assets ──
self.addEventListener('fetch', event => {
    const url = event.request.url;

    // Skip non-GET and chrome-extension requests
    if (event.request.method !== 'GET' || url.startsWith('chrome-extension')) return;

    // Skip Socket.IO entirely so the browser handles real-time polling natively
    if (url.includes('/socket.io/')) return;

    // API calls: network only, with offline fallback
    if (url.includes('/api/')) {
        event.respondWith(
            fetch(event.request).catch(() =>
                new Response(JSON.stringify({ error: 'Offline — please check your connection.' }), {
                    headers: { 'Content-Type': 'application/json' },
                    status: 503
                })
            )
        );
        return;
    }

    // Everything else: network-first, fallback to cache
    event.respondWith(
        fetch(event.request)
            .then(response => {
                if (response && response.status === 200 && response.type === 'basic') {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => {
                return caches.match(event.request).then(cached => {
                    if (cached) return cached;
                    if (event.request.mode === 'navigate' || (event.request.headers.get('accept') && event.request.headers.get('accept').includes('text/html'))) {
                        return caches.match('/index.html');
                    }
                });
            })
    );
});

// ── PUSH: show notification ──
self.addEventListener('push', event => {
    let data = { title: 'RECKON 1.O', body: 'New update!', url: '/', tag: 'rec1o', urgent: false };
    try {
        if (event.data) data = { ...data, ...event.data.json() };
    } catch (e) {
        if (event.data) data.body = event.data.text();
    }

    const options = {
        body: data.body,
        icon: '/logo.jpg',
        badge: '/logo.jpg',
        tag: data.tag || 'rec1o-notif',
        data: { url: data.url || '/' },
        vibrate: [200, 100, 200, 100, 200],
        requireInteraction: !!data.urgent,
        actions: data.urgent
            ? [{ action: 'open', title: '🚀 Open Now' }, { action: 'dismiss', title: 'Dismiss' }]
            : [{ action: 'open', title: 'View' }]
    };

    if (data.image) options.image = data.image;

    event.waitUntil(self.registration.showNotification(data.title, options));
});

// ── NOTIFICATION CLICK: open URL ──
self.addEventListener('notificationclick', event => {
    event.notification.close();

    if (event.action === 'dismiss') return;

    const targetUrl = event.notification.data?.url || '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
            // If app is already open, focus it and navigate
            for (const client of clientList) {
                if (client.url.includes(self.registration.scope) && 'focus' in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            // Otherwise open a new window
            if (clients.openWindow) return clients.openWindow(targetUrl);
        })
    );
});

// ── PUSH SUBSCRIPTION CHANGE ──
self.addEventListener('pushsubscriptionchange', event => {
    event.waitUntil(
        self.registration.pushManager.subscribe(event.oldSubscription.options)
            .then(subscription =>
                fetch('/api/push/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(subscription)
                })
            )
    );
});
