# Store-Privacy-Angaben für FootSim

Grundlage zum Ausfüllen von **Google Play Data Safety** und **Apple App
Privacy**. Kein Store-Listing, keine Einreichung — nur die belegte
Faktenlage.

Jede Zeile ist als **[CODE]** oder **[MANUELL]** gekennzeichnet:

- **[CODE]** — im Repository verifiziert, Fundstelle angegeben
- **[MANUELL]** — muss im jeweiligen Store-Portal angegeben oder von
  Elie entschieden werden; steht nicht im Code

Stand: August 2026 · geprüfter Commit-Stand: siehe `git log`

---

## 1. URLs

| Zweck | URL | Status |
|---|---|---|
| Datenschutzerklärung | `https://footsim.de/datenschutz` | **[CODE]** `app.py` → `datenschutz()` |
| Account-Löschung (öffentlich) | `https://footsim.de/account-loeschen` | **[CODE]** `app.py` → `account_loeschen()` |
| Account-Löschung (Alias, EN) | `https://footsim.de/delete-account` | **[CODE]** zweite Route auf dieselbe Seite |
| Impressum | `https://footsim.de/impressum` | **[CODE]** |
| Support-Kontakt | `eliebusiness0@gmail.com` | **[CODE]** `templates/impressum.html` |

Beide Rechtsseiten sind **ohne Login** erreichbar und folgen der
Sprachwahl (DE/EN) über den bestehenden `locale`-Mechanismus.

---

## 2. Erhobene Datenarten

> Die Antwort „Es werden keine Daten erhoben“ ist **falsch** und darf in
> keinem Store-Formular angekreuzt werden — FootSim verarbeitet Konten,
> E-Mail-Adressen und Favoriten.

### 2.1 Serverseitig gespeichert (nur mit Konto)

| Datenart | Feld | Zweck | Store-Kategorie | Beleg |
|---|---|---|---|---|
| Name | `first_name`, `last_name` | Kontoanzeige, Ansprache | Personal info → Name | **[CODE]** `src/models/user.py` |
| E-Mail | `email` | Anmeldung, Verifikation, Passwort-Reset | Personal info → Email address | **[CODE]** `src/models/user.py` |
| Anmeldedaten | `password_hash` (Argon2) | Authentifizierung | Personal info → Other (Credentials) | **[CODE]** `User.set_password()` |
| Konto-ID | `id` (UUIDv7) | interne Kennung | Identifiers → User ID | **[CODE]** `src/models/user.py` |
| Kontostatus | `is_verified`, `verified_at`, `profile_onboarding_completed`, `sessions_valid_after`, `created_at`, `updated_at` | Betrieb, Sicherheit | App activity / App info | **[CODE]** `src/models/user.py` |
| Spracheinstellung | `preferred_language` | Anzeige | App info and performance | **[CODE]** `src/models/user.py` |
| Lieblingsverein | `team_id`, `source`, `team_name`, `crest_url`, `created_at` | Personalisierung (Wappen, Live-Sortierung) | App activity → App interactions | **[CODE]** `src/models/favorite.py` |

**Ohne Konto** wird serverseitig nichts davon gespeichert. **[CODE]**

`favorite_players` existiert als Tabelle, wird aber von keinem Codepfad
beschrieben — daher **nicht** als erhobene Datenart deklarieren.
**[CODE]** `src/models/favorite.py`

### 2.2 Technisch anfallend

| Datenart | Inhalt | Store-Kategorie | Beleg |
|---|---|---|---|
| Server-Logs | IP-Adresse, Zeitstempel, URL, Statuscode, User-Agent, ggf. Referrer | App info and performance → Diagnostics | **[CODE]** nginx/Gunicorn Standardbetrieb |

Aufbewahrungsdauer der Logs: **[MANUELL]** — im Repository ist keine
Rotationsregel hinterlegt; auf dem VPS zu prüfen und danach hier und in
der Datenschutzerklärung nachzutragen.

### 2.3 Nur auf dem Gerät (verlässt das Gerät nicht)

Dieses Dokument ist die technische Innensicht für das Ausfüllen der
Store-Formulare — hier stehen die echten Schlüsselnamen. Die
**Datenschutzerklärung nennt bewusst nur die Kategorie** aus der ersten
Spalte: interne Schlüsselnamen helfen dort niemandem und veralten bei
jeder Umbenennung. Die Spalte hält beide Sichten zusammen, damit sie
nicht auseinanderlaufen.

| Kategorie (Rechtstext) | Schlüssel | Technik | Zweck | Dauer | Beleg |
|---|---|---|---|---|---|
| Anmeldesitzung | `session` | Cookie, HttpOnly, SameSite=Lax, Secure | Anmeldung + Schutz vor gefälschten Formularen | ≤ 30 Tage | **[CODE]** `app.py` |
| Spracheinstellung | `footsim_lang` | Cookie + localStorage | Sprachwahl | Cookie 1 Jahr, localStorage bis zum Löschen | **[CODE]** `src/i18n.py`, `static/script.js` |
| Darstellung | `theme` | localStorage | hell/dunkel | bis zum Löschen | **[CODE]** `static/script.js` |
| Einrichtungsfortschritt | `footsim_onboarding` | localStorage | Fortschritt der einmaligen Einrichtung | bis zum Löschen — der Schlüssel bleibt nach Abschluss mit dem Stand `complete` bestehen | **[CODE]** `static/script.js` |
| vorübergehende E-Mail-Information | `unverified_email` | localStorage | Komfort beim erneuten Senden der Bestätigungsmail | bis zur Abmeldung oder Kontolöschung (`clearAccountLocalData()`) | **[CODE]** `static/script.js` |
| Offline-App-Dateien | `footsim-vNN` | Cache Storage | PWA-Offline-Shell, **kein HTML**, keine Konto-Antworten | bis zur nächsten Version | **[CODE]** `static/sw.js` |

