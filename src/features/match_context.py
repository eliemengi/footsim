"""
Struktureller Spielkontext einer Champions-League-Partie (V2-C5).

WAS HIER BEANTWORTET WIRD
-------------------------
Vier Fragen, die vor dem Anpfiff feststehen und die der Datensatz bis
V2-C4 gar nicht kannte:

    Welcher Wettbewerbsabschnitt?   Ligaphase oder K.-o.-Runde
    Welches Spiel der Paarung?      Hinspiel, Rueckspiel, Einzelspiel
    Wie steht es im Aggregat?       nur fuer Rueckspiele
    Neutraler Platz?                Endspiel gegen Heimrecht

Bis V2-C4 waren alle 119 K.-o.-Partien der Saisons 2023 bis 2025 aus
der Auswertung ausgeschlossen - mit genau dieser Begruendung: "Zwei-Leg-
und Verlaengerungslogik nicht modelliert". Dieses Modul modelliert sie.

EIN KANONISCHER TYP STATT MEHRERER WAHRHEITSWERTE
-------------------------------------------------
Der Kontext wird als EIN Feld gefuehrt (match_type) und die
Modellspalten daraus ABGELEITET. Vier unabhaengige Wahrheitswerte
- is_knockout, is_first_leg, is_second_leg, is_final - koennten sich
widersprechen: "Finale und Hinspiel" ist keine Partie, die es gibt, aber
eine Kombination, die vier Bools zulassen. Aus einem kanonischen Typ
abgeleitet, kann sie nicht entstehen.

DIE HERLEITUNG BENUTZT KEINE ZUKUNFT
------------------------------------
Das ist der heikelste Punkt und deshalb ausdruecklich geloest:

Ob eine Partie Hin- oder Rueckspiel ist, kommt aus IHREN EIGENEN
Metadaten - stage und matchday. Es waere bequemer gewesen, die Partien
einer Paarung zu zaehlen; dann haette ein Hinspiel aber wissen muessen,
dass spaeter ein Rueckspiel folgt. Das ist zwar Spielplanwissen und
damit vor dem Anpfiff bekannt, aber es waere ueber die Zukunft der
Ergebnisliste hergeleitet - und diese Unterscheidung ist genau die, die
man spaeter nicht mehr nachvollziehen kann.

Der Aggregatstand eines Rueckspiels kommt aus dem Hinspiel, und das
liegt strikt in der Vergangenheit. Ein Hinspiel bekommt KEINEN
Aggregatstand - weder null noch einen geschaetzten.

WAS DIE QUELLE NICHT HERGIBT
----------------------------
Nachgemessen an data/historical/CL_2023..2025.json: Die Partien tragen
ausschliesslich date, match_id, matchday, stage, status, home_id,
away_id, home_goals, away_goals.

Es gibt KEINE Spielstaetten- und keine Neutralitaetsangabe, und es gibt
keinen Verlaengerungs- oder Elfmeterstatus (alle 503 Partien tragen
schlicht FINISHED). Beides wird hier nicht erfunden - siehe
neutral_venue() und die Anmerkung zur Ergebnisregel weiter unten.
"""

#: Die Runden der Ligaphase. 2023 als Gruppenphase des 32er-Formats,
#: ab 2024 als Ligaphase des 36er-Formats. Beide sind Rundenspiele.
LEAGUE_PHASE_STAGES = ("GROUP_STAGE", "LEAGUE_STAGE")

#: Die K.-o.-Runden in aufsteigender Tiefe. Die Reihenfolge ist zugleich
#: die Ordinalskala von ko_round_index.
KNOCKOUT_STAGES = ("PLAYOFFS", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS",
                   "FINAL")

#: Das Endspiel. Einzelpartie, neutraler Platz - siehe neutral_venue().
FINAL_STAGE = "FINAL"

#: Der kanonische Spieltyp. Genau einer je Partie.
TYPE_LEAGUE_PHASE = "league_phase"
TYPE_KO_FIRST_LEG = "ko_first_leg"
TYPE_KO_SECOND_LEG = "ko_second_leg"
TYPE_KO_SINGLE = "ko_single_match"
TYPE_FINAL = "final"
TYPE_UNKNOWN = "unknown"

MATCH_TYPES = (TYPE_LEAGUE_PHASE, TYPE_KO_FIRST_LEG, TYPE_KO_SECOND_LEG,
               TYPE_KO_SINGLE, TYPE_FINAL, TYPE_UNKNOWN)

