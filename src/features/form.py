"""
Kurzfristige Form und Gegnerstaerke vor einem Spiel (V2-C4).

WAS "FORM" HIER HEISST - UND WAS SCHON DA WAR
---------------------------------------------
Der V1-Kandidat enthaelt bereits Form, nur nicht unter diesem Namen:
points_per_game, win_rate, goals_for_per_game, goals_against_per_game
und die vier heim-/auswaertsgetrennten Angriffs- und Abwehrwerte sind
saisonweit gebildete Leistungsgroessen zum Stichtag. Wer "Form" sagt,
meint aber etwas anderes: die letzten paar Spiele, nicht die halbe
Saison.

Genau diese Luecke fuellt dieses Modul - und nur sie:

    Fenster       die letzten N Partien, nicht N Tage
    Trennung      national gegen Champions League, Heim gegen Auswaerts
    Gegner        wie stark waren die zuletzt bespielten Mannschaften

KEINE ZWEITE ZEITLEISTE, KEIN ZWEITES PROFIL
--------------------------------------------
Gerechnet wird auf der bestehenden wettbewerbsuebergreifenden
Zeitleiste (match_timeline). Sie bringt bereits alles mit, worauf es
ankommt: nur tatsaechlich ausgetragene Partien, Deduplizierung ueber
(competition, season, match_id), is_home je Team, den Wettbewerbscode,
die Runde und den Stichtagsschnitt. Ein eigener Datenpfad hier waere
die sicherste Art, sich von der Belastungsrechnung zu entfernen, ohne
dass es an einer Zahl auffaellt.

Die Gegnerstaerke kommt ueber eine hereingereichte Funktion. Dieses
Modul laedt nichts und kennt keine Datei - so bleibt es ohne Bestand
testbar, und der Aufrufer behaelt die Kontrolle darueber, WELCHER
Stichtag fuer den Gegner gilt.

WARUM FENSTER NACH PARTIEN UND NICHT NACH TAGEN
-----------------------------------------------
Ein 30-Tage-Fenster ist im Januar leer und im April voll. Genau das
haben die Belastungsmerkmale in V2-C3 gemessen - dort ist es richtig,
weil Ermuedung an der Zeit haengt. Form haengt an Spielen: "die letzten
fuenf" ist ueber eine Winterpause hinweg dieselbe Aussage, "die letzten
dreissig Tage" nicht.

KEIN LEAKAGE
------------
Jede Funktion bekommt einen cutoff und wertet ausschliesslich Partien
STRIKT davor aus. Das Zielspiel selbst zaehlt nie mit.
"""

from src.features.match_timeline import (BASE_LOAD_COMPETITIONS,
                                         CUP_COMPETITIONS, matches_before)


#: Fenstergroessen in PARTIEN, vorab festgelegt.
#:
#: Drei Werte und nicht mehr. Die Begruendung ist keine Vorliebe,
#: sondern Datenmenge: Der auswertbare CL-Bestand umfasst 213 Partien.
#: Jede zusaetzliche Fenstergroesse ist eine weitere getestete Variante
#: und macht die Auswahlunsicherheit groesser, ohne die Stichprobe zu
#: vergroessern.
#:
#:   3   die uebliche "letzte drei Spiele"-Lesart, sehr reaktiv
#:   5   der gaengige Kompromiss zwischen Reaktion und Rauschen
#:   8   rund ein Viertel einer Ligasaison - traege, aber stabil
#:
#: Die Werte standen vor dem ersten Lauf fest und wurden danach nicht
#: veraendert.
DEFAULT_WINDOWS = (3, 5, 8)

#: Das Fenster, in dem die getrennten Betrachtungen laufen.
#:
#: Nur EINES statt aller drei je Trennung: Heim-, Auswaerts-, National-
#: und CL-Form mit je drei Fenstern waeren zwoelf zusaetzliche
#: Merkmalspaare, von denen die meisten fast dasselbe messen. Die
#: Fensterfrage wird an der allgemeinen Form entschieden; die
#: Trennungen laufen dann im mittleren Fenster.
SPLIT_WINDOW = 5

