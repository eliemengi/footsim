# Lokale Security-Härtung — Abschlussbericht

**Datum:** 2026-08-21
**Umfang:** ausschließlich lokal. Kein Commit, kein Push, kein Pull, kein Deployment, kein SSH-Zugriff, keine Änderung an systemd/nginx/Produktionsdaten, keine Schlüsselrotation.
**Testergebnis:** 1898 passed, 1 skipped (vorher: 1881 passed, 1 failed, 1 skipped)

---

## 0. Wichtiger Hinweis zum Auftragsumfang

Der übergebene GO-Auftrag **brach nach der Zeile mit dem lokalen Pfad ab**. Der Text endete mit:

```
Lokaler Pfad:
C:\Users\elieb\Documents\DevProjects\FootSim
```

Die dort angekündigten **Phasen 2 bis 10 sind nie angekommen**. Bearbeitet wurde deshalb, was inhaltlich eindeutig bestimmbar war:

- die vier verifizierten Befunde des externen Audits (B1–B4),
- der ausdrücklich erlaubte Punkt „Abhängigkeiten kontrolliert aktualisieren",
- die daraus entstandenen Folgebefunde (B5).

Was in den fehlenden Phasen stand, ist **nicht** abgearbeitet. Für eine vollständige Erledigung müssten diese Phasen nachgereicht werden.

---

## 1. Befundübersicht

| ID | Befund | Schwere | Status |
|----|--------|---------|--------|
| B1 | Rate-Limiter fest auf `memory://`, nginx-Referenz zeigt Schutz als inaktiv | mittel | behoben |
| B2 | Datenbank-Zugangsdaten im Klartext in getrackter `docker-compose.yml` | hoch | behoben |
| B3 | Timing-Seitenkanal und Statuscode-Leck bei Passwort-Reset / Verifizierung | mittel | behoben |
| B4 | PDF-Merge ohne Obergrenze für die Gesamtseitenzahl | mittel | behoben |
| B5 | Pillow-Decoder-Angriffsfläche: Endungs-Allowlist filtert nur den Dateinamen | **hoch** | gemindert |
| B6 | Python 3.9 ist End-of-Life und blockiert fünf verfügbare Sicherheitsfixes | **hoch** | **offen — Betrieb** |
| E-4 | Registrierung verrät per HTTP 409 die Existenz einer Adresse | mittel | **offen — Produktentscheidung** |

---

## 2. B1 — Rate Limiting

### Befund
`src/models/extensions.py` setzte `storage_uri="memory://"` fest verdrahtet. In `ops/nginx-footsim.conf.reference` waren **alle fünf** `limit_req`-Direktiven auskommentiert.

### Korrektur am Audit
Der externe Prüfer hat nur das Repository gelesen und daraus geschlossen, Rate Limiting sei nicht aktiv. **Das ist für die Produktion falsch.** Die nginx-Zonen laufen dort und wurden gemessen — zwölf schnelle Auth-Requests ergaben `400 400 400 400 400 400 429 429 …`. Der Schutz existiert; die *Dokumentation* war irreführend.

### Umsetzung
- `RATELIMIT_STORAGE_URI` liest jetzt `FOOTSIM_RATELIMIT_STORAGE_URI`, Fallback bleibt `memory://`. Ein gemeinsamer Speicher (z. B. Redis) ist damit ohne Codeänderung nachrüstbar, aber **nicht Pflicht** — für den aktuellen Betrieb wäre Redis zusätzliche Angriffs- und Betriebsfläche ohne Gegenwert.
- Die Referenzdatei zeigt die Direktiven jetzt **aktiv**, weil sie es in Produktion sind. Ergänzt wurde der Hinweis, dass `sites-enabled/footsim` auf diesem Server **kein Symlink** ist — eine Änderung in `sites-available/` wirkt dort nicht automatisch.

