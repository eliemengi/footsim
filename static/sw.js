/**
 * FootSim Service Worker
 *
 * Strategie: Cache First für statische Dateien, Network First für API.
 * Das bedeutet: die App öffnet sich auch ohne Internet (zeigt gecachte Seite),
 * aber API-Daten werden immer frisch geholt wenn möglich.
 */

const CACHE_NAME = "footsim-v27";

// Diese Dateien werden beim ersten Laden gecacht
// und dann aus dem Cache bedient – das macht die App installierbar
const STATIC_ASSETS = [
    "/?lang=de",
    "/?lang=en",
    "/offline?lang=de",
    "/offline?lang=en",
    "/static/style.css",
    "/static/script.js",
    "/static/i18n/de.json",
    "/static/i18n/en.json",
    "/static/pdfmerge.css",
    "/static/pdfmerge.js",
    "/static/legal.css",
    "/static/images/logofoot.png",
    "/manifest.json",
    "/manifest.json?lang=de",
    "/manifest.json?lang=en",
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

    // Navigation stays usable when the network is unavailable.  The selected
    // locale travels in the first-party ``lang`` query used by the language
    // switcher; unknown/unsupported values safely fall back to English.
    if (event.request.mode === "navigate") {
        const locale = url.searchParams.get("lang") === "de" ? "de" : "en";
        event.respondWith(
            fetch(event.request)
                .catch(() => caches.match(`/offline?lang=${locale}`))
                // caches.match() liefert undefined, wenn die Offline-Seite
                // beim Install nicht gecacht werden konnte. respondWith()
                // wuerde daraus eine Netzwerkfehler-Antwort machen, statt
                // den Browser sein eigenes Offline-Verhalten zeigen zu
                // lassen - deshalb hier ausdruecklich pruefen.
                .then((response) => response || Response.error())
        );
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
        }).catch(() => {
            // Ohne diesen Zweig endete jeder fehlgeschlagene Netzabruf als
            // unbehandelte Promise-Ablehnung ("Uncaught (in promise)
            // TypeError: Failed to fetch") und zusaetzlich als
            // Netzwerkfehler-Antwort. Der Fehler bleibt ein Fehler, aber
            // er ist jetzt behandelt und verrauscht die Konsole nicht.
            return Response.error();
        })
    );
});
