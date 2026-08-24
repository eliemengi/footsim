"""
Player Importance: Wie gross ist die Rolle eines Spielers in seinem Team?

IMPORTANCE IST NICHT QUALITY
----------------------------
Zwei verschiedene Fragen, die oft verwechselt werden:

    Importance   Wie viel Mannschaft haengt an diesem Spieler?
    Quality      Wie gut ist er, verglichen mit seiner Position?

Ein solider Stammverteidiger mit 3.000 Minuten hat hohe Importance und
mittlere Quality. Ein hochbegabter Joker mit 300 Minuten und glaenzenden
per-90-Werten hat hohe Quality und geringe Importance - faellt er aus,
faellt wenig aus.

Genau deshalb traegt die ROLLE hier das meiste Gewicht (siehe
ROLE_WEIGHT). Wuerde die Leistung dominieren, waere das Ergebnis eine
zweite, schlechtere Quality-Bewertung. Quality steht in
src/features/player_quality.py.

POSITIONSGERECHT
----------------
Der Beitrag eines Spielers wird an dem gemessen, wofuer seine Position
da ist. Torhueter und Verteidiger ueber Tore zu bewerten waere der
klassische Fehler des Vorgaengermodells (squad_impact.py bewertete
ausschliesslich Torschuetzen).

    Torwart       Paraden, Gegentore, Minuten, Startelf
    Verteidigung  Zweikaempfe, Tacklings, Interceptions, Blocks
    Mittelfeld    Torvorlagen, Schluesselpaesse, Paesse, Dribblings
    Angriff       Tore, Vorlagen, Schuesse, Torbeteiligung

WAS ES NICHT GIBT
-----------------
Der Spielerpool fuehrt team_name, aber weder team_id noch die
Zugehoerigkeit ZUR DAMALIGEN ZEIT (siehe player_identity). Der
teambezogene Anteil - "wie viel Prozent der Teamtore" - laesst sich
deshalb nur fuer die AKTUELLE Saison sauber bilden. Fehlt er, wird die
Importance allein aus der Rolle gebildet und als "partial"
gekennzeichnet. Nicht als Null, nicht geschaetzt.
"""

from src.data.percentile_engine import current_weight


#: Wie sich Importance zusammensetzt.
#:
#: Die Rolle wiegt fast doppelt so schwer wie der Beitrag. Das ist die
#: zentrale Festlegung dieses Moduls und folgt direkt aus der
#: Unterscheidung im Modulkopf: Wer ausfaellt, reisst ein Loch in der
#: Groesse seiner Rolle, nicht in der Groesse seiner Statistik.
ROLE_WEIGHT = 0.65
CONTRIBUTION_WEIGHT = 0.35

#: Innerhalb der Rolle: Minuten vor Startelfeinsaetzen.
#:
#: Beide sagen Aehnliches, aber Minuten sind feiner. Startelfeinsaetze
#: kommen ergaenzend dazu, weil ein Spieler mit 60 Startelfminuten je
#: Spiel eine andere Rolle hat als einer, der immer in der 60. Minute
#: eingewechselt wird - bei gleicher Minutenzahl.
MINUTES_WEIGHT = 0.60
STARTS_WEIGHT = 0.40

#: Ab welcher Minutenzahl aktuelle Daten voll zaehlen.
#:
#: Uebernommen aus percentile_engine.current_weight (m/(m+k), k=450) -
#: derselbe Mechanismus wie bei den Perzentilen. Bewusst KEINE harte
#: Sperre: Ein Spieler mit 200 Minuten bekommt einen Wert, der zu 31 %
#: auf der laufenden und zu 69 % auf der Referenzsaison beruht.
#: Eine Sperre bei 450 Minuten wuerde im August die halbe Liga
#: unsichtbar machen.
#:
#: Der Wert wird nicht hier gesetzt, sondern von current_weight geerbt.

