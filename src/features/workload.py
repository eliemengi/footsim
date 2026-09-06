"""
Belastung, Terminverdichtung und Gegnerstaerke vor einem Spiel.

WAS HIER GERECHNET WIRD
-----------------------
Aus der wettbewerbsuebergreifenden Zeitleiste (match_timeline.py) drei
Gruppen von Merkmalen:

    Erholung      Wie lange ist das letzte Pflichtspiel her?
    Verdichtung   Wie viele Spiele lagen in den letzten 7/14/21/30 Tagen?
    Verlaengerung Wie viele Zusatzminuten kamen in 30 Tagen dazu? (V2-C3)
    Gegnerstaerke Wie schwer waren die zuletzt bespielten Gegner?

Die Verlaengerungsbelastung ist die einzige dieser Gruppen mit einer
wettbewerbsabhaengigen Datenlage: Fuer die K.-o.-Runden der Champions
League fuehrt die Quelle keinen Verlaengerungsstatus. Dort bleibt der
Wert ehrlich None - siehe extra_time_minutes().

ZEITLICHE GENAUIGKEIT - EHRLICH BENANNT
---------------------------------------
Nur die Pokalspiele tragen eine echte Anstosszeit. Die football-data-
Historie fuehrt fuer Ligen und Champions League ausschliesslich
Kalendertage; dort setzt die Zeitleiste ersatzweise Mittag an.

Fuer den groessten Teil der Spiele ist rest_hours deshalb KEINE
gemessene Groesse, sondern eine Ableitung aus dem Kalendertag. Der Fehler
liegt bei bis zu zwoelf Stunden je Seite. Das Feld time_precision haelt
fest, welcher Fall vorliegt, und die Datenqualitaet wird entsprechend
abgestuft. Eine Stundenzahl auszugeben, die genauer aussieht als ihre
Quelle, waere eine Scheingenauigkeit - deshalb steht der Hinweis hier
und wandert bis in die API-Diagnose durch.

KEIN LEAKAGE
------------
Jede Funktion bekommt einen cutoff und wertet ausschliesslich Spiele
STRIKT davor aus. Das Zielspiel selbst zaehlt nie mit - sonst waere die
Belastung "vor" dem Spiel durch das Spiel selbst mitbestimmt.
"""

from src.features.match_timeline import matches_before


#: Fenster, ueber die Spiele gezaehlt werden (Tage).
DEFAULT_WINDOWS = (7, 14, 21, 30)

#: Ab wann eine Pause als kurz gilt.
#:
#: Drei Tage entsprechen dem klassischen Samstag-Dienstag-Rhythmus. Die
#: sportmedizinische Literatur setzt die Erholung nach einem
#: Pflichtspiel bei 72 Stunden an; darunter ist die Regeneration
#: unvollstaendig. Der Schwellwert ist bewusst als Stundenzahl gefuehrt,
#: damit ein Sonntagabend-Dienstagabend-Paar nicht faelschlich als volle
#: Pause durchgeht.
SHORT_REST_HOURS = 72

#: Ab wie vielen Spielen in sieben Tagen die Verdichtung hoch ist.
#: Drei Pflichtspiele in einer Woche sind der Ausnahmefall, den auch
#: Vereine oeffentlich als Belastungsspitze benennen.
HIGH_LOAD_7D = 3

#: Zwei Spiele in sieben Tagen sind der englische Wochen-Normalfall
#: eines europaeisch spielenden Vereins - erhoeht, aber nicht extrem.
ELEVATED_LOAD_7D = 2

#: Ueber vierzehn Tage gemittelt gilt dieselbe Logik traeger.
ELEVATED_LOAD_14D = 5

#: Unterhalb dieser Werte ist die Woche ruhig.
LOW_LOAD_14D = 1
LOW_REST_DAYS = 7

#: Wie viele Spiele mindestens vorliegen muessen, damit die Verdichtung
#: ueberhaupt aussagekraeftig ist. Nach einem einzigen Saisonspiel ist
#: jedes Fenster trivial leer und wuerde faelschlich "ruhig" melden.
MIN_MATCHES_FOR_CONGESTION = 3

#: Wie viele Gegner mindestens bewertet sein muessen, damit die
#: Spielplanhaerte gemeldet wird.
MIN_OPPONENTS_FOR_STRENGTH = 3