#: Wie viele Partien ein Fenster mindestens enthalten muss.
#:
#: Ein Mittelwert ueber eine einzige Partie ist kein Formwert, sondern
#: dieses eine Ergebnis - und er traegt dieselbe scheinbare Sicherheit
#: wie einer ueber acht. Unterhalb dieser Grenze bleibt der Wert None.
#:
#: Zwei ist die kleinste Zahl, bei der ueberhaupt gemittelt wird. Fuer
#: die getrennten Betrachtungen (Heim, Auswaerts, CL) ist sie bewusst
#: nicht hoeher: Sonst haette eine Mannschaft in ihrer ersten
#: CL-Saison bis zum vierten Spieltag gar keine CL-Form - und die
#: Luecke waere groesser als der Nutzen.
MIN_WINDOW_MATCHES = 2

#: Punkte je Ergebnis. Sieg 1, Remis 0,5, Niederlage 0.
#:
#: Bewusst auf [0, 1] normiert statt 3/1/0: Der Wert ist dann eine
#: Quote und direkt mit win_rate aus dem Teamprofil vergleichbar. Die
#: Drei-Punkte-Regel ist eine Tabellenkonvention, keine Aussage ueber
#: Spielstaerke.
POINTS_WIN = 1.0
POINTS_DRAW = 0.5
POINTS_LOSS = 0.0

#: Wettbewerbe der NATIONALEN Form. Aus der Zeitleiste abgeleitet, nicht
#: ein zweites Mal getippt: Es sind dieselben Wettbewerbe, die dort den
#: Grundtakt einer Mannschaft bilden - die fuenf Top-Ligen und die 18
#: nationalen Ligen aus V2-C2B.
#:
#: Die nationalen POKALE stehen bewusst NICHT darin. Ein Zweitrunden-
#: Pokalspiel gegen einen Viertligisten ist zwar ein Pflichtspiel (und
#: erzeugt deshalb Belastung), aber als Formaussage waere es irrefuehrend:
#: Ein 5:0 dort ist kein Formbeleg. Fuer die ALLGEMEINE Form zaehlt es
#: mit - dort ist die Gegnerstaerke ein eigenes Merkmal.
DOMESTIC_FORM_COMPETITIONS = frozenset(BASE_LOAD_COMPETITIONS)

#: Wettbewerbe der EUROPAEISCHEN Form. Derzeit ausschliesslich die
#: Champions League - Europa League und Conference League liegen nicht
#: vor (siehe match_timeline.coverage()["known_gaps"]).
EUROPEAN_FORM_COMPETITIONS = frozenset(CUP_COMPETITIONS)

#: Die Betrachtungen, vorab festgelegt und in fester Reihenfolge.
#:
#: Ein Eintrag ist (name, fenster, wettbewerbe, ort):
#:   wettbewerbe None  -> alle, wettbewerbsuebergreifend
#:   ort None          -> Heim- und Auswaertsspiele
#:   ort True/False    -> nur Heim- bzw. nur Auswaertsspiele
FORM_SCOPES = (
    ("all_3", 3, None, None),
    ("all_5", 5, None, None),
    ("all_8", 8, None, None),
    ("domestic_5", SPLIT_WINDOW, DOMESTIC_FORM_COMPETITIONS, None),
    ("cl_5", SPLIT_WINDOW, EUROPEAN_FORM_COMPETITIONS, None),
    ("home_5", SPLIT_WINDOW, None, True),
    ("away_5", SPLIT_WINDOW, None, False),
)

SCOPE_NAMES = tuple(name for name, _, _, _ in FORM_SCOPES)

#: Was je Betrachtung gerechnet wird.
#:
#:   points_rate           Ergebnisform: Punktequote in [0, 1]
#:   goal_diff_per_match   Torform: Tordifferenz je Partie
#:
#: Torverhaeltnis UND Punktequote, weil sie verschiedene Dinge sagen:
#: Drei knappe Siege und ein 6:0 mit zwei Niederlagen ergeben dieselbe
#: Tordifferenz, aber sehr verschiedene Punktequoten. Welches der
#: beiden - wenn ueberhaupt - traegt, entscheidet die Ablation.
FORM_METRICS = ("points_rate", "goal_diff_per_match")

#: Die Tiefenangabe je Betrachtung. Sie ist KEIN Modellmerkmal,
#: sondern eine Qualitaetsangabe - dieselbe Lehre wie bei
#: profile_depth in V2-C2: Sie beschreibt die Quelle, nicht die
#: Mannschaft, und hat in der Champions League einen anderen
#: Wertebereich als im Ligatraining.
FORM_DEPTH_SUFFIX = "matches"

#: Fenster der Gegnerstaerke - dasselbe wie bei den Trennungen.
OPPONENT_WINDOW = SPLIT_WINDOW