### Grenze der Maßnahme
`memory://` zählt weiterhin **pro Gunicorn-Worker**. Bei `-w 3` existiert jedes Flask-Limit dreifach und ist nach jedem Neustart weg. Die harte, workerübergreifende und neustartfeste Grenze ist und bleibt nginx.

---

## 3. B2 — Datenbank-Zugangsdaten

### Befund
`docker-compose.yml:8` enthielt das Passwort im Klartext in einer **getrackten** Datei. `.env.example` wiederholte dieselbe Kombination.

### Umsetzung
Alle drei Werte kommen ausschließlich aus der Umgebung, **ohne Fallback**:

```yaml
POSTGRES_USER: ${POSTGRES_USER:?POSTGRES_USER fehlt - siehe .env.example}
```

Die `:?`-Form ist bewusst gewählt: fehlt eine Variable, bricht `docker compose` mit klarer Meldung ab. Ein `:-`-Fallback wäre genau das alte Problem in neuer Schreibweise.

### Bestandsschutz
Die Werte wurden in der bereits ignorierten lokalen `.env` ergänzt und **aus der vorhandenen `DATABASE_URL` abgeleitet** — identische Werte, damit der laufende Container und das bestehende `pgdata`-Volume unverändert weiterlaufen. Es wurde kein Volume gelöscht oder neu erstellt. Die Werte wurden zu keinem Zeitpunkt ausgegeben; die Konsistenz wurde nur über einen SHA-256-Vergleich geprüft.

### Nachtrag
Der ursprüngliche Erklärkommentar in `docker-compose.yml` zitierte das alte Passwort im Klartext — dasselbe Problem eine Ebene tiefer. Der Wert steht ohnehin noch in der Git-Historie und gehört nicht zusätzlich in den aktuellen Stand; das Literal wurde entfernt.

> **Offen für den Betrieb:** Das alte Passwort ist über die Git-Historie weiterhin lesbar. Wer Zugriff auf das Repository hatte, kennt es. Ein Wechsel des lokalen Entwicklungspassworts ist ratsam — für die Produktionsdatenbank gilt das nur, falls dort je derselbe Wert verwendet wurde.

---

## 4. B3 — Timing-Seitenkanal und User Enumeration

### Befund
`/api/auth/forgot-password` antwortete bewusst immer generisch, rief den Versand aber **nur bei existierendem Konto** auf. Da der Versand ein blockierender HTTPS-POST an Resend ist (`timeout=10`), verriet die **Antwortzeit** das Ergebnis. Die generische Meldung war damit wirkungslos.

Schwerwiegender noch: `/api/auth/resend-verification` lieferte bei Providerfehlern `503` mit `status="email_failed"`. Dieser Zweig war **per Definition nur erreichbar, wenn das Konto existierte UND unbestätigt war** — der Statuscode allein verriet die Antwort, ganz ohne Zeitmessung.

### Umsetzung
Neue Funktion `send_in_background()` in `src/utils/mail.py`: der Versand läuft in einem Daemon-Thread mit eigenem App-Kontext, Fehler werden dort geloggt und **nie** an den Aufrufer gereicht. Der 503-Zweig in `resend_verification()` ist entfernt.

Bewusst ein Thread statt Celery/Redis: für einige Mails am Tag wäre eine Task-Queue zusätzliche Betriebsfläche ohne Mehrwert. Der Preis ist ehrlich zu benennen — der Aufrufer erfährt das Versandergebnis nicht mehr synchron. Es steht im Serverlog.

### Nachweis
Der Regressionstest misst echte Zeiten. Zur Absicherung wurde die Regression simuliert (`send_in_background` synchron ausgeführt):

```
SYNCHRON: bekannt=0.425s unbekannt=0.007s diff=0.418s
```

Bei einer Schwelle von 0,2 s hätte der Test die Regression zuverlässig erkannt. Der Test ist damit nachweislich wirksam und kein Selbstläufer.