#: Ueber wie viele Tage zurueck die Gegnerstaerke gebildet wird.
STRENGTH_WINDOW_DAYS = 30

#: Datenqualitaetsklassen, absteigend nach Verlaesslichkeit.
#:
#:   complete     Zeitleiste vollstaendig, echte Anstosszeiten, genug Spiele
#:   partial      belastbar, aber mit Einschraenkung (z. B. nur Kalendertage)
#:   fallback     duenn - Richtung stimmt, Betrag unsicher
#:   unavailable  keine Aussage moeglich
#:
#: Die Klasse ist kein Etikett, sondern steuert spaeter die Staerke des
#: Einflusses. "unavailable" bedeutet ausdruecklich: exakt neutral,
#: nicht "ein bisschen".
QUALITY_CLASSES = ("complete", "partial", "fallback", "unavailable")

#: Wie stark ein Merkmal je Qualitaetsklasse wirken darf.
QUALITY_WEIGHTS = {
    "complete": 1.0,
    "partial": 0.6,
    "fallback": 0.3,
    "unavailable": 0.0,
}


#: Ueber welches Fenster die Verlaengerungsbelastung gebildet wird.
#: Dasselbe wie das laengste Zaehlfenster - eine eigene Laenge waere
#: eine zusaetzliche, unbegruendete Wahl.
EXTRA_TIME_WINDOW_DAYS = 30

#: Wie viele Minuten eine Verlaengerung kostet. Zweimal fuenfzehn, die
#: Regel des Spiels. Nachspielzeit ist in keiner Quelle gefuehrt und
#: wird deshalb NICHT geschaetzt.
EXTRA_TIME_MINUTES = 30

#: Anbieterstatus, der eine Verlaengerung ausweist.
#: PEN schliesst AET ein: Ein Elfmeterschiessen gibt es erst NACH der
#: Verlaengerung. Die Schuetzenminuten selbst zaehlen nicht als
#: Spielzeit - sie stehen in keiner Regel als solche.
EXTRA_TIME_STATUSES = ("AET", "PEN")

#: Anbieterstatus, der die regulaeren neunzig Minuten ausweist.
#: AWD und WO sind Wertungen am gruenen Tisch bzw. kampflose Siege. Sie
#: erzeugen keine Spielminuten - aber sie sind BEKANNT und deshalb
#: nicht "unbekannt".
REGULAR_TIME_STATUSES = ("FT", "AWD", "WO")

#: Runden, die per Reglement keine Verlaengerung kennen. Ein Rundenspiel
#: endet nach neunzig Minuten, auch unentschieden.
NO_EXTRA_TIME_STAGES = ("GROUP_STAGE", "LEAGUE_STAGE")

#: Wettbewerbe, deren Quelle keinen Status fuehrt, in denen eine
#: Verlaengerung aber ausgeschlossen ist: die fuenf Top-Ligen aus der
#: football-data-Historie. Ein Ligaspiel dauert neunzig Minuten - das
#: ist keine Annahme ueber die Daten, sondern die Spielregel.
REGULAR_TIME_COMPETITIONS = ("BL1", "PL", "PD", "SA", "FL1")


def extra_time_minutes(eintrag):
    """
    Zusaetzlich gespielte Minuten einer Partie - oder None.

    DIE UNTERSCHEIDUNG, AUF DIE ES ANKOMMT
    None heisst NICHT "keine Verlaengerung", sondern "nicht bekannt".
    Beides in eine Null zu legen waere genau die Scheingenauigkeit, die
    dieses Modul sonst vermeidet: Die football-data-Historie fuehrt fuer
    die Champions League ausschliesslich den Status FINISHED. Ob ein
    Achtelfinale nach neunzig oder nach hundertzwanzig Minuten endete,
    steht dort nicht - und laesst sich auch nicht aus dem Ergebnis
    ableiten.

    Bekannt ist der Wert in drei Faellen:

        Anbieterstatus AET/PEN      Verlaengerung, EXTRA_TIME_MINUTES
        Anbieterstatus FT/AWD/WO    regulaer, null
        Runde ohne Verlaengerung    regulaer, null (Reglement)

    und zusaetzlich fuer die fuenf Top-Ligen, deren Quelle gar keinen
    Status fuehrt: Ein Ligaspiel kennt keine Verlaengerung.
    """
    if eintrag is None:
        return None

    status = eintrag.get("status")
    status = str(status).upper() if status is not None else None

    if status in EXTRA_TIME_STATUSES:
        return float(EXTRA_TIME_MINUTES)
    if status in REGULAR_TIME_STATUSES:
        return 0.0

    # Rundenspiele koennen per Reglement nicht in die Verlaengerung -
    # unabhaengig davon, was der Anbieter im Status fuehrt.
    if eintrag.get("stage") in NO_EXTRA_TIME_STAGES:
        return 0.0

    if status is None and eintrag.get("competition") in REGULAR_TIME_COMPETITIONS:
        return 0.0

    return None