#: Metriken je Positionsgruppe, absteigend nach Aussagekraft.
#:
#: Alle Namen stammen aus den tatsaechlich vorhandenen Poolfeldern
#: (metrics_by_scope). Es steht hier nichts, was der Anbieter nicht
#: liefert - eine erfundene Metrik waere spaeter eine erfundene Null.
POSITION_METRICS = {
    "Goalkeeper": (
        ("saves_per90", 1.0),
        ("conceded_per90", -0.6),        # weniger ist besser
        ("pass_accuracy_pct", 0.2),
    ),
    "Defender": (
        ("tackles_per90", 0.8),
        ("interceptions_per90", 0.8),
        ("blocks_per90", 0.5),
        ("duels_won_pct", 0.6),
    ),
    "Midfielder": (
        ("key_passes_per90", 0.9),
        ("assists_per90", 0.8),
        ("passes_per90", 0.5),
        ("dribbles_success_per90", 0.4),
    ),
    "Attacker": (
        ("goals_per90", 1.0),
        ("assists_per90", 0.7),
        ("shots_per90", 0.5),
        ("goal_contributions_per90", 0.8),
    ),
}

#: Metriken, bei denen ein kleinerer Wert besser ist.
INVERSE_METRICS = frozenset({"conceded_per90"})

#: Wertebereich der Importance. Dokumentiert und geprueft.
IMPORTANCE_MIN = 0.0
IMPORTANCE_MAX = 1.0


def _safe(metrics, name):
    """Metrikwert oder None. Ein fehlender Wert ist NICHT null."""
    if not isinstance(metrics, dict):
        return None
    wert = metrics.get(name)
    if wert is None:
        return None
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _scope(player, scope="league"):
    """Die Metriken einer Wettbewerbsebene."""
    return (player.get("metrics_by_scope") or {}).get(scope) or {}


def position_group(player):
    """Positionsgruppe des Spielers, oder None wenn unbekannt."""
    pos = player.get("position")
    return pos if pos in POSITION_METRICS else None


def role_score(minutes, lineups, appearances, possible_minutes,
               possible_matches):
    """
    Rollenanteil eines Spielers: Minuten und Startelfeinsaetze.

    possible_minutes / possible_matches: was in dieser Liga und Saison
    ueberhaupt moeglich war. Kommt aus der Zahl der tatsaechlich
    ausgetragenen Spieltage, nicht aus einer angenommenen 38 - die
    Bundesliga hat 34, die Ligue 1 seit 2023/24 ebenfalls.

    Rueckgabe: (score, minutes_share, starts_share)
    """
    if not possible_minutes or possible_minutes <= 0:
        return None, None, None

    minutes_share = min(1.0, (minutes or 0) / float(possible_minutes))

    if possible_matches and possible_matches > 0:
        starts_share = min(1.0, (lineups or 0) / float(possible_matches))
    else:
        starts_share = None

    if starts_share is None:
        # Ohne Startelfdaten bleibt der Minutenanteil allein stehen -
        # nicht mit einer angenommenen Null vermischt.
        return minutes_share, minutes_share, None

    score = MINUTES_WEIGHT * minutes_share + STARTS_WEIGHT * starts_share
    return score, minutes_share, starts_share


def contribution_score(player, scope="league", peer_maxima=None):
    """
    Positionsgerechter Beitrag, normiert an der Vergleichsgruppe.

    peer_maxima: {position: {metrik: hoechstwert}} - die Bezugsgroesse.
                 Ohne sie gibt es keinen Massstab und damit keinen Wert;
                 einen absoluten per-90-Wert als "Beitrag" auszugeben
                 waere skalenlos.

    Rueckgabe: (score_oder_None, komponenten, verwendete_metriken)
    """
    gruppe = position_group(player)
    if not gruppe or not peer_maxima:
        return None, {}, []

    maxima = peer_maxima.get(gruppe) or {}
    metrics = _scope(player, scope)

    summe = 0.0
    gewicht_summe = 0.0
    komponenten = {}
    verwendet = []

    for name, gewicht in POSITION_METRICS[gruppe]:
        roh = _safe(metrics, name)
        obergrenze = maxima.get(name)
        if roh is None or not obergrenze:
            # Fehlende Metrik geht NICHT als Null ein, sondern faellt aus
            # der Gewichtung heraus. Sonst wuerde ein Spieler bestraft,
            # weil der Anbieter etwas nicht fuehrt.
            continue

        if name in INVERSE_METRICS:
            # Weniger ist besser: an der Obergrenze gespiegelt.
            anteil = max(0.0, 1.0 - (roh / obergrenze)) if obergrenze else 0.0
        else:
            anteil = max(0.0, min(1.0, roh / obergrenze))

        betrag = abs(gewicht)
        summe += anteil * betrag
        gewicht_summe += betrag
        komponenten[name] = round(anteil, 4)
        verwendet.append(name)

    if gewicht_summe <= 0:
        return None, {}, []
    return summe / gewicht_summe, komponenten, verwendet