#: Welche Typen ueberhaupt K.-o. sind. Aus der Typliste abgeleitet,
#: damit es nur EINE Definition gibt.
KNOCKOUT_TYPES = (TYPE_KO_FIRST_LEG, TYPE_KO_SECOND_LEG, TYPE_KO_SINGLE,
                  TYPE_FINAL)

#: matchday-Werte, die ein Hin- bzw. Rueckspiel ausweisen.
#:
#: Nachgemessen ueber alle drei Saisons: Jede Zwei-Spiel-Paarung traegt
#: genau die Werte 1 und 2. Das Endspiel traegt None (2023, 2025) oder 0
#: (2024) - deshalb entscheidet dort die Runde und nicht der matchday.
FIRST_LEG_MATCHDAY = 1
SECOND_LEG_MATCHDAY = 2

#: Ab welcher Saison die UEFA-Auswaertstorregel abgeschafft ist.
#:
#: Das UEFA-Exekutivkomitee hat sie am 24.06.2021 mit Wirkung zur
#: Saison 2021/22 gestrichen. FootSim bezeichnet eine Saison mit ihrem
#: Startjahr, also gilt: season >= 2021 -> keine Auswaertstorregel.
#:
#: Im vorliegenden Bestand (2023-2025) ist der Wert damit KONSTANT
#: falsch. Das ist ein Befund und kein Versehen: Ein konstantes Merkmal
#: kann nichts erklaeren, und die Redundanzpruefung weist es als solches
#: aus. Die Regel steht hier trotzdem als Vertrag, weil sie fuer
#: aeltere Saisons gilt, falls der Bestand je zurueckreicht.
AWAY_GOALS_RULE_ABOLISHED_FROM = 2021

#: Woher die Neutralitaetsangabe stammt. Sichtbar statt stillschweigend.
VENUE_SOURCE_FINAL_RULE = "competition_rule_final_at_neutral_venue"
VENUE_SOURCE_HOME_AWAY = "scheduled_home_away"
VENUE_SOURCE_UNKNOWN = "unknown"


def is_league_phase(stage):
    """Rundenspiel der Gruppen- bzw. Ligaphase?"""
    return stage in LEAGUE_PHASE_STAGES


def is_knockout_stage(stage):
    """K.-o.-Runde? Das Endspiel zaehlt dazu."""
    return stage in KNOCKOUT_STAGES


def ko_round_index(stage):
    """
    Wie tief im Wettbewerb - als Ordinalzahl.

    0 fuer die Ligaphase, dann aufsteigend bis 5 fuer das Endspiel.
    Bewusst ordinal und nicht als fuenf Wahrheitswerte: Die Runden
    haben eine natuerliche Ordnung, und fuenf Indikatoren aus 119
    Partien zu schaetzen waere bei dieser Datenmenge aussichtslos.

    Rueckgabe None bei unbekannter Runde - nicht 0. Eine Null hiesse
    "Ligaphase" und waere eine Behauptung.
    """
    if is_league_phase(stage):
        return 0
    if stage in KNOCKOUT_STAGES:
        return KNOCKOUT_STAGES.index(stage) + 1
    return None


def match_type(stage, matchday):
    """
    Der kanonische Spieltyp - die EINE Stelle.

    Hergeleitet ausschliesslich aus den Metadaten der Partie selbst.
    Keine Zaehlung ueber die Paarung, kein Blick auf spaetere Partien -
    siehe Modulkopf.

    Das Endspiel wird VOR dem matchday geprueft: Es traegt je nach
    Saison None oder 0, und beides duerfte nicht als "unbekanntes Leg"
    durchgehen.
    """
    if is_league_phase(stage):
        return TYPE_LEAGUE_PHASE
    if stage == FINAL_STAGE:
        return TYPE_FINAL
    if stage not in KNOCKOUT_STAGES:
        return TYPE_UNKNOWN
    if matchday == FIRST_LEG_MATCHDAY:
        return TYPE_KO_FIRST_LEG
    if matchday == SECOND_LEG_MATCHDAY:
        return TYPE_KO_SECOND_LEG
    # Eine K.-o.-Partie ohne Legkennung. Im vorliegenden Bestand kommt
    # das nicht vor; kaeme es vor (etwa ein pandemiebedingtes
    # Einzelspiel), waere sie eine Einzelpartie - und genau das steht
    # dann auch da, statt sie stillschweigend als Hinspiel zu fuehren.
    return TYPE_KO_SINGLE


