/**
 * FootSim Service Worker
 *
 * Strategie: Cache First für statische Dateien, Network First für API.
 * Das bedeutet: die App öffnet sich auch ohne Internet (zeigt gecachte Seite),
 * aber API-Daten werden immer frisch geholt wenn möglich.
 */

// Die Versionsnummer MUSS steigen, sobald sich ausgelieferte Dateien
// ändern – der activate-Handler löscht alle Caches mit abweichendem
// Namen, und nur dadurch bekommen bestehende Installationen den neuen
// Stand statt des alten aus dem Cache.
//
// v29: Die Startseite wird nicht mehr vorgecacht; damit verschwand das
//      dort mitgespeicherte CSRF-Token aus dem geteilten Cache.
// v30: script.js (saisonkorrekter CL-Vergleich) und legal.css (mobile
//      Speicherübersicht der Datenschutzseite) haben sich geändert.
//      Ohne neue Version behielten Bestandsinstallationen die alten
//      Dateien und damit den Saisonfehler.
// v32: Datenreparatur. Zwei Änderungen, die zusammengehören.
//
//      1. Neue Cacheversion. Sie ist hier NICHT nur Formsache: Die
//         Übersetzungsschlüssel player.positionHint.free und
//         player.scopeHint.club_all kamen am 13.08.2026 dazu, der letzte
//         committete Versionssprung lag am 28.07.2026 - 55 Commits davor.
//         Wer dazwischen installiert hat, bekam die alte de.json aus dem
//         Cache und sah dauerhaft die rohen Schlüssel statt der Texte.
//
//      2. Übersetzungen werden nicht mehr Cache-First bedient. Genau
//         diese Strategie hat den alten Stand konserviert: Ohne
//         Versionswechsel wurde nie neu geladen, und ein Versionswechsel
//         wird beim Hinzufügen eines Textes leicht vergessen. Ein
//         Auslieferungsweg, der von menschlicher Disziplin abhängt, ist
//         kein Auslieferungsweg.
// v35: Die CTA-Gruppe im Hero. Zwei ausgelieferte Dateien haben sich
//      geaendert, und beide werden hier gecacht: style.css (die neuen
//      .tester-btn-Regeln) und die zwei Katalogdateien (hero.appSignup,
//      hero.appDownload).
//
//      Ohne den Versionssprung tritt exakt der unter v32 beschriebene
//      Fehler wieder ein - und er ist am 28.08.2026 auch aufgetreten:
//      Der erste Aufruf nach der Aenderung beantwortete beide Pfade aus
//      dem alten Cache. Sichtbar waren die rohen Schluessel
//      "hero.testerJoin"/"hero.testerDownload" statt der Beschriftungen
//      (applyTranslations ueberschreibt den serverseitig gerenderten
//      Text mit dem Katalogwert, und t() faellt bei fehlendem Schluessel
//      auf den Schluesselnamen zurueck) sowie zwei unterstrichene
//      Standardlinks statt der Knoepfe, weil das alte Stylesheet die
//      .tester-btn-Regeln nicht kannte.
//
//      stale-while-revalidate allein reicht dafuer nicht: Es erneuert
//      im Hintergrund und zeigt den neuen Stand erst beim NAECHSTEN
//      Aufruf. Fuer eine Auslieferung ist genau der erste Eindruck der
//      entscheidende.
// v36: iOS-Vorbereitung. Erneut haben sich zwei gecachte Dateien
//      geaendert - style.css (Ausblendregel fuer data-platform="ios")
//      und script.js (native Bruecke).
//
//      DER GRUND IST HIER NICHT FORMSACHE, SONDERN EIN REVIEW-RISIKO.
//      Navigationen laufen network-first, das neue index.html kommt also
//      sofort an und setzt data-platform="ios". style.css laeuft dagegen
//      stale-while-revalidate: Beim ERSTEN Aufruf nach einem Deployment
//      antwortet der Cache noch mit der alten Fassung - und die kennt nur
//      :root[data-platform="android"] .support.
//
//      Ergebnis ohne Versionssprung: In einer bereits installierten
//      iOS-App waeren nach einem Web-Deployment fuer genau einen Aufruf
//      der PayPal-Link, der Play-Store-Link und der Google-Groups-Link
//      wieder sichtbar. Play-Store- und Groups-Link verstossen gegen App
//      Store Review Guideline 2.3.10. Das Zeitfenster ist kurz, aber
//      genau waehrend einer TestFlight-Phase mit laufenden Deployments
//      real - und der Preis dafuer waere eine Ablehnung.
//
//      NACHTRAG zur selben Version: Inzwischen kam pdfmerge.js dazu (der
//      native Downloadweg im iOS-Modus). Dafuer ist der Sprung sogar
//      zwingender als fuer style.css: pdfmerge.js steht in
//      STATIC_ASSETS und wird CACHE-FIRST bedient, nicht
//      stale-while-revalidate. Ohne Versionswechsel wuerde eine
//      bestehende Installation die alte Fassung dauerhaft behalten - der
//      iOS-Downloadweg kaeme also NIE an, nicht nur einen Aufruf zu
//      spaet.
//
//      Eine ZWEITE Erhoehung ist nicht noetig: v36 ist noch nicht
//      ausgeliefert. Der Sprung von v35 traegt alle Aenderungen dieses
//      Durchgangs gemeinsam.
//
// v37 - Berechnungsansatz der Champions League (C8B).
//
//      Hier reicht die Revalidierung ausnahmsweise NICHT, und zwar wegen
//      des Zusammenspiels zweier Strategien: Navigationen laufen
//      network-first, das neue index.html ist also sofort da - mitsamt
//      der Ansatzwahl und den vier Reglern. script.js laeuft dagegen
//      stale-while-revalidate und antwortet beim ERSTEN Aufruf nach
//      einem Deployment noch aus dem alten Cache.
//
//      Fuer genau diesen einen Aufruf staende die neue Auswahl sichtbar
//      auf der Seite, ohne dass irgendetwas sie verdrahtet: kein
//      Klickverhalten, keine Regler, und der Request truege weiterhin
//      kein 'approach'. Eine sichtbare, tote Steuerung ist schlimmer als
//      gar keine.
//
//      Mit dem Versionssprung loescht der activate-Handler den alten
//      Cache, und install() legt script.js, style.css und beide
//      Sprachkataloge frisch ab. Ob v36 zwischenzeitlich ausgeliefert
//      wurde, spielt dabei keine Rolle - hoeher ist in jedem Fall
//      richtig.
//
// v38 - C0B. Zwei Aenderungen an ausgelieferten Dateien: der
//      Aktualisierungsvertrag in script.js (controllerchange mit
//      Reload-Guard) und die Freigabestufe im ML-Pfad.
//
//      Der Versionssprung und der neue controllerchange-Handler
//      arbeiten zusammen: Der Sprung sorgt dafuer, dass install() die
//      neuen Dateien frisch ablegt und activate() den alten Cache
//      loescht; der Handler sorgt dafuer, dass die bereits gerenderte
//      Seite den Wechsel auch mitbekommt. Ohne den Handler bliebe genau
//      eine Navigation mit neuem HTML und altem JavaScript stehen.
const CACHE_NAME = "footsim-v38";

