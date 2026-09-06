"""
Historische UEFA-Staerke als Point-in-Time-Merkmal (V2-C4).

WAS DIE QUELLE HERGIBT - UND WAS NICHT
--------------------------------------
data/big_games/uefa_coefficients/ enthaelt je Saison die UEFA-Top-40
der VEREINE (ranking_type "uefa_club_coefficient_top40"), mit Rang,
Gesamtkoeffizient, Land und stabilen Team-IDs beider Namensraeume.
Gelesen wird ueber src/data/uefa_coefficients.py - dieses Modul parst
nichts nach.

Ein VERBANDSKOEFFIZIENT (Landeskoeffizient) liegt NICHT vor. Geprueft:
alle sechs Snapshots tragen ausschliesslich den Typ
"uefa_club_coefficient_top40" und keinen weiteren Block. Die eigentlich
gesuchte "Staerke der nationalen Liga" ist damit in diesem Bestand
nicht vorhanden.

Statt einen zu erfinden, gibt es hier zweierlei, sauber getrennt:

    uefa_club_coefficient        der offizielle Vereinskoeffizient
    uefa_country_top40_strength  ein ABGELEITETER Landeswert

Der zweite traegt "top40" im Namen, weil das seine Schwaeche ist: Er
ist die Summe der Koeffizienten aller Vereine EINES LANDES in den Top
40. Ein Land mit acht Vereinen darin bekommt dadurch mehr als eines mit
einem - unabhaengig davon, wie stark seine Liga in der Breite ist. Das
ist kein Verbandskoeffizient und wird auch nicht als einer ausgegeben.

DER STICHTAG - DER KERN DIESES MODULS
-------------------------------------
Der Koeffizient einer Saison X ist ein ueber fuenf Jahre rollierender
Wert, der die Ergebnisse der Saison X SELBST bereits enthaelt. Belegt
in den Daten: Der Snapshot 2026/27 traegt status "provisional", und
seine Werte liegen durchgehend deutlich unter denen von 2025/26 (Real
Madrid 114,5 gegen 144,5), weil die laufende Saison erst wenige Punkte
beigesteuert hat.

Damit ist snapshot(X) fuer ein Spiel IN der Saison X eine
Zukunftsinformation - er enthaelt Ergebnisse, die zum Anpfiff noch
nicht feststanden, moeglicherweise das Spiel selbst.

Die Regel dieses Moduls lautet deshalb ohne Ausnahme:

    Fuer eine Partie der Saison X gilt der Snapshot der Saison X - 1.

Dieser Wert war mit dem Ende der Saison X-1 vollstaendig und stand vor
dem ersten Spieltag der Saison X fest. Ein Test haelt die Regel fest,
und ein zweiter prueft, dass ein veraenderter Snapshot der LAUFENDEN
Saison keine historische Zeile beruehrt.

DIE DATEIEN SIND NICHT IM REPOSITORY
------------------------------------
data/big_games/ steht in .gitignore. Jeder Wert dieses Moduls kann
deshalb auf einem anderen Rechner fehlen - und das ist kein Fehlerfall,
sondern der Normalfall der CI. Fehlt der Snapshot, liefert dieses Modul
None und einen sichtbaren Grund; es wirft nie. Die Merkmale tragen ihre
Verfuegbarkeit als eigenes Feld mit, damit eine Auswertung nicht
stillschweigend ueber eine ganze fehlende Datenquelle hinwegmittelt.
"""

from src.data import uefa_coefficients as uc

#: Warum ein Wert fehlt. Sichtbar statt stillschweigend.
SOURCE_OK = "uefa_snapshot"
SOURCE_NO_SNAPSHOT = "no_snapshot_for_season"
SOURCE_NOT_RANKED = "club_not_in_top40"
SOURCE_NO_TEAM = "no_team_id"

#: Um wie viele Saisons der massgebliche Snapshot vor der Spielsaison
#: liegt. Eins - siehe Modulkopf. Bewusst eine benannte Konstante:
#: Sie ist die gesamte Point-in-Time-Zusage dieses Moduls, und sie soll
#: sich nicht als beilaeufige "season - 1" im Code verstecken.
SNAPSHOT_LAG_SEASONS = 1


