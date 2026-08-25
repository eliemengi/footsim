# FootSim als Android-App (Trusted Web Activity)

**Stand: Web-Vorbereitung abgeschlossen. Es existiert noch kein
Android-Projekt, kein Keystore und keine AAB.**

Dieses Dokument beschreibt, wie aus der bestehenden PWA eine
Play-Store-App wird — und warum die Entscheidungen so gefallen sind.

---

## 1. Warum Bubblewrap/TWA und nicht Capacitor

FootSim wird vom eigenen VPS ausgeliefert. Eine Trusted Web Activity ist
ein dünner Android-Container, der `https://footsim.de` im Vollbild öffnet.
Die App **ist** die Website.

| Kriterium | Bubblewrap/TWA | Capacitor |
|---|---|---|
| Auslieferung vom VPS | Kernfall | braucht `server.url` |
| Neue Auswertungen ohne neue AAB | **sofort sichtbar** | nur über `server.url` |
| Produktionstauglichkeit dieses Wegs | vorgesehener Einsatzzweck | `server.url` ist laut Doku **nicht für Produktion** gedacht |
| Native Gerätefunktionen | keine vorgesehen | Stärke, hier ungenutzt |
| AAB-Größe | ~1–2 MB | ~5–10 MB |

Den Ausschlag gibt der zweite Punkt. Bei Capacitor gäbe es nur zwei Wege:
Assets bündeln — dann bräuchte **jede** Modelländerung eine neue AAB samt
Play-Review — oder `server.url`, was die Dokumentation für die Produktion
ausschließt. TWA hat dieses Dilemma nicht: Ein Deployment auf dem VPS ist
sofort in der App sichtbar.

Da keine nativen Gerätefunktionen vorgesehen sind, zahlt Capacitors
eigentliche Stärke auf nichts ein.

---

## 2. Eckdaten

| | |
|---|---|
| Paket-ID | `de.footsim.app` — **nach Veröffentlichung unveränderlich** |
| Produktionsdomain | `https://footsim.de` |
| Manifest-URL | `https://footsim.de/manifest.json` |
| Manifest `start_url` / `scope` | `/` |
| **Bubblewrap-Start-URL** | `/?platform=android` |
| Asset Links | `https://footsim.de/.well-known/assetlinks.json` |

### Warum start_url und Bubblewrap-Start-URL verschieden sind

Das ist Absicht und der wichtigste Punkt dieses Dokuments.

- Das **Manifest** sagt `start_url: "/"`. Ohne `?lang=` entscheidet der
  Server bei jedem Aufruf neu: `?lang=` schlägt Cookie schlägt
  `Accept-Language`. Ein deutsches System bekommt Deutsch, jedes andere
  Englisch. **Es wird keine Sprache in die App eingebrannt.**
- **Bubblewrap** bekommt beim `init` ausdrücklich `/?platform=android`.
  Nur dieser Parameter schaltet den Android-Modus, der den
  PayPal-Unterstützungslink ausblendet.

Würde `platform=android` im Manifest stehen, verschwände der Link auch im
normalen Browser. Würde er in Bubblewrap fehlen, erschiene er in der App.

Der Modus wird in `sessionStorage` gemerkt, **nicht** in `localStorage`:
Die TWA und ein normaler Chrome-Tab teilen sich denselben
Origin-Speicher, ein dauerhafter Vermerk würde in den Browser
überlaufen.

---

## 3. Benötigte Software

| Werkzeug | Zweck |
|---|---|
| Node.js LTS (≥ 18) | Bubblewrap CLI |
| `@bubblewrap/cli` | `npm i -g @bubblewrap/cli` |
| JDK 17 | Android-Build |
| Android SDK / Build-Tools | Bubblewrap installiert Fehlendes teils selbst |

Node fehlt derzeit im lokalen PATH. Es wird ohnehin auch für
`node --check` in der CI gebraucht.

---

## 4. Signierung

**Play App Signing verwenden** (Standard für neue Apps).

Es gibt **zwei** Schlüssel, und sie werden regelmäßig verwechselt:

| | Upload-Key | App-Signing-Key |
|---|---|---|
| Wer hält ihn | **Sie**, lokal | **Google**, in der Play Console |
| Wofür | signiert die AAB beim Hochladen | signiert das, was auf den Geräten landet |
| Bei Verlust | ersetzbar über den Google-Support | Totalverlust |
| **Für `assetlinks.json`** | nein | **ja — dieser Fingerabdruck zählt** |

> **Die klassische Falle:** Wer den Upload-Fingerabdruck in
> `assetlinks.json` einträgt, bekommt dauerhaft eine Adressleiste und
> sucht den Fehler an der falschen Stelle. Während der Testphase trägt
> man am besten **beide** ein — die Route unterstützt mehrere Werte,
> kommagetrennt.

### Keystore-Regeln