// Dateien, die stale-while-revalidate laufen: Der Cache antwortet
// sofort, im Hintergrund wird erneuert. Beim nächsten Aufruf liegt die
// neue Fassung vor - ohne Versionssprung.
//
// SCRIPT UND STYLESHEET GEHÖREN SEIT v33 DAZU.
//
// Vorher waren sie Cache-First, und die Cacheversion war die EINZIGE
// Garantie, dass eine Installation je etwas Neues sieht. Im Browser ist
// das unschön; für die Android-App wäre es ein echter Fehler gewesen:
// Ein Nutzer mit altem Cache hätte neue Auswertungen dauerhaft nicht
// gesehen, und ein App-Update über den Play Store hätte daran nichts
// geändert - die TWA lädt dieselbe Website.
//
// Der Start bleibt schnell und offlinefähig, weil weiterhin zuerst der
// Cache antwortet. Nur die Erneuerung läuft jetzt daneben, statt auf
// eine Zahl zu warten, an die jemand denken muss.
const REVALIDATE_PATHS = [
    "/static/script.js",
    "/static/style.css",
    "/static/i18n/de.json",
    "/static/i18n/en.json",
];

// Diese Dateien werden beim ersten Laden gecacht
// und dann aus dem Cache bedient – das macht die App installierbar
//
// BEWUSST NICHT HIER: "/?lang=de" und "/?lang=en".
// templates/index.html enthält <meta name="csrf-token" content="…">.
// Das Token hängt an der Session des Browsers, der den Service Worker
// installiert hat. Vorgecacht landete es dauerhaft im Cache Storage –
// einem Speicher, der pro Herkunft geteilt wird und nicht pro Benutzer.
// Auf einem gemeinsam genutzten Gerät hätte der nächste Benutzer damit
// das Token einer fremden Session vorgefunden, und ein veraltetes Token
// ist zugleich die Ursache der bekannten CSRF-400-Fehler.
//
// Für den Offline-Betrieb wird die Startseite nicht gebraucht: der
// navigate-Zweig unten holt sie immer frisch aus dem Netz und fällt bei
// Bedarf auf /offline zurück. Diese Seite trägt kein Token.
const STATIC_ASSETS = [
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
    // Die Icons des Manifests. Sie ändern sich praktisch nie und sind
    // klein - Cache-First ist hier richtig.
    "/static/images/icon-192-v2.png",
    "/static/images/icon-512-v2.png",
    "/static/images/icon-maskable-512-v2.png",
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

    // Uebersetzungen: stale-while-revalidate.
    //
    // Bewusst VOR dem Navigationszweig und vor den statischen Dateien:
    // Zwei bestehende Sicherungstests pruefen textlich, dass zwischen
    // Navigationsbehandlung und Statikbehandlung KEIN cache.put steht
    // (Navigationsantworten tragen CSRF-Token und duerfen nie in einen
    // geteilten Cache). Diese Reihenfolge haelt beide Zusicherungen
    // unveraendert gueltig - und sie ist ohnehin die richtige, weil eine
    // JSON-Datei nie eine Navigation ist.
    if (REVALIDATE_PATHS.includes(url.pathname)) {
        event.respondWith(
            caches.open(CACHE_NAME).then((cache) => (
                cache.match(event.request).then((cached) => {
                    const fromNetwork = fetch(event.request).then((response) => {
                        // Dieselbe HTML-Sperre wie im Statikzweig. Diese
                        // Pfade liefern JSON, aber die Zusicherung "kein
                        // cache.put ohne vorherige HTML-Pruefung" soll
                        // ausnahmslos gelten - eine Fehlkonfiguration am
                        // Server darf kein tokenbehaftetes HTML in einen
                        // geteilten Cache legen.
                        const contentType = (response && response.headers
                            && response.headers.get("Content-Type")) || "";
                        if (contentType.includes("text/html")) return response;

                        if (response && response.status === 200
                            && response.type === "basic") {
                            cache.put(event.request, response.clone());
                        }
                        return response;
                    }).catch(() => cached || Response.error());

                    // Liegt etwas im Cache, wird es sofort ausgeliefert und
                    // die Erneuerung läuft daneben weiter.
                    return cached || fromNetwork;
                })
            ))
        );
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

                // HTML nie in den Cache legen. Auf dieser Herkunft trägt
                // HTML entweder ein sessiongebundenes CSRF-Token oder
                // benutzerbezogene Inhalte (Account-, Reset-, Verifikations-
                // seiten). Beides gehört nicht in einen Speicher, der die
                // Herkunft teilt und den Neustart überlebt.
                //
                // Statische Dateien – CSS, JS, JSON, Bilder – sind davon
                // nicht betroffen und werden weiterhin genauso gecacht.
                const contentType = response.headers.get("Content-Type") || "";
                if (contentType.includes("text/html")) {
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
