// sw.js — Service Worker Content Tracker
const CACHE_NAME = 'ct-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

// Push notification reçue
self.addEventListener('push', e => {
  let data = { title: 'Content Tracker', body: '', url: '/' };
  try { data = { ...data, ...JSON.parse(e.data.text()) }; } catch {}

  e.waitUntil(
    self.registration.showNotification(data.title, {
      body:    data.body,
      icon:    '/icon-192.png',
      badge:   '/icon-192.png',
      data:    { url: data.url },
      vibrate: [100, 50, 100],
      actions: [{ action: 'open', title: 'Voir' }],
    })
  );
});

// Clic sur la notification
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data?.url || '/';
  e.waitUntil(
    self.clients.matchAll({ type: 'window' }).then(clients => {
      const existing = clients.find(c => c.url === url && 'focus' in c);
      if (existing) return existing.focus();
      return self.clients.openWindow(url);
    })
  );
});