def _punkte(eintrag, team_ist_heim):
    """
    Der Ergebniswert einer Partie aus Sicht einer Mannschaft.

    DIE ERGEBNISREGEL, AUSDRUECKLICH
    Gewertet wird der Spielstand nach Ablauf der reguleren Spielzeit
    beziehungsweise nach Verlaengerung. Ein Elfmeterschiessen aendert
    ihn NICHT: Die Quellen fuehren die Schuetzentore in eigenen Feldern
    (penalty_home/penalty_away), home_goals/away_goals bleiben der
    Spielstand nach 90 bzw. 120 Minuten.

    Damit gilt ein im Elfmeterschiessen entschiedenes Spiel hier als
    REMIS. Das ist die uebliche Konvention der Fussballstatistik und
    zugleich die einzige, die ohne Zusatzannahme aus den Daten folgt -
    ein Schuetzenduell sagt ueber die Spielstaerke wenig.

    Rueckgabe: None, wenn kein verwertbares Ergebnis vorliegt.
    """
    heim, gast = eintrag.get("home_goals"), eintrag.get("away_goals")
    if heim is None or gast is None:
        return None

    eigene, fremde = (heim, gast) if team_ist_heim else (gast, heim)
    if eigene > fremde:
        return POINTS_WIN
    if eigene < fremde:
        return POINTS_LOSS
    return POINTS_DRAW


def _tordifferenz(eintrag, team_ist_heim):
    """Tordifferenz einer Partie aus Sicht einer Mannschaft."""
    heim, gast = eintrag.get("home_goals"), eintrag.get("away_goals")
    if heim is None or gast is None:
        return None
    return float(heim - gast) if team_ist_heim else float(gast - heim)


def _fenster(vorherige, anzahl, competitions=None, venue=None):
    """
    Die letzten `anzahl` passenden Partien - juengste zuletzt.

    Erst filtern, dann abschneiden. Die andere Reihenfolge waere ein
    stiller Fehler: "die letzten fuenf Heimspiele" ist nicht dasselbe
    wie "die Heimspiele unter den letzten fuenf Partien", und die
    zweite Lesart liefert bei einer Auswaertsserie fast nichts.
    """
    passend = []
    for eintrag in vorherige:
        if competitions is not None and eintrag.get("competition") not in competitions:
            continue
        if venue is not None and eintrag.get("is_home") is not venue:
            continue
        passend.append(eintrag)
    return passend[-anzahl:] if anzahl else passend


def _mittel(werte):
    """Mittelwert - oder None bei zu duenner Grundlage."""
    brauchbar = [w for w in werte if w is not None]
    if len(brauchbar) < MIN_WINDOW_MATCHES:
        return None
    return sum(brauchbar) / len(brauchbar)


def scope_values(vorherige, name, anzahl, competitions, venue):
    """
    Punktequote, Tordifferenz und Tiefe EINER Betrachtung.

    Rueckgabe: dict mit den Schluesseln
    "<name>_points_rate", "<name>_goal_diff_per_match", "<name>_matches".

    Die Tiefe steht IMMER da, auch wenn die Werte None sind. Ohne sie
    liesse sich "keine Partie im Fenster" nicht von "zwei Partien, aber
    ohne Ergebnis" unterscheiden - und genau diese Unterscheidung
    entscheidet, ob eine Luecke ehrlich oder verdaechtig ist.
    """
    fenster = _fenster(vorherige, anzahl, competitions, venue)

    punkte, differenzen = [], []
    for eintrag in fenster:
        heim = eintrag.get("is_home")
        punkte.append(_punkte(eintrag, heim))
        differenzen.append(_tordifferenz(eintrag, heim))

    return {
        f"{name}_points_rate": _mittel(punkte),
        f"{name}_goal_diff_per_match": _mittel(differenzen),
        f"{name}_{FORM_DEPTH_SUFFIX}": len(fenster),
    }


