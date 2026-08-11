/**
 * FootSim Service Worker
 *
 * Strategie: Cache First für statische Dateien, Network First für API.
 * Das bedeutet: die App öffnet sich auch ohne Internet (zeigt gecachte Seite),
 * aber API-Daten werden immer frisch geholt wenn möglich.
 */

const CACHE_NAME = "footsim-v19";

// Diese Dateien werden beim ersten Laden gecacht
// und dann aus dem Cache bedient – das macht die App installierbar
const STATIC_ASSETS = [
    "/",
    "/static/style.css",
    "/static/script.js",
    "/static/pdfmerge.css",
    "/static/pdfmerge.js",
    "/static/legal.css",
    "/static/images/logofoot.png",
    "/manifest.json",
];

// API-Routen – immer vom Netz, nie aus dem Cache
const API_ROUTES = [
    "/api/",
    "/tools/pdf/merge",
];


// ── Installation: statische Dateien cachen ──────────────────────────
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_ASSETS).catch((error) => {
                // Einzelne fehlgeschlagene Assets blockieren nicht die Installation
                console.warn("FootSim SW: Nicht alle Assets gecacht:", error);
            });
        })
    );

    // Sofort aktiv werden, nicht auf Schließen anderer Tabs warten
    self.skipWaiting();
});


// ── Aktivierung: alten Cache aufräumen ─────────────────────────────
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((key) => caches.delete(key))
            )
        )
    );

    self.clients.claim();
});


// ── Fetch: Anfragen abfangen ────────────────────────────────────────
self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    // Nur eigene Herkunft behandeln
    if (url.origin !== self.location.origin) return;

    // API-Anfragen: immer Netz, kein Cache
    const isApi = API_ROUTES.some((route) => url.pathname.startsWith(route));
    if (isApi) {
        event.respondWith(fetch(event.request));
        return;
    }

    // Statische Dateien: Cache First, Netz als Fallback
    event.respondWith(
        caches.match(event.request).then((cached) => {
            if (cached) return cached;

            return fetch(event.request).then((response) => {
                // Nur gültige Antworten cachen
                if (!response || response.status !== 200 || response.type !== "basic") {
                    return response;
                }

                const toCache = response.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, toCache);
                });

                return response;
            });
        })
    );
});