def build_peer_maxima(pool_players, scope="league", quantile=0.95):
    """
    Bezugsgroessen je Positionsgruppe aus dem Pool selbst.

    Bewusst das 95. Perzentil und nicht das Maximum: Ein einzelner
    Ausreisser - etwa ein Torwart mit zwei Einsaetzen und
    aussergewoehnlicher Paradenquote - wuerde sonst die Skala aller
    anderen zusammendruecken.
    """
    gesammelt = {}
    for spieler in pool_players or []:
        gruppe = position_group(spieler)
        if not gruppe:
            continue
        metrics = _scope(spieler, scope)
        # Nur Spieler mit nennenswerter Spielzeit praegen die Skala.
        if (metrics.get("minutes") or 0) < 450:
            continue
        for name, _ in POSITION_METRICS[gruppe]:
            wert = _safe(metrics, name)
            if wert is not None:
                gesammelt.setdefault(gruppe, {}).setdefault(name, []).append(wert)

    maxima = {}
    for gruppe, metriken in gesammelt.items():
        maxima[gruppe] = {}
        for name, werte in metriken.items():
            if not werte:
                continue
            werte.sort()
            index = min(len(werte) - 1, int(len(werte) * quantile))
            wert = werte[index]
            if wert > 0:
                maxima[gruppe][name] = wert
    return maxima


def league_capacity(league_code, season):
    """
    Wie viele Spiele und Minuten waren in dieser Liga und Saison moeglich?

    Aus der lokalen Historie gezaehlt, nicht angenommen. Rueckgabe:
    (spiele_je_team, minuten_je_team). Ohne Datei: (None, None) - dann
    gibt es keinen Minutenanteil und die Importance bleibt unbestimmt.
    """
    from src.data.historical_loader import LEAGUE_CODES, load_season

    api_code = LEAGUE_CODES.get(league_code)
    if not api_code:
        return None, None

    payload = load_season(api_code, season)
    if not payload:
        return None, None

    je_team = {}
    for match in (payload.get("matches") or []):
        if match.get("home_goals") is None:
            continue
        for schluessel in ("home_id", "away_id"):
            tid = match.get(schluessel)
            if tid is not None:
                je_team[tid] = je_team.get(tid, 0) + 1

    if not je_team:
        return None, None

    # Median statt Maximum: ein Team mit Nachholspielen soll die
    # Bezugsgroesse nicht verschieben.
    werte = sorted(je_team.values())
    spiele = werte[len(werte) // 2]
    return spiele, spiele * 90


def player_importance(player, peer_maxima, possible_minutes, possible_matches,
                      scope="league", reference_importance=None,
                      reference_season=None):
    """
    Importance eines Spielers.

    reference_importance: Importance derselben Person aus der letzten
        nutzbaren Saison. Sie traegt den Wert, solange die laufende
        Saison noch wenig Minuten hat - dieselbe Stabilisierung wie bei
        den Perzentilen (GO 1.1).

    Rueckgabe: dict mit allen geforderten Feldern. Bei fehlender
    Grundlage steht dort None und data_quality "unavailable" - nie eine
    erfundene Null.
    """
    metrics = _scope(player, scope)
    minuten = metrics.get("minutes") or 0
    gruppe = position_group(player)

    rolle, minutes_share, starts_share = role_score(
        minuten, metrics.get("lineups"), metrics.get("appearances"),
        possible_minutes, possible_matches)

    beitrag, komponenten, verwendet = contribution_score(
        player, scope, peer_maxima)

    gewicht = current_weight(minuten)

    if rolle is None:
        aktuell = None
    elif beitrag is None:
        # Nur die Rolle ist bekannt. Sie allein ist eine ehrliche,
        # wenn auch groebere Aussage - der Beitrag wird NICHT mit null
        # eingesetzt, das wuerde jeden Spieler kuenstlich abwerten.
        aktuell = rolle
    else:
        aktuell = ROLE_WEIGHT * rolle + CONTRIBUTION_WEIGHT * beitrag

    if aktuell is None and reference_importance is None:
        wert = None
        qualitaet = "unavailable"
    elif aktuell is None:
        wert = reference_importance
        qualitaet = "fallback"
    elif reference_importance is None:
        wert = aktuell
        # Ohne Referenz ist ein Wert aus wenigen Minuten wackelig.
        qualitaet = "complete" if gewicht >= 0.5 else "partial"
    else:
        wert = gewicht * aktuell + (1.0 - gewicht) * reference_importance
        qualitaet = "complete"

    if wert is not None:
        wert = max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, wert))
        wert = round(wert, 6)

    if beitrag is None and qualitaet == "complete":
        # Rolle vollstaendig, Beitrag nicht - das ist "teilweise".
        qualitaet = "partial"

    return {
        "player_id": player.get("player_id"),
        "player_name": player.get("name"),
        "position_group": gruppe,
        "player_importance": wert,
        "importance_components": {
            "role": round(rolle, 6) if rolle is not None else None,
            "contribution": round(beitrag, 6) if beitrag is not None else None,
            "contribution_detail": komponenten,
        },
        "importance_quality": qualitaet,
        "minutes": minuten,
        "minutes_share": round(minutes_share, 6) if minutes_share is not None else None,
        "starts_share": round(starts_share, 6) if starts_share is not None else None,
        "current_weight": round(gewicht, 6),
        "reference_season": reference_season,
        "metrics_used": verwendet,
        "data_quality": qualitaet,
        "source": "apisports_player_pool",
    }