def snapshot_season_for(season):
    """
    Welcher Snapshot fuer eine Spielsaison gilt.

    Die EINE Stelle, an der aus einer Spielsaison eine Snapshot-Saison
    wird. Zwei Stellen waeren zwei Gelegenheiten, den Versatz zu
    vergessen.
    """
    if season is None:
        return None
    return int(season) - SNAPSHOT_LAG_SEASONS


def _snapshot(season):
    """Der massgebliche Snapshot - oder None."""
    ziel = snapshot_season_for(season)
    if ziel is None:
        return None
    schnappschuss = uc.load_snapshot(ziel)
    return schnappschuss if schnappschuss.get("available") else None


def _by_footsim_id(schnappschuss):
    """
    Umschluesselung auf football-data-IDs.

    uefa_coefficients schluesselt auf apisports_team_id - das ist fuer
    Big Games richtig, dort kommen die Gegner von API-Sports. Der
    Datensatz hier fuehrt dagegen football-data-IDs. Die Snapshotdatei
    traegt BEIDE, deshalb braucht es keinen Crosswalk und kein Raten
    ueber Namen.

    Aufgeloest wird ausschliesslich ueber die mitgelieferte ID. Ein
    Verein ohne football-data-ID im Snapshot gilt als nicht gefuehrt -
    nicht als "vermutlich dieser aehnlich heissende".
    """
    from src.data.uefa_coefficients import load_snapshot, snapshot_path  # noqa: F401
    import json
    import os

    pfad = uc.snapshot_path(schnappschuss["season"])
    if not os.path.exists(pfad):
        return {}
    try:
        with open(pfad, "r", encoding="utf-8") as fh:
            roh = json.load(fh)
    except (OSError, ValueError):                        # pragma: no cover
        return {}

    ergebnis = {}
    for club in (roh.get("clubs") or []):
        if not isinstance(club, dict):
            continue
        fid = club.get("footsim_team_id")
        koeffizient = club.get("total_coefficient")
        if fid is None or not isinstance(koeffizient, (int, float)) \
                or isinstance(koeffizient, bool):
            continue
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            continue
        if fid in ergebnis:
            # Zwei Eintraege auf derselben ID waeren ein Datenfehler.
            # Der erste (bessere) Rang gewinnt - dieselbe Regel wie in
            # uefa_coefficients._parse_snapshot.
            continue
        ergebnis[fid] = {
            "coefficient": float(koeffizient),
            "rank": club.get("rank"),
            "country": club.get("country"),
            "club_name": club.get("club_name"),
        }
    return ergebnis