def _extra_time_load(vorherige, cutoff, fenster_tage=EXTRA_TIME_WINDOW_DAYS):
    """
    Verlaengerungsbelastung im Fenster - als (partien, minuten, qualitaet).

    Eine EINZIGE unbekannte Partie im Fenster macht die Summe unsicher,
    nicht falsch: Die gezaehlten Minuten sind dann eine Untergrenze. Das
    steht als "partial" in der Qualitaet, und die Werte bleiben stehen -
    sie auf None zu setzen wuerde eine belegte Beobachtung wegen einer
    Unsicherheit an anderer Stelle verwerfen.

    Ist im Fenster ueberhaupt keine Partie bekannt, gibt es nichts zu
    melden: (None, None, "unavailable").
    """
    from datetime import timedelta

    if cutoff is None or not vorherige:
        return None, None, "unavailable"

    grenze = cutoff - timedelta(days=fenster_tage)
    im_fenster = [e for e in vorherige if e["kickoff"] >= grenze]
    if not im_fenster:
        return 0, 0.0, "complete"

    partien, minuten, unbekannt = 0, 0.0, 0
    for eintrag in im_fenster:
        wert = extra_time_minutes(eintrag)
        if wert is None:
            unbekannt += 1
            continue
        if wert > 0:
            partien += 1
        minuten += wert

    if unbekannt == len(im_fenster):
        return None, None, "unavailable"
    return partien, minuten, ("complete" if unbekannt == 0 else "partial")


def _rest_hours(vorheriges, cutoff):
    """
    Stunden zwischen letztem Anpfiff und dem Zielspiel.

    RUNDUNGSREGEL: kaufmaennisch auf eine ganze Stunde, ueber round().
    Halbe Stunden werden also zur naechsten geraden Stunde gerundet
    (Bankers Rounding, Python-Standard). Das ist bewusst nicht
    abgeschnitten: Abschneiden wuerde die Pause systematisch verkuerzen
    und Belastung durchgaengig ueberschaetzen.
    """
    if vorheriges is None or cutoff is None:
        return None
    differenz = cutoff - vorheriges["kickoff"]
    return round(differenz.total_seconds() / 3600.0)


def _consecutive_away(vorherige):
    """
    Wie viele Auswaertsspiele unmittelbar hintereinander zuletzt kamen.

    Zaehlt vom juengsten Spiel rueckwaerts und bricht beim ersten
    Heimspiel ab. Reisebelastung entsteht durch die Serie, nicht durch
    die Gesamtzahl.
    """
    anzahl = 0
    for eintrag in reversed(vorherige):
        if eintrag.get("is_home") is False:
            anzahl += 1
        else:
            break
    return anzahl


def _congestion_level(fenster, rest_hours, nutzbare):
    """
    Verdichtungsstufe: low / normal / elevated / high.

    Bewusste Absicherung: EIN einzelnes Pokalspiel darf niemals allein
    "high" ergeben. "high" setzt drei Spiele in sieben Tagen voraus oder
    zwei Spiele bei zusaetzlich kurzer Pause - ein Mittwochsspiel nach
    ruhiger Woche erfuellt beides nicht.
    """
    if nutzbare < MIN_MATCHES_FOR_CONGESTION:
        return None

    letzte7 = fenster.get(7, 0)
    letzte14 = fenster.get(14, 0)
    kurz = rest_hours is not None and rest_hours < SHORT_REST_HOURS

    if letzte7 >= HIGH_LOAD_7D:
        return "high"
    if letzte7 >= ELEVATED_LOAD_7D and kurz:
        return "high"
    if letzte7 >= ELEVATED_LOAD_7D or letzte14 >= ELEVATED_LOAD_14D or kurz:
        return "elevated"
    if letzte14 <= LOW_LOAD_14D and (rest_hours is None
                                     or rest_hours >= LOW_REST_DAYS * 24):
        return "low"
    return "normal"


