"""
Historische Kaderzugehoerigkeit, Transfers und Kaderstaerke (V2-C7).

DIE ZWEI INFORMATIONSKLASSEN - DER KERN DIESES MODULS
-----------------------------------------------------
Nicht alles, was ueber einen Kader bekannt ist, war zu einem
historischen Spieltag bekannt. C7 trennt das technisch, nicht nur im
Text:

    Klasse A - historisch rekonstruierbar
        Transferereignisse. Jedes traegt ein Datum; 84.943 lokal
        vorhandene Ereignisse zu 24.404 Spielern. Ein Wechsel vom
        3. September 2024 war am 20. September 2024 bekannt, und das
        laesst sich belegen.

        Ebenso die Spielerstatistiken ABGESCHLOSSENER Vorsaisons: Was
        ein Spieler in der Saison 2023/24 geleistet hat, stand im
        September 2024 fest.

    Klasse B - erst seit V2-C6 beobachtbar
        Kader- und Verfuegbarkeitssnapshots. Sie entstehen ab dem Tag,
        an dem der Sammler laeuft. Vor archive_window().usable_from
        existiert nichts, und dieses Nichts laesst sich nicht
        nachtraeglich fuellen.

Die Trennung ist als Codevertrag gebaut: data_class() sagt zu jeder
Merkmalsfamilie, welcher Klasse sie angehoert, und
class_b_is_usable() entscheidet anhand des tatsaechlichen Archivs, ob
sie ueberhaupt bewertbar ist. Ein Merkmal der Klasse B auf einen
Spieltag anzuwenden, der vor dem ersten Snapshot liegt, ist damit kein
Versehen mehr, sondern unmoeglich.

WAS DER BESTAND NICHT HERGIBT - NACHGEMESSEN, NICHT VERMUTET
------------------------------------------------------------
1. Der Spielerpool (data/player_pool/) traegt KEIN Datums- und kein
   Spieltagsfeld. Er ist eine Saisonaggregation. Fuer ein Spiel MITTEN
   in Saison S waere er Saisonendwissen - deshalb gilt hier
   ausnahmslos: nur Saisons <= S-1.

2. Der Pool traegt keine team_id, nur team_name. Eine Zuordnung ueber
   den Namen waere genau die unsichere Identitaet, die dieses Projekt
   an anderer Stelle teuer gelernt hat. Die Verknuepfung laeuft
   deshalb ausschliesslich ueber player_id - denselben Namensraum, den
   auch die Transfers benutzen (85,6 % Ueberschneidung, nachgemessen).

3. Die aus Transfers ABGELEITETE Kaderzugehoerigkeit ueberzaehlt. Sie
   sieht Zugaenge, aber nicht jedes Ausscheiden: Vertragsenden,
   Karriereenden und nicht gemeldete Abgaenge fehlen. Nachgemessen:
   Median 41 abgeleitete Spieler gegen rund 30 in einem echten
   Einsatzkader.

   Deshalb ist sie hier eine OBERGRENZE und ausdruecklich KEINE
   Kadergroesse. Sie wird als Diagnose gefuehrt und nicht als
   Modellmerkmal - eine Zahl, die um ein Drittel danebenliegt, waere
   als "Kadertiefe" schlicht falsch.

WAS STATTDESSEN TRAEGT
----------------------
Die Transferereignisse selbst. Sie brauchen keine Mitgliedschafts-
ableitung: "Wer kam in den letzten 365 Tagen, wer ging, und wie stark
waren diese Spieler in ihrer letzten abgeschlossenen Saison" ist
vollstaendig aus datierten Ereignissen und abgeschlossenen Saisons
beantwortbar - ohne eine einzige Annahme darueber, wer sonst noch im
Kader steht.
"""

from datetime import timedelta

from src.features.transfer_events import parse_date

#: Fassung des C7-Datenvertrags.
#:
#: 1  V2-C7: Erstfassung. Transferfenster, Vorsaisonstaerke,
#:    abgeleitete Mitgliedschaft als Obergrenze, Klassentrennung.
SQUAD_HISTORY_VERSION = 1

#: Die beiden Informationsklassen.
CLASS_A_HISTORICAL = "A_historically_reconstructible"
CLASS_B_SNAPSHOT_ONLY = "B_observable_since_c6"

