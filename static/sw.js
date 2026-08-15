/* ============================================================
   Service Worker — Unimaster Web Push
   ============================================================ */

const CACHE_NAME = 'unimaster-v1';

// ── Instalar ──────────────────────────────────────────────
self.addEventListener('install', e => {
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(self.clients.claim());
});

// ── Push recebido ─────────────────────────────────────────
self.addEventListener('push', e => {
    let data = {};
    try { data = e.data ? e.data.json() : {}; } catch (_) {}

    const title   = data.title   || 'Unimaster';
    const body    = data.body    || '';
    const icon    = data.icon    || '/static/img/icon-192.png';
    const badge   = data.badge   || '/static/img/badge-72.png';
    const url     = data.url     || '/';
    const tag     = data.tag     || 'default';
    const actions = data.actions || [];

    e.waitUntil(
        self.registration.showNotification(title, {
            body,
            icon,
            badge,
            tag,
            data: { url },
            actions,
            vibrate: [200, 100, 200],
            requireInteraction: data.requireInteraction || false,
        })
    );
});

// ── Clique na notificação ──────────────────────────────────
self.addEventListener('notificationclick', e => {
    e.notification.close();

    const url = (e.notification.data && e.notification.data.url) || '/';

    if (e.action === 'dismiss') return;

    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(wins => {
            const match = wins.find(w => w.url.includes(url) && 'focus' in w);
            if (match) return match.focus();
            if (clients.openWindow) return clients.openWindow(url);
        })
    );
});
