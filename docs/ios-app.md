# FootSim als iOS-App (Swift + WKWebView)

**Stand: Web-Vorbereitung abgeschlossen. Es existiert noch kein
Xcode-Projekt, keine Signierung und kein Build.**

Gegenstück zu `docs/android-twa.md`. Dieses Dokument beschreibt
ausschließlich, was im **Hauptprojekt** für iOS geändert wurde und warum.
Die native Hülle liegt getrennt unter
`C:\Users\elieb\Documents\DevProjects\FootSim-iOS`.

---

## 1. Warum eine eigene Swift-Hülle und nicht Capacitor oder PWABuilder

Dieselbe Ausgangslage wie bei Android: FootSim wird vom eigenen VPS
ausgeliefert, die App **ist** die Website. Ein Deployment ist sofort in
der App sichtbar, ohne Store-Review.

| Weg | Warum nicht |
|---|---|
| **Capacitor** | `server.url` ist laut offizieller Dokumentation **„not intended for use in production"**. Assets bündeln geht nicht — es gibt kein Build-Artefakt, das Jinja-Templates und Live-Daten ersetzt. |
| **PWABuilder-iOS** | Repository am **11.09.2025 archiviert**, read-only, laut README „100 % community driven". |

Auf iOS gibt es kein TWA-Äquivalent, deshalb eine schlanke eigene Hülle —
vier Swift-Dateien plus `Info.plist`.

---

## 2. Was sich im Hauptprojekt geändert hat

### 2.1 Plattformerkennung verallgemeinert

`templates/_platform_detect.html` — ein Include im `<head>`, das
`index.html` **und** `pdfmerge.html` einbinden. Bewusst keine zwei
Kopien: Auf der PDF-Seite entscheidet die Erkennung ueber den
Downloadweg, und auseinandergelaufene Kopien waeren dort ein
funktionaler Fehler.

Vorher war der Wert `'android'` fest verdrahtet. Jetzt entscheidet eine
**Allowlist**:

```js
var ERLAUBTE = { android: true, ios: true };
```

Reihenfolge der Erkennung:

1. `?platform=` — muss in `ERLAUBTE` stehen, sonst verworfen
2. `sessionStorage['footsim-platform']` — trägt über interne Navigation
3. User-Agent enthält `FootSim-iOS` — Rückfallweg

**Der User-Agent-Marker ist bewusst exakt** und keine Heuristik auf
„iPhone", „iPad" oder „Safari". Eine Heuristik würde jedes normale
mobile Safari als App erkennen — die Website verlöre dort ihre CTAs. Ein
E2E-Test (`test_normales_safari_wird_nicht_als_app_erkannt`) sichert das
mit einem echten Apple-User-Agent ab.

`sessionStorage` und **nicht** `localStorage`: App und Browser teilen
denselben Origin-Speicher; ein dauerhafter Vermerk liefe in den Browser
über.

### 2.2 Ausblendung der CTA-Gruppe

`static/style.css`:

```css
:root[data-platform="android"] .support,
:root[data-platform="ios"] .support { display: none; }
```

**Eine** Regel für beide Plattformen, bewusst nicht zwei. Zwei Regeln
könnten auseinanderlaufen, und dann erschiene in genau einer App etwas,
das dort nicht sein darf.

Für iOS ist das keine Vorsicht, sondern Pflicht: **App Store Review
Guideline 2.3.10** untersagt Namen und Verweise auf fremde Plattformen
und App-Marktplätze. In `.support` stehen ein Play-Store-Link und ein
Google-Groups-Link auf das Android-Testerprogramm — beide wären ein
Einreichungsblocker. Der PayPal-Link fällt unter dieselbe Regel.

`display: none` statt `visibility: hidden`, damit nichts per Tastatur
erreichbar bleibt **und** kein leerer Abstand im Hero zurückbleibt.

### 2.3 `viewport-fit=cover`

In `index.html` und `pdfmerge.html`. Ohne diesen Wert liefert
`env(safe-area-inset-*)` überall `0` — das Stylesheet rechnet an sechs
Stellen damit. Auf Android und im Desktop-Browser ändert der Wert nichts.

### 2.4 Native Brücke

`static/script.js`, Abschnitt „2b. NATIVE BRUECKE".

Zwei Kanäle über `window.webkit.messageHandlers`:

| Kanal | Nutzlast | Ausgelöst durch |
|---|---|---|
| `haptic` | `{ style: "light"\|"medium"\|"heavy" }` | Start einer Simulation |
| `share` | `{ title?, text?, url? }` | Knopf „Ergebnis teilen" im Ergebnisbereich |

Jeder Aufruf prüft die vollständige Kette (`window.webkit` →
`messageHandlers` → Kanal → `postMessage` als Funktion) und ist in
`try/catch` gefasst. Im Browser und in Android existiert das Objekt
nicht; es entsteht **kein** Fehler. Ein E2E-Test prüft genau das.

**Sicherheitsgrenze:** Die Brücke trägt ausschließlich Darstellungs- und
Komfortsignale. Weder Authentifizierung noch Autorisierung noch
Datenzugriff hängen an ihr oder an `data-platform`. Wer sie fälscht, löst
bestenfalls eine Vibration aus.