#: Welche Merkmalsfamilie welcher Klasse angehoert.
#:
#: Diese Zuordnung ist der Vertrag. Sie steht hier und nicht im README,
#: damit ein Test sie pruefen kann.
FAMILY_DATA_CLASS = {
    "transfer_volume": CLASS_A_HISTORICAL,
    "transfer_balance": CLASS_A_HISTORICAL,
    "transfer_strength": CLASS_A_HISTORICAL,
    "squad_membership": CLASS_A_HISTORICAL,
    "squad_snapshot": CLASS_B_SNAPSHOT_ONLY,
    "availability_impact": CLASS_B_SNAPSHOT_ONLY,
}

#: Wie weit zurueck ein Transfer als "juengst" gilt.
#:
#: 365 Tage decken genau ein Transferjahr ab - Sommer- und
#: Winterperiode. Kuerzer verlöre die Sommerzugaenge einer
#: Ruecklaufsaison, laenger vermengte zwei Kaderumbauten.
TRANSFER_WINDOW_DAYS = 365

#: Ein zweites, engeres Fenster fuer den juengsten Umbau.
TRANSFER_RECENT_DAYS = 120

#: Mindestminuten der Vorsaison, damit ein Spieler in die
#: Staerkerechnung eingeht.
#:
#: Unter 270 Minuten (drei Spielen) ist eine Bewertung kein Mittelwert,
#: sondern ein Einzelereignis - und die Anbieterbewertung schwankt bei
#: Kurzeinsaetzen stark.
MIN_PRIOR_MINUTES = 270

#: Welcher Leistungswert benutzt wird.
#:
#: Die Anbieterbewertung ("rating") ist die einzige Groesse, die ueber
#: alle Positionen vergleichbar ist. Tore je 90 Minuten waeren fuer
#: einen Innenverteidiger sinnlos, Zweikampfquoten fuer einen Stuermer.
#: Sie ist eine ANBIETERMEINUNG und keine Messung - deshalb steht sie
#: hier mit Namen und wird nicht als "Staerke" ausgegeben.
STRENGTH_METRIC = "rating"

#: Aus welchem Bereich die Vorsaisonwerte stammen.
STRENGTH_SCOPE = "club_all"


# ---------------------------------------------------------------------------
# Klassenvertrag
# ---------------------------------------------------------------------------

def data_class(family):
    """
    Welcher Informationsklasse gehoert diese Merkmalsfamilie an?

    Wirft bei unbekannter Familie. Ein stillschweigendes "vermutlich
    Klasse A" waere genau die Annahme, die dieser Vertrag verhindern
    soll.
    """
    if family not in FAMILY_DATA_CLASS:
        raise ValueError(
            f"unbekannte Merkmalsfamilie: {family!r} - bekannt sind "
            f"{sorted(FAMILY_DATA_CLASS)}")
    return FAMILY_DATA_CLASS[family]


def class_b_is_usable(cutoff, archive_reader=None, kinds=None):
    """
    Darf eine Klasse-B-Familie fuer diesen Stichtag benutzt werden?

    Rueckgabe: (bool, begruendung).

    Die Antwort haengt am TATSAECHLICHEN Archiv, nicht an einer
    Zusicherung. Liegt der frueheste Snapshot nach dem Stichtag, gibt
    es fuer diesen Spieltag keine Beobachtung - und ein spaeter
    erhobener Stand rueckwirkend anzuwenden waere erfundene Historie.
    """
    from src.data import availability_snapshots as av

    if archive_reader is None:
        from src.data import snapshot_reader as archive_reader

    kinds = kinds or (av.KIND_SQUAD, av.KIND_AVAILABILITY)
    cutoff_text = cutoff.isoformat() if hasattr(cutoff, "isoformat") \
        else str(cutoff)

    for art in kinds:
        fenster = archive_reader.archive_window(art)
        beginn = fenster.get("usable_from")
        if not beginn:
            return False, (f"kein Snapshot der Art {art!r} vorhanden - "
                           f"die Sammlung hat noch nicht begonnen")
        if beginn >= cutoff_text:
            return False, (f"fruehester {art}-Snapshot ({beginn}) liegt "
                           f"nicht vor dem Stichtag ({cutoff_text})")
    return True, "Snapshothistorie reicht vor den Stichtag zurueck"


# ---------------------------------------------------------------------------
# Abgeleitete Kaderzugehoerigkeit
# ---------------------------------------------------------------------------