def away_goals_rule_active(season):
    """
    Galt in dieser Saison die Auswaertstorregel?

    Reiner REGELKONTEXT: Die Antwort haengt am Kalender, nicht am
    Ergebnis. Sie aus dem Spielausgang abzuleiten waere ein
    Selbstleck - deshalb bekommt diese Funktion die Saison und sonst
    nichts.
    """
    if season is None:
        return None
    return int(season) < AWAY_GOALS_RULE_ABOLISHED_FROM


def neutral_venue(stage):
    """
    Neutraler Austragungsort? Rueckgabe (neutral, quelle).

    WAS DIE QUELLE HERGIBT
    Nichts. Die football-data-Historie fuehrt zu keiner der 503 Partien
    eine Spielstaette und keine Neutralitaetsangabe. Es gibt hier also
    nichts abzulesen, nur abzuleiten - und die Ableitung wird benannt,
    statt als Messung aufzutreten.

    DIE ABLEITUNG UND IHRE GRENZE
    Das Endspiel der Champions League findet nach UEFA-Reglement an
    einem im Voraus vergebenen neutralen Ort statt; das gilt fuer alle
    drei Endspiele dieses Bestands. Jede andere Partie ist als Heim-
    oder Auswaertsspiel angesetzt.

    Die Grenze ist ausdruecklich: Eine EINZELNE verlegte Partie - ein
    Verein, der sein Stadion nicht bespielen darf, ein Ausweichort aus
    Sicherheitsgruenden - waere hier nicht erkennbar und liefe als
    normales Heimspiel mit. Ohne Spielstaettendaten laesst sich das
    nicht ausschliessen. Deshalb traegt jede Zeile ihre Herkunft mit,
    und die Herkunft heisst nicht "gemessen".

    Ein Sonderfall waere ein Endspiel im Stadion eines Finalisten. Das
    kommt vor (zuletzt 2012), im vorliegenden Bestand aber nicht. Die
    Regel bleibt trotzdem an die Runde gebunden und nicht an eine
    Jahreszahl - so faellt ein solcher Fall spaeter als Abweichung auf,
    statt lautlos richtig zu erscheinen.
    """
    if stage == FINAL_STAGE:
        return True, VENUE_SOURCE_FINAL_RULE
    if stage in LEAGUE_PHASE_STAGES or stage in KNOCKOUT_STAGES:
        return False, VENUE_SOURCE_HOME_AWAY
    return None, VENUE_SOURCE_UNKNOWN


# ---------------------------------------------------------------------------
# Aggregatstand vor dem Anpfiff
# ---------------------------------------------------------------------------

def tie_key(season, stage, home_id, away_id):
    """
    Der Schluessel einer K.-o.-Paarung - richtungsunabhaengig.

    frozenset, weil Heim und Gast im Rueckspiel vertauscht sind. Ein
    geordnetes Tupel wuerde Hin- und Rueckspiel als zwei verschiedene
    Paarungen fuehren, und der Aggregatstand waere nie zu finden.
    """
    if home_id is None or away_id is None:
        return None
    return (season, stage, frozenset((home_id, away_id)))


def first_leg_of(match, saisonpartien):
    """
    Die frueher gespielte Partie derselben Paarung - oder None.

    Gesucht wird ausschliesslich unter Partien mit FRUEHEREM Datum.
    Damit kann ein Hinspiel sein eigenes Rueckspiel nicht finden, und
    kein Rueckspiel sich selbst.

    Bei mehr als einer frueheren Partie derselben Paarung gewinnt die
    juengste - das ist die richtige Wahl, falls eine Paarung je mehr
    als zwei Partien traegt (im vorliegenden Bestand kommt das nicht
    vor). Die Mehrdeutigkeit wird vom Aufrufer gemeldet.
    """
    schluessel = tie_key(match.get("season"), match.get("stage"),
                         match.get("home_id"), match.get("away_id"))
    if schluessel is None:
        return None

    datum = match.get("date")
    if not datum:
        return None

    frueher = []
    for andere in saisonpartien:
        if andere is match:
            continue
        if andere.get("date") is None or andere["date"] >= datum:
            continue
        if tie_key(andere.get("season"), andere.get("stage"),
                   andere.get("home_id"), andere.get("away_id")) != schluessel:
            continue
        frueher.append(andere)

    if not frueher:
        return None
    frueher.sort(key=lambda m: (m["date"], str(m.get("match_id"))))
    return frueher[-1]