class UefaStrengthLookup:
    """
    Koeffizienten einer Spielsaison, einmal geladen.

    Eine Instanz lebt fuer die Dauer eines Datensatzbaus oder eines
    Requests - wie PitProfileRepository und aus demselben Grund: Der
    Zwischenspeicher traegt die SPIELSAISON im Schluessel, damit ein
    Wert fuer 2024 niemals eine Zeile von 2023 erreichen kann.
    """

    def __init__(self):
        self._je_saison = {}

    def _laden(self, season):
        if season in self._je_saison:
            return self._je_saison[season]

        schnappschuss = _snapshot(season)
        if schnappschuss is None:
            eintrag = {"available": False,
                       "snapshot_season": snapshot_season_for(season),
                       "by_team": {}, "by_country": {}}
        else:
            nach_team = _by_footsim_id(schnappschuss)
            nach_land = {}
            for wert in nach_team.values():
                land = wert.get("country")
                if land:
                    nach_land[land] = nach_land.get(land, 0.0) + wert["coefficient"]
            eintrag = {"available": True,
                       "snapshot_season": schnappschuss["season"],
                       "by_team": nach_team, "by_country": nach_land}

        self._je_saison[season] = eintrag
        return eintrag

    def club(self, season, team_id):
        """
        Vereinskoeffizient und Herkunft - (wert, rang, land, grund).

        Rueckgabe (None, None, None, grund), wenn kein Wert vorliegt.
        Der Grund unterscheidet ausdruecklich zwischen "kein Snapshot"
        und "Verein nicht in den Top 40": Das erste ist eine Datenluecke
        der Umgebung, das zweite eine Aussage ueber den Verein.
        """
        if team_id is None:
            return None, None, None, SOURCE_NO_TEAM

        eintrag = self._laden(season)
        if not eintrag["available"]:
            return None, None, None, SOURCE_NO_SNAPSHOT

        treffer = eintrag["by_team"].get(int(team_id))
        if treffer is None:
            return None, None, None, SOURCE_NOT_RANKED
        return (treffer["coefficient"], treffer.get("rank"),
                treffer.get("country"), SOURCE_OK)

    def country(self, season, land):
        """
        Der abgeleitete Landeswert - Summe der Top-40-Koeffizienten.

        Siehe Modulkopf: KEIN Verbandskoeffizient. None, wenn kein
        Verein dieses Landes in den Top 40 steht.
        """
        if not land:
            return None
        eintrag = self._laden(season)
        if not eintrag["available"]:
            return None
        return eintrag["by_country"].get(land)

    def snapshot_season(self, season):
        """Welcher Snapshot fuer diese Spielsaison herangezogen wurde."""
        return self._laden(season)["snapshot_season"]

    def available(self, season):
        return self._laden(season)["available"]


class NoUefaLookup:
    """
    Ein Lookup, der nie etwas findet - und nie eine Datei anfasst.

    WOZU DAS NOETIG IST
    data/big_games/ steht in .gitignore. Der Datensatzbau muss aber aus
    einem frischen Checkout reproduzierbar sein; ein Test haelt das
    ausdruecklich fest ("es wird nur aus data/historical gelesen").
    Wuerde der Datensatz die UEFA-Dateien standardmaessig lesen,
    entstuende auf jedem anderen Rechner ein anderer Bestand - und der
    Unterschied waere unsichtbar, weil fehlende Werte nun einmal wie
    fehlende Werte aussehen.

    Deshalb ist die UEFA-Quelle ausdruecklich abwaehlbar, und das
    Abwaehlen ist der Standard. Wer sie einschaltet, weiss, dass sein
    Bestand ohne die privaten Dateien nicht nachbaubar ist - das
    Ergebnisartefakt haelt es unter uefa_data_available fest.

    Die gemeldete Herkunft ist SOURCE_NO_SNAPSHOT und nicht etwa ein
    eigener Grund: Aus Sicht der Zeile ist die Lage genau dieselbe wie
    auf einem Rechner ohne die Dateien.
    """

    def club(self, season, team_id):
        return None, None, None, SOURCE_NO_SNAPSHOT

    def country(self, season, land):
        return None

    def snapshot_season(self, season):
        return snapshot_season_for(season)

    def available(self, season):
        return False


#: Die Felder, die uefa_values() liefert.
UEFA_FELDER = ("uefa_club_coefficient", "uefa_club_rank",
               "uefa_country_top40_strength")

#: Die Herkunftsangabe. Qualitaetsfeld, kein Modellmerkmal.
UEFA_QUALITAET = ("uefa_source",)


def uefa_values(lookup, season, team_id):
    """
    Die UEFA-Merkmale EINER Mannschaft - die EINE Stelle.

    Rueckgabe: dict mit UEFA_FELDER und UEFA_QUALITAET.

    Der Landeswert kommt ueber das Land, das der Snapshot selbst fuer
    diesen Verein fuehrt. Ist der Verein nicht in den Top 40, ist auch
    sein Land unbekannt - dann bleibt der Landeswert None statt ueber
    eine Zuordnungstabelle geraten zu werden, die es hier nicht gibt.
    """
    koeffizient, rang, land, grund = lookup.club(season, team_id)
    return {
        "uefa_club_coefficient": koeffizient,
        "uefa_club_rank": float(rang) if rang is not None else None,
        "uefa_country_top40_strength": lookup.country(season, land),
        "uefa_source": grund,
    }