def _quality(vorherige, nutzbare):
    """
    Datenqualitaet der ZAEHLUNGEN (Spiele je Fenster).

    Diese Groessen haengen ausschliesslich am Kalendertag und sind
    deshalb exakt, sobald genug Spiele vorliegen - auch dann, wenn keine
    Anstosszeit bekannt ist. Ein Spiel am 14. September liegt in den
    letzten sieben Tagen oder nicht; die Uhrzeit aendert daran nichts.

    Die geringere Genauigkeit der Stundenrechnung wird deshalb NICHT
    hier abgebildet, sondern getrennt ueber _rest_quality(). Beides in
    eine Zahl zu pressen wuerde exakte Zaehlungen ohne Grund abwerten.
    """
    if not vorherige or nutzbare == 0:
        return "unavailable"
    if nutzbare < MIN_MATCHES_FOR_CONGESTION:
        return "fallback"
    return "complete"


def _rest_quality(letztes):
    """
    Datenqualitaet der PAUSE in Stunden.

    "complete" nur bei echter Anstosszeit. Ist die Zeit aus dem
    Kalendertag abgeleitet (football-data fuehrt fuer Ligen und
    Champions League keine Uhrzeit), betraegt der Fehler bis zu zwoelf
    Stunden je Seite - das ist "partial", nicht "complete".
    """
    if letztes is None:
        return "unavailable"
    if letztes.get("time_precision") == "datetime":
        return "complete"
    return "partial"