### 2.5 PDF-Download im iOS-Modus

`static/pdfmerge.js`. Der Browser holt das fertige PDF per `fetch` als
Blob und haengt eine `blob:`-URL an `<a download>`. In einer WKWebView
erzeugt das **keinen** `WKDownload` — es entsteht keine HTTP-Antwort, und
`blob:` ist ein reserviertes Schema.

Im iOS-Modus sendet `mergeUeberFormular()` deshalb ein echtes Formular an
dieselbe Route, in ein verstecktes gleichherkuenftiges iframe. Die Antwort
traegt `Content-Disposition: attachment`, und genau daran erkennt die
Huelle den Download.

Unveraendert: Route, `multipart/form-data`, CSRF (als Formularfeld statt
Header), Rate Limit, alle Serverlimits. **Eine** Anfrage, kein Base64,
keine PDF-Daten ueber die Bruecke. Browser und Android nehmen weiterhin
den Blob-Weg.

---

## 3. Der Teilen-Knopf

`#share-result-btn` steht im Ergebnisbereich, unter dem Spieltitel — dort,
wo das Ergebnis gerade entstanden ist. **Nicht im Hero.**

Beschriftung: `simulation.shareResult` — „Ergebnis teilen" / „Share result".

**Drei Bedingungen, alle notwendig** (`aktualisiereTeilenKnopf()`):

1. `istNativeHuelle()` — im Browser gibt es die Systemfunktion bereits
2. `nativerKanal("share") !== null` — ohne registrierten Kanal wäre der
   Knopf tot
3. ein Ergebnis liegt vor

Der Knopf trägt im Markup das `hidden`-Attribut und wird ausschließlich
von `renderResult()` freigegeben. `display: none` auf `[hidden]` ist
ausdrücklich gesetzt: `inline-flex` schlägt sonst die Browservorgabe, und
im verborgenen Zustand bliebe eine Lücke.

**Vor jeder neuen Simulation** ruft `runSimulation()` zuerst
`aktualisiereTeilenKnopf(null)`. Scheitert der Lauf, läuft
`renderResult()` nicht — ohne diesen Schritt bliebe das **vorige**
Ergebnis teilbar und würde unter dem neuen Spiel geteilt.

Der Listener ist **einmal** auf Modulebene registriert, nicht in
`renderResult()`. Sonst öffneten sich nach drei Simulationen drei Share
Sheets. Er liest `letztesTeilbaresErgebnis`, statt Daten einzuschließen.

**Inhalt** (aus `baueTeilenNutzlast()`, gebildet aus genau den
angezeigten Werten — keine zweite Berechnung):

```
Bundesliga: FC Bayern - RB Leipzig
FC Bayern 54.2% | Unentschieden 23.1% | RB Leipzig 22.7%
Simuliert mit FootSim – eine Wahrscheinlichkeitsverteilung, keine Vorhersage.
```

plus `window.location.origin` als Link. Der Hinweis ist bewusst neutral:
keine Erfolgszusage, kein Tipp, keine ML-Behauptung. Übertragen werden
ausschließlich die drei Felder `title`, `text`, `url` — keine
Kontodaten, Tokens oder internen IDs.

---

## 4. Was unverändert bleibt

* **Android:** Der Erkennungszweig ist inhaltlich unverändert; `android`
  steht weiterhin in der Allowlist und `sessionStorage` verhält sich
  gleich. Die bestehenden Android-Tests laufen unverändert durch.
* **Normaler Browser:** Ohne Parameter, ohne `sessionStorage`-Eintrag und
  ohne den exakten User-Agent-Marker passiert nichts. Kein Attribut, kein
  verändertes Layout.
* **Backend, Sitzungen, CSRF, Sprachwahl, Themes:** nicht berührt.

---

## 5. Tests

| Fall | Ort |
|---|---|
| Normale Website zeigt alle CTAs | `test_browser_smoke.py` |
| Android-Modus blendet aus | `test_browser_smoke.py` |
| iOS-Modus blendet aus | `test_browser_smoke.py` |
| iOS-Modus ohne leeren Abstand | `test_browser_smoke.py` |
| Kein Play-Store-/Groups-/PayPal-Link sichtbar | `test_browser_smoke.py` |
| Normales Safari **nicht** als App erkannt | `test_browser_smoke.py` |
| User-Agent-Marker schaltet iOS | `test_browser_smoke.py` |
| Unbekannter Plattformwert verworfen | `test_browser_smoke.py` |
| Brücke wirft im Browser nicht | `test_browser_smoke.py` |
| Brücke validiert Nutzlasten | `test_browser_smoke.py` |
| Allowlist, UA-Marker, `viewport-fit`, CSS-Regel | `test_hero_cta.py` |
| PDF-Weiche, Formularaufbau, CSRF, Dateien | `test_ios_pdf_und_share.py`, `test_browser_smoke.py` |
| Teilen-Knopf: Sichtbarkeit, Nutzlast, zweite Simulation | `test_browser_smoke.py` |
| Service Worker erfasst alle plattformrelevanten Dateien | `test_hero_cta.py` |

Die Browsertests laufen mit `python -m pytest tests/ -q --e2e -m e2e`.