def build_league_importance(pool_players, league_code, season,
                            reference_players=None, reference_season=None,
                            scope="league"):
    """
    Importance aller Spieler einer Liga und Saison.

    Rueckgabe: {"players": {player_id: importance}, "coverage": {...}}

    reference_players: der Pool der letzten nutzbaren Saison. Aus ihm
    wird je Spieler die Vorjahres-Importance gebildet und zur
    Stabilisierung herangezogen.
    """
    spiele, minuten = league_capacity(league_code, season)
    maxima = build_peer_maxima(pool_players, scope)

    referenz = {}
    if reference_players:
        ref_spiele, ref_minuten = league_capacity(league_code, reference_season)
        ref_maxima = build_peer_maxima(reference_players, scope)
        for spieler in reference_players:
            pid = spieler.get("player_id")
            if pid is None:
                continue
            eintrag = player_importance(spieler, ref_maxima, ref_minuten,
                                        ref_spiele, scope)
            if eintrag["player_importance"] is not None:
                referenz[int(pid)] = eintrag["player_importance"]

    ergebnis = {}
    zaehler = {"complete": 0, "partial": 0, "fallback": 0, "unavailable": 0}
    je_position = {}

    for spieler in pool_players or []:
        pid = spieler.get("player_id")
        if pid is None:
            continue
        eintrag = player_importance(
            spieler, maxima, minuten, spiele, scope,
            reference_importance=referenz.get(int(pid)),
            reference_season=reference_season if int(pid) in referenz else None)
        ergebnis[int(pid)] = eintrag
        zaehler[eintrag["importance_quality"]] = \
            zaehler.get(eintrag["importance_quality"], 0) + 1
        gruppe = eintrag["position_group"] or "unknown"
        je_position[gruppe] = je_position.get(gruppe, 0) + 1

    return {
        "league": league_code,
        "season": season,
        "reference_season": reference_season,
        "players": ergebnis,
        "coverage": {
            "players": len(ergebnis),
            "by_quality": zaehler,
            "by_position": je_position,
            "possible_matches": spiele,
            "possible_minutes": minuten,
            "peer_groups": sorted(maxima),
            "reference_players": len(referenz),
        },
    }