def workload_features(timeline, cutoff, windows=DEFAULT_WINDOWS):
    """
    Belastungsmerkmale eines Teams zum Zeitpunkt cutoff.

    timeline: Ausgabe von match_timeline.team_timeline() fuer EIN Team.
    cutoff:   datetime des Zielspiels. Spiele ab diesem Zeitpunkt
              zaehlen nicht mit.

    Rueckgabe: dict mit allen Feldern - auch dann, wenn nichts bekannt
    ist. Ein fehlender Schluessel waere fuer den Aufrufer schlechter als
    ein ehrliches None.
    """
    from datetime import timedelta

    vorherige = matches_before(timeline, cutoff)
    nutzbare = len(vorherige)

    letztes = vorherige[-1] if vorherige else None
    stunden = _rest_hours(letztes, cutoff)

    fenster = {}
    for tage in windows:
        grenze = cutoff - timedelta(days=tage) if cutoff else None
        fenster[tage] = sum(1 for e in vorherige if e["kickoff"] >= grenze) \
            if grenze else 0

    qualitaet = _quality(vorherige, nutzbare)
    pausen_qualitaet = _rest_quality(letztes)
    stufe = _congestion_level(fenster, stunden, nutzbare)
    et_partien, et_minuten, et_qualitaet = _extra_time_load(vorherige, cutoff)

    wettbewerbe = sorted({e["competition"] for e in vorherige})

    return {
        "previous_match_datetime": letztes["kickoff"].isoformat() if letztes else None,
        "previous_match_competition": letztes["competition"] if letztes else None,
        "rest_hours": stunden,
        # rest_days bewusst aus den Stunden abgeleitet und ABGERUNDET:
        # "zwei volle Tage Pause" darf nicht heissen "49 Stunden".
        "rest_days": (stunden // 24) if stunden is not None else None,
        "short_rest_flag": (stunden is not None and stunden < SHORT_REST_HOURS),
        "matches_last_7_days": fenster.get(7, 0),
        "matches_last_14_days": fenster.get(14, 0),
        "matches_last_21_days": fenster.get(21, 0),
        "matches_last_30_days": fenster.get(30, 0),
        "consecutive_away_matches": _consecutive_away(vorherige),
        # Verlaengerungsbelastung (V2-C3). Minuten UND Partien, weil
        # beides eine andere Frage beantwortet: die Minuten die
        # zusaetzliche Spielzeit, die Partien die Haeufigkeit. Welche
        # der beiden - wenn ueberhaupt - traegt, entscheidet die
        # Ablation und nicht diese Datei.
        "extra_time_matches_last_30_days": et_partien,
        "extra_time_minutes_last_30_days": et_minuten,
        "congestion_level": stufe,
        "competitions_included": wettbewerbe,
        "number_of_usable_matches": nutzbare,
        "data_quality": qualitaet,
        # Getrennt gefuehrt: die Zaehlungen sind exakt, die Stundenzahl
        # ist es nur bei echter Anstosszeit. Die Integration darf
        # deshalb den pausenbasierten Anteil anders gewichten als den
        # zaehlbasierten - siehe Modulkopf.
        "rest_data_quality": pausen_qualitaet,
        "rest_time_precision": letztes.get("time_precision") if letztes else None,
        # Getrennt gefuehrt wie die Pausenqualitaet, und aus demselben
        # Grund: "partial" heisst hier, dass mindestens eine Partie im
        # Fenster keine Verlaengerungsangabe traegt und die Minuten
        # deshalb eine Untergrenze sind.
        "extra_time_data_quality": et_qualitaet,
    }


def schedule_strength(timeline, cutoff, strength_lookup,
                      window_days=STRENGTH_WINDOW_DAYS):
    """
    Wie schwer waren die zuletzt bespielten Gegner?

    strength_lookup: {team_id: staerke} - wird vom Aufrufer EINMAL
                     gebaut und hereingereicht. Bewusst keine eigene
                     Beschaffung: eine Staerkeabfrage je Simulation waere
                     genau der Fehler, den GO 3 vermeiden soll.

    Die Werte stammen aus der zentralen Staerkeberechnung des Projekts
    (src/features/strength_provider.py). Hier wird NICHT parallel
    gerechnet - es wird nur gemittelt.

    Punkt-in-Zeit: Es zaehlen nur Gegner aus Spielen strikt vor cutoff.
    Die Staerkewerte selbst muss der Aufrufer punktgenau erzeugt haben;
    eine Abschlusstabelle als Lookup waere Leakage.
    """
    from datetime import timedelta

    if not strength_lookup:
        return {
            "recent_opponent_strength": None,
            "number_of_usable_opponents": 0,
            "schedule_strength_quality": "unavailable",
            "opponent_window_days": window_days,
        }

    grenze = cutoff - timedelta(days=window_days) if cutoff else None
    vorherige = [e for e in matches_before(timeline, cutoff)
                 if grenze is None or e["kickoff"] >= grenze]

    werte = []
    ohne_wert = 0
    for eintrag in vorherige:
        gegner = eintrag.get("opponent_id")
        if gegner is None:
            # Unterklassiger Pokalgegner ohne Zuordnung. Nicht mit einer
            # geschaetzten Staerke fuellen - das waere erfunden.
            ohne_wert += 1
            continue
        wert = strength_lookup.get(gegner)
        if wert is None:
            ohne_wert += 1
            continue
        werte.append(float(wert))

    if not werte:
        return {
            "recent_opponent_strength": None,
            "number_of_usable_opponents": 0,
            "schedule_strength_quality": "unavailable",
            "opponent_window_days": window_days,
            "opponents_without_strength": ohne_wert,
        }

    durchschnitt = sum(werte) / len(werte)

    if len(werte) >= MIN_OPPONENTS_FOR_STRENGTH and ohne_wert == 0:
        qualitaet = "complete"
    elif len(werte) >= MIN_OPPONENTS_FOR_STRENGTH:
        qualitaet = "partial"
    else:
        qualitaet = "fallback"

    return {
        "recent_opponent_strength": round(durchschnitt, 4),
        "number_of_usable_opponents": len(werte),
        "schedule_strength_quality": qualitaet,
        "opponent_window_days": window_days,
        "opponents_without_strength": ohne_wert,
    }


def combined_quality(*klassen):
    """
    Gesamtqualitaet mehrerer Teilergebnisse: die schlechteste zaehlt.

    Ein Merkmalssatz ist nur so belastbar wie sein schwaechstes Glied.
    Ein Mittelwert waere hier falsch - er wuerde eine fehlende Angabe
    durch eine gute ausgleichen.
    """
    rang = {name: i for i, name in enumerate(QUALITY_CLASSES)}
    schlechteste = "complete"
    for klasse in klassen:
        if klasse in rang and rang[klasse] > rang[schlechteste]:
            schlechteste = klasse
    return schlechteste


def quality_weight(klasse):
    """Einflussfaktor einer Qualitaetsklasse. Unbekannt = neutral."""
    return QUALITY_WEIGHTS.get(klasse, 0.0)