### Angepasster Bestandstest
`test_resend_verification_failure` prüfte genau den entfernten 503-Zweig — die Assertion kodierte die Schwachstelle selbst. Der Test wurde **nicht gelöscht und nicht übersprungen**, sondern auf den korrigierten Vertrag umgestellt (`test_resend_verification_failure_stays_generic`), mit der Begründung im Docstring. Ergänzt wurde ein zweiter Test, der bekannte und unbekannte Adresse auf **identische Antwort** prüft.

### Bewusst nicht geändert
`register()` versendet weiterhin synchron und meldet `status="email_failed"`. Das ist hier kein Leck: die Route verrät die Existenz einer Adresse ohnehin offen per 409 (siehe E-4), es gibt also kein Geheimnis zu schützen — und der Nutzer erfährt zu Recht, dass sein Konto zwar angelegt wurde, die Mail aber nicht ankam. Der Nachteil bleibt, dass ein Worker für die Dauer des Providerzugriffs blockiert.

---

## 5. B4 — PDF-Merge, Seitenbudget

### Befund
`app.py` maß die Gesamtseitenzahl (`total_pages = len(writer.pages)`), **begrenzte sie aber nie**. `MAX_CONTENT_LENGTH` (50 MB) deckelt nur die übertragene Datenmenge, nicht den Rechenaufwand: eine stark komprimierte PDF-Bombe bleibt weit darunter und enthält trotzdem Zehntausende Seiten. Bei drei Workern genügen wenige solcher Requests für einen Totalausfall.

### Umsetzung
`PDF_MAX_TOTAL_PAGES = 1500`, geprüft **vor** dem teuren `writer.append(reader)`:

```python
if len(writer.pages) + len(reader.pages) > PDF_MAX_TOTAL_PAGES:
    return jsonify({"error": f"Zu viele Seiten insgesamt (Maximum {PDF_MAX_TOTAL_PAGES})."}), 400
```

`len(reader.pages)` liest nur den Seitenbaum, nicht die Seiteninhalte — die Prüfung ist billig, das Anhängen wird bei Überschreitung gar nicht erst erreicht. Ein Test sichert die Reihenfolge ab, nicht nur die Existenz der Konstante.

---

## 6. B5 — Pillow-Decoder-Angriffsfläche (neuer Befund)

Dieser Befund entstand erst durch den Abhängigkeits-Check und ist der schwerwiegendste der Runde.

### Befund
`PDF_ALLOWED_EXTENSIONS` filtert nur den **Dateinamen**. `Image.open()` bestimmt das Format dagegen am **Inhalt** und wählt danach das Plugin. Eine Datei namens `urlaub.png`, die in Wahrheit FITS-, GD- oder JPEG2000-Daten enthält, landet also trotz Allowlist im jeweiligen Decoder. Die Endung schützt nichts.

Das ist relevant, weil `pip-audit` für Pillow 11.3.0 **22 offene Advisories** meldet. Nach Prüfung gegen den tatsächlichen Code sind vier davon erreichbar:

| Advisory | Decoder | Wirkung |
|---|---|---|
| PYSEC-2026-2250 | FITS | Dekompressionsbombe, unbegrenzter Speicher |
| PYSEC-2026-2256 | GD | Dekompressionsbombe |
| PYSEC-2026-3496 | JPEG2000 | Heap-Fehler in `Jpeg2KDecode.c` |
| PYSEC-2026-3493 | raw/mmap | greift, wenn **aus einem Dateinamen** geöffnet wird — genau der Fall hier |

Die übrigen 18 verlangen APIs, die FootSim nicht aufruft (`ImageCms`, `RankFilter`, TGA-Save, `ImageShow`, PCF-/BDF-Fonts, Pillows PDF-Parser).

### Warum kein Upgrade
Alle vier sind erst ab Pillow 12.1.1 bzw. 12.3.0 behoben. **Pillow 12 verlangt Python ≥ 3.10.** Unter Python 3.9 ist 11.3.0 das Maximum — ein Upgrade ist schlicht nicht installierbar.