def derived_membership(team_id, cutoff, transfer_index):
    """
    Wer gehoerte diesem Verein zum Stichtag - abgeleitet aus Transfers.

    Regel: Fuer jeden Spieler zaehlt sein LETZTER Transfer strikt vor
    dem Stichtag. Fuehrte er zu diesem Verein, gilt der Spieler als
    zugehoerig; fuehrte er weg, nicht.

    OBERGRENZE, NICHT KADERGROESSE
    Diese Menge ueberzaehlt, und zwar systematisch. Sie sieht jeden
    Zugang, aber nur die als Transfer GEMELDETEN Abgaenge - ein
    auslaufender Vertrag, ein Karriereende oder ein nicht erfasster
    Wechsel hinterlassen keinen Eintrag, und der Spieler bleibt hier
    ewig im Kader stehen. Nachgemessen: Median 41 gegen rund 30 in
    einem echten Einsatzkader.

    Deshalb liefert diese Funktion ausdruecklich eine Obergrenze. Sie
    ist als Diagnose brauchbar und als Kadertiefe nicht.

    Rueckgabe: {player_id: letzter_transfer}
    """
    grenze = parse_date(cutoff)
    if grenze is None or team_id is None:
        return {}

    letzter = {}
    for eintrag in transfer_index.get(team_id, []):
        datum = parse_date(eintrag["date"])
        if datum is None or datum >= grenze:
            continue
        pid = eintrag["player_id"]
        vorhanden = letzter.get(pid)
        if vorhanden is None or datum > parse_date(vorhanden["date"]):
            letzter[pid] = eintrag

    return {pid: e for pid, e in letzter.items()
            if e["to_team_id"] == team_id}


# ---------------------------------------------------------------------------
# Transferfenster
# ---------------------------------------------------------------------------

def transfer_window(team_id, cutoff, transfer_index,
                    window_days=TRANSFER_WINDOW_DAYS):
    """
    Zu- und Abgaenge eines Vereins im Fenster vor dem Stichtag.

    Der belastbarste Teil von C7: Hier wird nichts abgeleitet. Jedes
    Ereignis traegt ein Datum, und es zaehlt genau dann, wenn dieses
    Datum strikt vor dem Stichtag und innerhalb des Fensters liegt.

    Rueckgabe: (zugaenge, abgaenge) - je Liste von Transfereintraegen.
    """
    grenze = parse_date(cutoff)
    if grenze is None or team_id is None:
        return [], []

    frueheste = grenze - timedelta(days=window_days)

    zugaenge, abgaenge = [], []
    for eintrag in transfer_index.get(team_id, []):
        datum = parse_date(eintrag["date"])
        if datum is None or datum >= grenze or datum < frueheste:
            continue
        if eintrag["to_team_id"] == team_id:
            zugaenge.append(eintrag)
        elif eintrag["from_team_id"] == team_id:
            abgaenge.append(eintrag)

    schluessel = (lambda e: (e["date"], e["player_id"]))
    return sorted(zugaenge, key=schluessel), sorted(abgaenge, key=schluessel)


# ---------------------------------------------------------------------------
# Vorsaisonstaerke
# ---------------------------------------------------------------------------