#: Die Felder, die aggregate_state() liefert.
AGGREGATE_FELDER = ("aggregate_goals_for", "aggregate_goals_against",
                    "aggregate_diff", "aggregate_lead")

#: Verfuegbarkeit und Tiefe. Ohne sie waere eine Null nicht von einer
#: Luecke zu unterscheiden - und genau das verlangt der Vertrag.
AGGREGATE_DEPTH_FELDER = ("aggregate_available", "aggregate_legs_played",
                          "first_leg_was_home")


def aggregate_state(match, saisonpartien, typ=None):
    """
    Der Aggregatstand VOR dem Anpfiff - aus Sicht des HEIMTEAMS.

    Rueckgabe: dict mit AGGREGATE_FELDER und AGGREGATE_DEPTH_FELDER.

    DIE PERSPEKTIVE, AUSDRUECKLICH
    Alle Werte gelten aus Sicht der Mannschaft, die IN DIESER PARTIE zu
    Hause spielt. Im Rueckspiel ist das die Mannschaft, die im Hinspiel
    auswaerts war - die Tore muessen also gedreht werden. Genau hier
    entsteht der Fehler, den niemand bemerkt: Ein Vorzeichendreher
    ergibt lauter plausible Zahlen mit der falschen Mannschaft davor.

        aggregate_goals_for      Tore des jetzigen Heimteams bisher
        aggregate_goals_against  Tore des jetzigen Gastteams bisher
        aggregate_diff           for - against
        aggregate_lead           +1 Fuehrung, 0 Gleichstand, -1 Rueckstand

    KEIN ERFUNDENER STAND
    Hinspiel, Einzelspiel und Endspiel haben keinen Vorstand. Dort
    bleiben alle vier Werte None und aggregate_available ist 0. Eine
    Null waere hier zweideutig: Sie hiesse zugleich "Gleichstand" und
    "keine Information", und beides ist nicht dasselbe.

    KEIN ZUKUNFTSWISSEN
    Gerechnet wird ausschliesslich aus Partien mit FRUEHEREM Datum
    (siehe first_leg_of). Das Zielspiel selbst geht nie ein - sein
    Ergebnis waere genau das, was vorhergesagt werden soll.
    """
    leer = {feld: None for feld in AGGREGATE_FELDER}
    leer.update({"aggregate_available": 0, "aggregate_legs_played": 0,
                 "first_leg_was_home": None})

    typ = typ or match_type(match.get("stage"), match.get("matchday"))
    if typ != TYPE_KO_SECOND_LEG:
        return leer

    hinspiel = first_leg_of(match, saisonpartien)
    if hinspiel is None:
        return leer

    heim_tore = hinspiel.get("home_goals")
    gast_tore = hinspiel.get("away_goals")
    if heim_tore is None or gast_tore is None:
        return leer

    # Die Drehung. Das jetzige Heimteam war im Hinspiel zu Gast, ausser
    # die Paarung wurde zweimal am selben Ort ausgetragen - dann stimmt
    # die Zuordnung ueber die Kennung trotzdem.
    jetzt_heim = match.get("home_id")
    war_heim = (hinspiel.get("home_id") == jetzt_heim)

    fuer = heim_tore if war_heim else gast_tore
    gegen = gast_tore if war_heim else heim_tore
    differenz = float(fuer - gegen)

    return {
        "aggregate_goals_for": float(fuer),
        "aggregate_goals_against": float(gegen),
        "aggregate_diff": differenz,
        "aggregate_lead": (1.0 if differenz > 0
                           else (-1.0 if differenz < 0 else 0.0)),
        "aggregate_available": 1,
        "aggregate_legs_played": 1,
        "first_leg_was_home": 1 if war_heim else 0,
    }


# ---------------------------------------------------------------------------
# Der vollstaendige Kontext
# ---------------------------------------------------------------------------

#: Die abgeleiteten Modellspalten des Spieltyps.
#:
#: Aus match_type gebildet und deshalb widerspruchsfrei: Es gibt keinen
#: Weg, gleichzeitig Endspiel und Hinspiel zu sein.
CONTEXT_TYPE_FELDER = ("is_knockout", "is_first_leg", "is_second_leg",
                       "is_final", "ko_round_index")