### Umsetzung
Die einzige verfügbare Minderung ist, die Decoder gar nicht erst zuzulassen:

```python
PDF_ALLOWED_IMAGE_FORMATS = ["JPEG", "PNG"]
...
with Image.open(image_path, formats=PDF_ALLOWED_IMAGE_FORMATS) as image:
```

`formats=` begrenzt, welche Plugins Pillow überhaupt ausprobiert.

### Nachweis
Mit einer minimalen, gültigen FITS-Datei empirisch geprüft:

```
ohne formats=: GEOEFFNET -> FITS (10, 10)
mit  formats=: ABGEWIESEN -> UnidentifiedImageError
```

Vier Tests sichern das ab: dass Pillow die Fremddatei ohne die Einschränkung tatsächlich öffnet (die Gefahr ist real, nicht theoretisch), dass `pdf_convert_image` sie abweist, dass die Abweisung auch über die echte HTTP-Route greift, und als Gegenprobe, dass ein echtes PNG weiterhin durchgeht.

> Das ist eine **Minderung, keine Behebung**. Die verwundbare Bibliothek bleibt installiert. Fällt die Einschränkung je weg, ist die Lücke sofort wieder offen.

---

## 7. B6 — Python 3.9 ist End-of-Life (offen)

Die Laufzeit ist **Python 3.9.13**. Python 3.9 erhält keine Sicherheitspatches mehr. Das ist keine Formalie: für **fünf** gemeldete Schwachstellen existiert bereits eine korrigierte Version, die sich auf 3.9 **nicht installieren lässt**.

| Paket | installiert | Fix ab | Blocker |
|---|---|---|---|
| pillow | 11.3.0 | 12.1.1 / 12.3.0 | benötigt ≥ 3.10 |
| urllib3 | 2.6.3 | 2.7.0 | benötigt ≥ 3.10 |
| requests | 2.32.5 | 2.33.0 | benötigt ≥ 3.10 |
| python-dotenv | 1.2.1 | 1.2.2 | benötigt ≥ 3.10 |
| click | 8.1.8 | 8.3.3 | benötigt ≥ 3.10 |

**Der EOL-Interpreter ist damit die Ursache, nicht die einzelnen Pakete.** Solange er steht, ist jede weitere Härtung an diesen Stellen Umgehung statt Behebung — und die Liste wird mit jeder Woche länger.

Von den fünf ist nach heutiger Prüfung nur Pillow erreichbar (jetzt gemindert). `urllib3` ist grenzwertig: die Dekompressionsbombe betrifft Antworten der externen Fußball-APIs. `requests`, `python-dotenv` und `click` betreffen Funktionen, die FootSim nicht aufruft. **„Nicht erreichbar" ist aber eine Momentaufnahme** — sie kippt mit der nächsten Codeänderung.

**Empfehlung:** Python 3.12 auf dem VPS, danach die fünf Pakete anheben und die Deckelung in `requirements.txt` entfernen. Das ist ein eigener, getesteter Vorgang und gehört nicht in dasselbe Deployment wie diese Änderungen.

---

## 8. Durchgeführte Abhängigkeits-Updates

Installiert und mit grüner Suite bestätigt:

| Paket | vorher | nachher | Grund |
|---|---|---|---|
| pypdf | 6.14.2 | 6.16.1 | 2 DoS-Advisories (nicht erreichbar — FootSim extrahiert keinen Text — trotzdem gehoben) |
| Werkzeug | 3.1.3 | 3.1.8 | 3 `safe_join`-Advisories (Windows; Produktion ist Linux → dort nicht erreichbar) |
| idna | 3.11 | 3.15 | ReDoS in `idna.encode()` |
| certifi | 2026.2.25 | 2026.7.22 | Aktualität des CA-Bundles |
| charset-normalizer | 3.4.5 | 3.5.1 | Aktualität |
| setuptools | 58.1.0 | 82.0.1 | 4 Advisories; reines Build-Werkzeug im venv, kein Deployment-Artefakt |