Nicht vorhanden, im Code verifiziert: **kein** `sessionStorage`, **keine**
IndexedDB, **keine** Push-Benachrichtigungen, **keine** Analytics-,
Werbe-, Crash- oder Tracking-SDKs. **[CODE]**

---

## 3. Weitergabe an Dritte

| Empfänger | Was | Wie | Beleg |
|---|---|---|---|
| Hostinger (VPS) | alles serverseitig Gespeicherte | Auftragsverarbeiter (Hosting) | **[CODE]** Deployment |
| Resend, Inc. | E-Mail-Adresse + Nachrichteninhalt | Auftragsverarbeiter (Mailversand) | **[CODE]** `src/utils/mail.py` |
| football-data.org | **keine Nutzerdaten** | Abruf durch den Server | **[CODE]** `src/api/league_api.py` |
| API-Football / API-Sports | **keine Nutzerdaten** | Abruf durch den Server | **[CODE]** `src/api/apisports_api.py` |
| `crests.football-data.org`, `media.api-sports.io` | **IP-Adresse, Zeitpunkt, User-Agent** | **direkter Abruf durch den Browser** beim Anzeigen von Wappen | **[CODE]** `static/script.js` |

Die letzte Zeile ist die einzige automatische Drittanbieter-Übertragung
und in beiden Store-Formularen als solche zu berücksichtigen.

PayPal, Instagram und TikTok sind **reine Links** mit
`rel="noopener noreferrer"` — keine eingebetteten Inhalte, keine
Übertragung ohne Klick. **[CODE]** `templates/index.html`

---

## 4. Sicherheit

| Frage | Antwort | Beleg |
|---|---|---|
| Verschlüsselung bei Übertragung | **Ja** — HTTPS, HSTS aktiv | **[CODE]** nginx |
| Passwortspeicherung | Argon2-Hash, nie Klartext | **[CODE]** `src/models/user.py` |
| Datenbank öffentlich erreichbar | **Nein** — nur Loopback | **[CODE]** verifiziert im Deployment |
| Kann der Nutzer die Löschung verlangen | **Ja** — in der App und öffentlich dokumentiert | **[CODE]** `src/api/auth.py`, `/account-loeschen` |

---

## 5. Account-Löschung (Google-Play-Pflichtangabe)

- **In der App:** Konto-Bereich → „Account löschen“ → Bestätigung mit
  aktuellem Passwort. **[CODE]** `src/api/auth.py` → `delete_account()`
- **Öffentlich:** `https://footsim.de/account-loeschen`
- **Gelöscht wird:** Konto mit allen Profildaten sowie der
  Lieblingsverein (Cascade-Delete). **[CODE]** `User.favorite_teams`
  mit `cascade='all, delete-orphan'`
- **Restaufbewahrung:** Die Datenbank wird täglich automatisch gesichert;
  die Sicherungen rotieren nach 14 Tagen und werden danach automatisch
  entfernt. Ein Wiederherstellungstest wurde erfolgreich durchgeführt.
  Sicherungen dienen ausschließlich dem Notfall, nicht dem laufenden
  Betrieb. **[CODE]** `ops/backup_footsim_db.sh`
  — deckungsgleich mit Abschnitt 9 der Datenschutzerklärung.

---

## 6. Cookie-Einwilligung

**Kein Consent-Banner erforderlich.** Es werden ausschließlich technisch
notwendige Cookies sowie vom Nutzer selbst gewählte Einstellungen
gespeichert; kein Tracking, keine Werbung, kein Profiling
(§ 25 Abs. 2 TDDDG). Im Code verifiziert. **[CODE]**

Ein Banner würde erst nötig bei: Analytics, Crash-Reporting mit
Gerätekennungen, Werbung, eingebetteten Social-Media-Inhalten, externen
Fonts/CDNs oder Push-Benachrichtigungen.

---

## 7. Offene Punkte — [MANUELL]

Diese Angaben lassen sich **nicht** aus dem Code ableiten:

1. **Zielgruppe / Altersfreigabe** — FootSim nicht vorschnell als
   Kinder-App positionieren; sonst greift die Families Policy.
2. **Log-Aufbewahrungsdauer** — auf dem VPS festlegen und dann in
   Datenschutzerklärung und Abschnitt 2.2 eintragen.
3. **AV-Verträge** mit Hostinger und Resend sowie die Grundlage für die
   Übermittlung in die USA (Resend).
4. **Marken- und Logorechte** für Vereinswappen in einer öffentlich
   vertriebenen Store-App. Ein API-Abo ist keine Markenlizenz; ein
   Disclaimer ersetzt keine Lizenz.
5. **PayPal-Link** im Store-Build — Store-Regeln zu externen Zahlungen
   prüfen; Empfehlung: im Store-Build ausblenden.
6. **DSA-Trader-Status** (Apple, EU) und **Export Compliance**.
7. **Android-/iOS-Paket** existiert noch nicht — kein AAB, kein Xcode-
   Projekt, kein `assetlinks.json`, kein `PrivacyInfo.xcprivacy`.
8. **Apple Sign in with Apple** — derzeit nicht erforderlich, da nur
   eigenes E-Mail/Passwort-Login. Bei späterem Social-Login neu bewerten.
9. **App Tracking Transparency** — derzeit nicht erforderlich, da kein
   Tracking.