- Keystore **außerhalb** des Repositorys anlegen, z. B.
  `%USERPROFILE%\.footsim-keys\`.
- Passwörter in einen Passwortmanager. Niemals in `gradle.properties`,
  niemals in eine Datei des Projekts.
- **Backup an einem zweiten Ort**, offline. Ohne Upload-Key ist der
  nächste Upload nur über den Google-Support möglich.
- `.gitignore` schließt `*.jks`, `*.keystore`, `keystore.properties`,
  `signing.properties` und `twa-manifest.json` bereits aus.

Der SHA-256-**Fingerabdruck** ist dagegen **kein Geheimnis** — er steht in
jeder installierten App. Er kommt zur Laufzeit aus
`ANDROID_ASSETLINKS_SHA256` (siehe `.env.example`), damit er nicht im
Code steht und ohne Deployment wechseln kann.

---

## 5. Reihenfolge bis zum geschlossenen Test

```
1.  Webfix          Manifest, Icons, Android-Modus, History, SW   [erledigt]
2.  Tests           volle Suite, JS-Parser, Browser-Smoke          [erledigt]
3.  GitHub/CI       pushen, CI grün abwarten
4.  VPS             deployen; danach prüfen:
                      https://footsim.de/manifest.json
                      → scope "/", start_url "/", drei Icons
                      https://footsim.de/static/images/icon-512.png
5.  Bubblewrap      bubblewrap init \
                      --manifest https://footsim.de/manifest.json
                    → Paket-ID de.footsim.app
                    → Start-URL auf /?platform=android setzen
                    → Upload-Keystore außerhalb des Repos anlegen
                    bubblewrap build
6.  Interner Test   AAB in der Play Console hochladen,
                    Play App Signing aktivieren,
                    SHA-256 des App-Signing-Keys kopieren
7.  Asset Links     ANDROID_ASSETLINKS_SHA256 auf dem VPS setzen,
                    Dienst neu starten, dann prüfen:
                      https://footsim.de/.well-known/assetlinks.json
                    → 200, application/json, keine Weiterleitung,
                      package_name de.footsim.app
                    App neu installieren → Vollbild ohne Adressleiste
8.  Closed Test     erst wenn Schritt 7 nachweislich sitzt
```

**Schritt 7 kommt zwingend nach Schritt 6** — vorher existiert der
Fingerabdruck des App-Signing-Keys nicht.

### Erst interner Test, nicht sofort Closed Test

Der interne Test ist sofort verfügbar, braucht keine Prüfung und keine
Mindestzahl an Testern. Er ist der richtige Ort, um die Asset Links, den
Login und die Zurück-Taste zu prüfen.

Der **geschlossene Test** verlangt für den späteren
Produktionszugang **mindestens 12 Tester über 14 zusammenhängende Tage**.
Diese Frist beginnt neu, wenn die Zahl unterschritten wird — deshalb erst
starten, wenn die App wirklich funktioniert.

---

## 6. Prüfplan im internen Test

| # | Prüfung | Erwartung |
|---|---|---|
| 1 | App öffnen | Vollbild, **keine Adressleiste** |
| 2 | Deutsches Systemlocale | Oberfläche auf Deutsch |
| 3 | Englisches Systemlocale | Oberfläche auf Englisch |
| 4 | Sprachumschalter in der App | wechselt und bleibt |
| 5 | Registrierung | Bestätigungsmail kommt an |
| 6 | Login und Neustart | Sitzung bleibt bestehen |
| 7 | **PayPal-Knopf** | **nicht sichtbar** |
| 8 | Dieselbe Seite in Chrome | **PayPal sichtbar** |
| 9 | Bereich wechseln, Zurück | vorheriger Bereich, App bleibt offen |
| 10 | Zurück im ersten Bereich | App schließt (korrekt) |
| 11 | PDF Merge | Datei landet in den Downloads |
| 12 | Kontakt, Feedback, Impressum, Datenschutz, Account löschen | alle erreichbar |
| 13 | Flugmodus | Offline-Seite statt Fehlerseite |
| 14 | Zurück aus dem Flugmodus | App lädt normal weiter |
| 15 | Neues Deployment auf dem VPS | nach kurzer Zeit ohne App-Update sichtbar |

Prüfung 15 belegt den eigentlichen Grund für TWA: `script.js` und
`style.css` laufen seit Cacheversion v33 mit stale-while-revalidate.

---

## 7. Was bewusst offen bleibt

- **Paket-ID** ist mit `de.footsim.app` festgelegt, aber noch nicht
  registriert. Nach der ersten Veröffentlichung unveränderlich.
- **Data Safety** in der Play Console muss E-Mail, Passwort und
  Nutzungsdaten deklarieren. Nicht aus dem Code ableitbar.
- **PayPal in der Web-Fassung** bleibt bestehen. Nur die App blendet ihn
  aus. Ob Google den Link auf der Website beanstandet, ist nicht
  vorhersagbar — er ist dort aber kein Bestandteil der App.
- **Datenschutz-URL** (`/datenschutz`) und **Account-Löschung**
  (`/delete-account`) existieren und müssen in der Console eingetragen
  werden.