Neu: `requirements-dev.txt` mit `pytest` und `pip-audit`, damit die Schwachstellenprüfung reproduzierbar ist. Diese Datei wird **nicht** auf dem VPS installiert.

> **Zur Auswertung von `pip-audit`:** Es meldet auch seine eigenen Abhängigkeiten (`filelock`, `msgpack`) sowie `pip` und `pytest`. Diese laufen nie auf dem Server. Relevant sind die Pakete aus `requirements.txt`.

---

## 9. E-4 — Registrierung verrät Adressen (offen, Produktentscheidung)

`src/api/auth.py:250` antwortet bei bereits registrierter Adresse mit `409 "Email is already registered"`. Damit lässt sich jede Adresse prüfen — dasselbe Leck, das B3 an anderer Stelle geschlossen hat.

**Bewusst nicht einseitig geändert.** Die sichere Variante (immer 201 antworten und dem Bestandskonto stattdessen eine „jemand wollte sich mit deiner Adresse registrieren"-Mail schicken) ist eine spürbare UX-Änderung: wer sein Passwort vergessen hat und sich erneut registriert, bekommt dann keine klare Fehlermeldung mehr. Das ist eine Produktentscheidung.

Solange sie offen ist, ist die B3-Härtung unvollständig: ein Angreifer nimmt einfach die Registrierungsroute.

---

## 10. Geänderte Dateien

```
 .env.example                     | Platzhalter statt echter Kombination
 app.py                           | B4 Seitenbudget, B5 formats=
 docker-compose.yml               | B2 nur noch Umgebungsvariablen
 ops/nginx-footsim.conf.reference | B1 Direktiven aktiv, Symlink-Warnung
 requirements.txt                 | Updates + Python-3.9-Deckelung dokumentiert
 requirements-dev.txt             | neu
 src/api/auth.py                  | B3 Hintergrundversand, 503-Zweig entfernt
 src/models/extensions.py         | B1 konfigurierbarer Storage
 src/utils/mail.py                | B3 send_in_background()
 tests/test_audit_hardening.py    | neu, 15 Tests
 tests/test_email_verification.py | Vertrag auf generische Antwort umgestellt
```

Die lokale, ignorierte `.env` wurde ergänzt (nicht getrackt, keine Werte ausgegeben).

---

## 11. Was ausdrücklich NICHT geschah

Kein Commit, kein Push, kein Pull, kein Deployment. Kein SSH-Zugriff auf den VPS. Keine Änderung an systemd oder nginx. Kein Neustart produktiver Dienste. Keine Änderung produktiver Datenbankdaten. Keine Schlüsselrotation. Keine Secret-Werte angezeigt. Keine Offsite-Backups konfiguriert. Kein ML, keine Simulationsregler, keine erfundenen Produktlimits.

---

## 12. Offene Punkte, nach Dringlichkeit

1. **Python 3.9 → 3.12** (B6). Ursache für fünf ungepatchte Pakete. Eigener Vorgang, eigenes Deployment.
2. **E-4 entscheiden.** Ohne sie bleibt die Enumeration über die Registrierung offen.
3. **Altes DB-Passwort wechseln** (B2). Über die Git-Historie weiterhin lesbar.
4. **`APISPORTS_KEY` als kompromittiert behandeln.** In einer früheren Sitzung wurde der Wert durch ein unvorsichtiges `grep` auf dem VPS im Klartext ausgegeben und steht damit im Transkript. Rotation war für diese Phase ausdrücklich untersagt — der Punkt bleibt offen und sollte nachgeholt werden.
5. **Fehlende Phasen 2–10** des GO-Auftrags nachreichen.
6. **`pip-audit` vor jedem Deployment laufen lassen.** Grüne Tests sagen nichts über bekannte Lücken in Abhängigkeiten aus.