def opponent_values(vorherige, strength_at, anzahl=OPPONENT_WINDOW):
    """
    Gegnerstaerke der juengsten Partien - und die daran gewichtete Form.

    strength_at: Funktion (team_id, kickoff) -> Staerke oder None.

    DER ENTSCHEIDENDE PUNKT: WELCHER STICHTAG GILT FUER DEN GEGNER
    Nicht der des Zielspiels, sondern der der DAMALIGEN Partie. Ein
    Gegner, der im September geschlagen wurde und danach zehnmal
    gewann, war im September nicht der Verein, als der er heute
    dasteht. Die Staerke zum Zielstichtag zu nehmen waere zwar kein
    Zukunftsleck gegenueber der Prognose - sie laege ja vor dem
    Cutoff -, aber sie enthielte das Ergebnis genau der Partie, die
    gerade bewertet wird. Diese Funktion verlangt deshalb eine
    Funktion und keinen fertigen Lookup.

    Zwei Werte:

      opponent_strength_5        mittlere Gegnerstaerke im Fenster
      adjusted_points_rate_5     mit der Gegnerstaerke GEWICHTETE
                                 Punktequote

    Die Gewichtung ist parameterfrei und damit nachpruefbar:

        sum(punkte_i * staerke_i) / sum(staerke_i)

    Ein Sieg gegen einen starken Gegner zaehlt mehr als einer gegen
    einen schwachen. Eine Erwartungskurve "welche Punktzahl ist gegen
    diese Staerke normal" waere die naheliegende Alternative - sie
    braeuchte aber einen freien Parameter, den niemand gemessen hat.
    Die lineare Anpassung des Modells kann eine solche Korrektur aus
    Punktequote und Gegnerstaerke ohnehin selbst bilden.

    Rueckgabe: dict. Fehlt jede Gegnerstaerke, bleiben beide Werte
    None - nicht null.
    """
    fenster = _fenster(vorherige, anzahl)

    staerken, punkte = [], []
    ohne_staerke = 0
    for eintrag in fenster:
        gegner = eintrag.get("opponent_id")
        wert = None if gegner is None else strength_at(gegner, eintrag["kickoff"])
        if wert is None:
            # Ein unterklassiger Pokalgegner ohne Profil. Nicht mit
            # einem Schaetzwert fuellen - das waere erfunden.
            ohne_staerke += 1
            continue
        p = _punkte(eintrag, eintrag.get("is_home"))
        if p is None:
            ohne_staerke += 1
            continue
        staerken.append(float(wert))
        punkte.append(p)

    if len(staerken) < MIN_WINDOW_MATCHES:
        return {
            "opponent_strength_5": None,
            "adjusted_points_rate_5": None,
            "opponent_strength_matches": len(staerken),
            "opponents_without_strength_5": ohne_staerke,
        }

    summe = sum(staerken)
    gewichtet = (sum(p * s for p, s in zip(punkte, staerken)) / summe
                 if summe > 0 else None)

    return {
        "opponent_strength_5": sum(staerken) / len(staerken),
        "adjusted_points_rate_5": gewichtet,
        "opponent_strength_matches": len(staerken),
        "opponents_without_strength_5": ohne_staerke,
    }


def form_features(timeline, cutoff, strength_at=None, scopes=FORM_SCOPES):
    """
    Alle Formmerkmale einer Mannschaft zum Zeitpunkt cutoff.

    timeline: Ausgabe von match_timeline.team_timeline() fuer EIN Team.
    cutoff:   datetime des Zielspiels. Partien ab diesem Zeitpunkt
              zaehlen nicht mit.
    strength_at: Funktion (team_id, kickoff) -> Staerke oder None.
              Ohne sie entfaellt die Gegnerstaerke; die uebrigen
              Merkmale entstehen unveraendert.

    Rueckgabe: dict mit ALLEN Feldern - auch dort, wo nichts bekannt
    ist. Ein fehlender Schluessel waere fuer den Aufrufer schlechter
    als ein ehrliches None.

    ALTE PARTIEN WERDEN NICHT ABGEWERTET
    Innerhalb eines Fensters zaehlt jede Partie gleich. Eine zweite
    Abklingkonstante waere ein freier Parameter, den diese Datenmenge
    nicht bestimmen kann - das Fenster IST die Gewichtung, und drei
    Fenstergroessen decken die Spannweite ab.
    """
    vorherige = matches_before(timeline, cutoff)

    werte = {}
    for name, anzahl, competitions, venue in scopes:
        werte.update(scope_values(vorherige, name, anzahl, competitions, venue))

    if strength_at is not None:
        werte.update(opponent_values(vorherige, strength_at))
    else:
        werte.update({
            "opponent_strength_5": None,
            "adjusted_points_rate_5": None,
            "opponent_strength_matches": 0,
            "opponents_without_strength_5": 0,
        })

    werte["form_matches_available"] = len(vorherige)
    return werte