class PriorSeasonStrength:
    """
    Leistungswerte aus ABGESCHLOSSENEN Saisons - der Stichtagsschutz.

    DER VERTRAG IN EINEM SATZ
    Fuer ein Spiel der Saison S zaehlen ausschliesslich Poolsaisons
    <= S-1.

    WARUM SO STRENG
    Der Pool traegt kein Datum - nachgemessen, kein einziges Feld mit
    "date" oder "matchday". Er ist eine Saisonaggregation: 14 Einsaetze,
    578 Minuten, Bewertung 6,61. Fuer ein Spiel im Oktober der Saison S
    waere das die Statistik einer Saison, die im Mai darauf endet - also
    Wissen aus der Zukunft, und zwar in genau der Groesse, die man
    vorhersagen will.

    Die Vorsaison ist dagegen sauber: Sie war im Sommer abgeschlossen,
    lange bevor die neue begann.

    Ein Zwischenspeicher je (saison) - eine Poolsaison wird einmal
    gelesen.
    """

    def __init__(self, pool_dir=None, leagues=None):
        self.pool_dir = pool_dir
        self.leagues = leagues
        self._je_saison = {}

    def _laden(self, season):
        if season in self._je_saison:
            return self._je_saison[season]

        import glob
        import json
        import os

        if self.pool_dir is None:
            from src.data.player_pool import POOL_DIR

            verzeichnis = POOL_DIR
        else:
            verzeichnis = self.pool_dir

        werte = {}
        muster = os.path.join(verzeichnis, f"pool_*_{int(season)}.json")
        for pfad in sorted(glob.glob(muster)):
            if self.leagues is not None:
                liga = os.path.basename(pfad)[len("pool_"):-len(".json")]
                liga = liga.rsplit("_", 1)[0]
                if liga not in self.leagues:
                    continue
            try:
                with open(pfad, "r", encoding="utf-8") as handle:
                    inhalt = json.load(handle)
            except (OSError, ValueError):
                continue

            for spieler in (inhalt.get("players") or []):
                pid = spieler.get("player_id")
                if pid is None:
                    continue
                bereich = (spieler.get("metrics_by_scope") or {}).get(
                    STRENGTH_SCOPE) or {}
                minuten = bereich.get("minutes")
                bewertung = bereich.get(STRENGTH_METRIC)
                if minuten is None:
                    continue
                # Bei mehreren Eintraegen desselben Spielers gewinnt der
                # mit mehr Minuten - ein Wechsler steht in zwei
                # Ligadateien, und die Saison, in der er mehr gespielt
                # hat, beschreibt ihn besser.
                vorhanden = werte.get(int(pid))
                if vorhanden is not None and vorhanden["minutes"] >= minuten:
                    continue
                werte[int(pid)] = {
                    "minutes": float(minuten),
                    "rating": (float(bewertung)
                               if isinstance(bewertung, (int, float))
                               else None),
                    "appearances": bereich.get("appearances"),
                    "lineups": bereich.get("lineups"),
                    "position": spieler.get("position"),
                    "season": int(season),
                }

        self._je_saison[season] = werte
        return werte

    def for_player(self, player_id, match_season, seasons_back=2):
        """
        Der juengste ABGESCHLOSSENE Saisonwert eines Spielers.

        Gesucht wird ab match_season - 1 rueckwaerts. Findet sich
        nichts, bleibt es None: Ein Spieler ohne Vorsaisondaten ist
        unbekannt, nicht schwach.
        """
        if player_id is None or match_season is None:
            return None
        for versatz in range(1, seasons_back + 1):
            saison = int(match_season) - versatz
            treffer = self._laden(saison).get(int(player_id))
            if treffer is not None:
                return treffer
        return None

    def available_seasons(self):
        return sorted(self._je_saison)


def strength_of_group(player_ids, match_season, strength_source,
                      min_minutes=MIN_PRIOR_MINUTES):
    """
    Die Vorsaisonstaerke einer Spielergruppe.

    Rueckgabe: dict mit Mittelwert, Bestwert, Zahl der bewertbaren und
    der unbewertbaren Spieler.

    Nur Spieler mit mindestens min_minutes gehen in die Bewertung ein.
    Wer weniger gespielt hat, traegt eine Bewertung, die auf zwei
    Kurzeinsaetzen beruht - das ist kein Leistungsmass.

    Ohne einen einzigen bewertbaren Spieler bleiben die Werte None.
    Eine Null hiesse "durchweg schwach" und waere die schaerfste
    denkbare Falschaussage ueber eine Gruppe, ueber die nichts bekannt
    ist.
    """
    bewertungen, minuten = [], []
    ohne_wert = 0

    for pid in player_ids or ():
        eintrag = strength_source.for_player(pid, match_season)
        if eintrag is None or eintrag["rating"] is None \
                or eintrag["minutes"] < min_minutes:
            ohne_wert += 1
            continue
        bewertungen.append(eintrag["rating"])
        minuten.append(eintrag["minutes"])

    if not bewertungen:
        return {"count": len(player_ids or ()), "rated": 0,
                "unrated": ohne_wert, "mean_rating": None,
                "max_rating": None, "mean_minutes": None}

    return {
        "count": len(player_ids or ()),
        "rated": len(bewertungen),
        "unrated": ohne_wert,
        "mean_rating": sum(bewertungen) / len(bewertungen),
        "max_rating": max(bewertungen),
        "mean_minutes": sum(minuten) / len(minuten),
    }


# ---------------------------------------------------------------------------
# Der vollstaendige C7-Zustand einer Seite
# ---------------------------------------------------------------------------