#: Der Austragungsort.
CONTEXT_VENUE_FELDER = ("neutral_venue",)

#: Der Regelkontext.
CONTEXT_RULE_FELDER = ("away_goals_rule_active",)

#: Herkunfts- und Qualitaetsangaben - niemals Modellmerkmal.
CONTEXT_QUALITAET = ("match_type", "venue_source")


def context_values(match, saisonpartien=()):
    """
    Der vollstaendige strukturelle Kontext EINER Partie.

    Die EINE Stelle, die Datensatz UND Laufzeit benutzen. Eine zweite
    Fassung derselben Herleitung waere die zuverlaessigste Art, im
    Betrieb einen anderen Kontext zu erzeugen als im Training - und ein
    vertauschtes Vorzeichen im Aggregat faellt an keiner Zahl auf.

    saisonpartien: die Partien derselben CL-Saison. Gebraucht wird
    ausschliesslich das Hinspiel eines Rueckspiels; alle spaeter
    liegenden Partien werden von first_leg_of() verworfen.
    """
    stage = match.get("stage")
    typ = match_type(stage, match.get("matchday"))
    neutral, quelle = neutral_venue(stage)

    werte = {
        "is_knockout": 1.0 if typ in KNOCKOUT_TYPES else 0.0,
        "is_first_leg": 1.0 if typ == TYPE_KO_FIRST_LEG else 0.0,
        "is_second_leg": 1.0 if typ == TYPE_KO_SECOND_LEG else 0.0,
        "is_final": 1.0 if typ == TYPE_FINAL else 0.0,
        "ko_round_index": (float(ko_round_index(stage))
                           if ko_round_index(stage) is not None else None),
        "neutral_venue": (None if neutral is None
                          else (1.0 if neutral else 0.0)),
        "away_goals_rule_active": (
            None if away_goals_rule_active(match.get("season")) is None
            else (1.0 if away_goals_rule_active(match.get("season")) else 0.0)),
        "match_type": typ,
        "venue_source": quelle,
    }
    werte.update(aggregate_state(match, saisonpartien, typ))
    return werte


def context_consistency(werte):
    """
    Die Wahrheitswerte duerfen sich nicht widersprechen.

    Rueckgabe: Liste der Verstoesse, leer wenn alles stimmt. Der
    Aufrufer entscheidet, ob er abbricht - der Datensatzbau tut es.

    Warum das ueberhaupt geprueft wird, obwohl die Werte abgeleitet
    sind: Genau deshalb. Eine Ableitung, die niemand nachprueft, ist
    eine Behauptung. Diese Pruefung kostet nichts und faengt jeden
    spaeteren Umbau ab, der die Ableitung aufweicht.
    """
    verstoesse = []
    typ = werte.get("match_type")

    legs = werte.get("is_first_leg", 0) + werte.get("is_second_leg", 0)
    if legs > 1:
        verstoesse.append("Hin- und Rueckspiel zugleich")
    if werte.get("is_final") and legs:
        verstoesse.append("Endspiel und zugleich Leg einer Paarung")
    if legs and not werte.get("is_knockout"):
        verstoesse.append("Leg einer Paarung, aber nicht K.-o.")
    if werte.get("is_final") and not werte.get("is_knockout"):
        verstoesse.append("Endspiel, aber nicht K.-o.")
    if werte.get("aggregate_available") and not werte.get("is_second_leg"):
        verstoesse.append("Aggregatstand ohne Rueckspiel")
    if werte.get("is_second_leg") and werte.get("aggregate_available"):
        if werte.get("aggregate_diff") is None:
            verstoesse.append("Aggregat verfuegbar, aber ohne Differenz")
    if not werte.get("aggregate_available"):
        for feld in AGGREGATE_FELDER:
            if werte.get(feld) is not None:
                verstoesse.append(f"{feld} gesetzt ohne verfuegbares Aggregat")
    if typ == TYPE_LEAGUE_PHASE and werte.get("is_knockout"):
        verstoesse.append("Ligaphase als K.-o. gefuehrt")
    if werte.get("neutral_venue") and typ not in (TYPE_FINAL, TYPE_UNKNOWN):
        verstoesse.append("neutraler Platz ausserhalb des Endspiels")
    return verstoesse