#: Merkmale, die der Bestand traegt.
TRANSFER_VOLUME_FELDER = ("arrivals_365d", "departures_365d",
                          "arrivals_120d", "departures_120d",
                          "loans_in_365d", "loans_out_365d")
TRANSFER_BALANCE_FELDER = ("net_transfers_365d", "net_transfers_120d")
TRANSFER_STRENGTH_FELDER = ("arrivals_mean_rating", "departures_mean_rating",
                            "arrivals_minus_departures_rating")

#: Diagnose - NIEMALS Modellmerkmal. Siehe Modulkopf zur Ueberzaehlung.
MEMBERSHIP_DIAGNOSE = ("derived_membership_upper_bound",
                       "arrivals_rated", "departures_rated",
                       "transfer_data_available")

#: Qualitaets- und Herkunftsangaben.
SQUAD_HISTORY_QUALITAET = ("squad_history_source", "prior_season_used")

#: Warum keine Werte vorliegen.
SOURCE_OK = "transfers_and_prior_season"
SOURCE_NO_CROSSWALK = "no_apisports_team_id"
SOURCE_NO_TRANSFERS = "no_transfer_history_for_team"


def squad_history_values(team_id_apisports, match_season, cutoff,
                         transfer_index, strength_source):
    """
    Der vollstaendige C7-Zustand EINER Seite - die EINE Stelle.

    Rueckgabe: dict mit genau den Spalten, die auch im Datensatz stehen.

    team_id_apisports ist die API-Sports-Kennung. Sie MUSS ueber den
    Crosswalk aufgeloest worden sein - die football-data-Kennung der
    CL-Historie ist eine andere Zahl, und sie hier einzusetzen ergaebe
    lauter plausible Werte ueber einen fremden Verein.
    """
    werte = {feld: None for feld in
             TRANSFER_VOLUME_FELDER + TRANSFER_BALANCE_FELDER
             + TRANSFER_STRENGTH_FELDER}
    werte.update({
        "derived_membership_upper_bound": None,
        "arrivals_rated": None,
        "departures_rated": None,
        "transfer_data_available": 0,
        "squad_history_source": SOURCE_NO_CROSSWALK,
        "prior_season_used": None,
    })

    if team_id_apisports is None:
        return werte

    if team_id_apisports not in transfer_index:
        werte["squad_history_source"] = SOURCE_NO_TRANSFERS
        return werte

    zu_365, ab_365 = transfer_window(team_id_apisports, cutoff,
                                     transfer_index, TRANSFER_WINDOW_DAYS)
    zu_120, ab_120 = transfer_window(team_id_apisports, cutoff,
                                     transfer_index, TRANSFER_RECENT_DAYS)

    zugang_staerke = strength_of_group(
        [e["player_id"] for e in zu_365], match_season, strength_source)
    abgang_staerke = strength_of_group(
        [e["player_id"] for e in ab_365], match_season, strength_source)

    differenz = None
    if zugang_staerke["mean_rating"] is not None \
            and abgang_staerke["mean_rating"] is not None:
        differenz = (zugang_staerke["mean_rating"]
                     - abgang_staerke["mean_rating"])

    werte.update({
        "arrivals_365d": float(len(zu_365)),
        "departures_365d": float(len(ab_365)),
        "arrivals_120d": float(len(zu_120)),
        "departures_120d": float(len(ab_120)),
        "loans_in_365d": float(sum(1 for e in zu_365
                                   if e["transfer_type"] == "loan")),
        "loans_out_365d": float(sum(1 for e in ab_365
                                    if e["transfer_type"] == "loan")),
        "net_transfers_365d": float(len(zu_365) - len(ab_365)),
        "net_transfers_120d": float(len(zu_120) - len(ab_120)),
        "arrivals_mean_rating": zugang_staerke["mean_rating"],
        "departures_mean_rating": abgang_staerke["mean_rating"],
        "arrivals_minus_departures_rating": differenz,
        "derived_membership_upper_bound": float(len(derived_membership(
            team_id_apisports, cutoff, transfer_index))),
        "arrivals_rated": zugang_staerke["rated"],
        "departures_rated": abgang_staerke["rated"],
        "transfer_data_available": 1,
        "squad_history_source": SOURCE_OK,
        "prior_season_used": (int(match_season) - 1
                              if match_season is not None else None),
    })
    return werte
