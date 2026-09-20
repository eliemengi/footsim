"""
Big Game Rating V2 - Zulassung und Kontextgewicht unter gewaehlter Huerde.

WOZU
----
Die Bestenliste laesst den Nutzer waehlen, ab welcher Gegnerstaerke ein
Spiel ueberhaupt als Big Game zaehlt (UEFA Top 5-30, FIFA Top 5-20).
Diese Auswahl darf NICHT im Browser aus einer fertigen Liste gefiltert
werden - sonst waere es nur eine andere Beschriftung derselben Rangfolge.
Stattdessen wird je Anfrage aus den gespeicherten Spielzeilen neu
entschieden:

    1. Zaehlt dieses Spiel unter DIESER Huerde ueberhaupt?
    2. Wie schwer wiegt es dann?

ZWEI UNABHAENGIGE WEGE (die zentrale Regel dieses Moduls)
---------------------------------------------------------
GEGNER  - der Gegner lag innerhalb der gewaehlten Huerde.
RUNDE   - die Partie war an sich gross (CL-K.o., Pokalfinale,
          WM-/EM-K.o., Halbfinale/Finale einer kontinentalen
          Meisterschaft, Supercup).

Beide Wege qualifizieren fuer sich allein. Deshalb kann eine engere
Gegnerhuerde ein WM-Finale NIE entfernen - sie nimmt ihm nur den
Elitebonus:

    WM-Finale gegen einen Gegner ausserhalb der gewaehlten FIFA-Huerde
        -> zaehlt (Runde), Gegnerstaerke neutral 1.00

    CL-Finale gegen einen Klub ausserhalb der gewaehlten UEFA-Huerde
        -> zaehlt (Runde), Gegnerstaerke neutral 1.00

    Ligaspiel gegen Rang 4 bei gewaehlter Huerde Top 5
        -> zaehlt (Gegner), voller Staerkewert

    Ligaspiel gegen Rang 8 bei gewaehlter Huerde Top 5
        -> zaehlt NICHT

GESPEICHERT WIRD NUR DAS BAND
-----------------------------
Je Spiel liegt ``opponent_band`` vor (5/10/15/20/25/30 bzw. 5/10/15/20)
oder None. Der exakte Rang und der Koeffizient bleiben auf dem Server;
die Huerde laesst sich trotzdem exakt anwenden.
"""

from src.features import big_games
from src.features import national_big_games


#: Quellenkennungen der gespeicherten Spielzeilen.
SOURCE_CLUB = "club"
SOURCE_NATIONAL = national_big_games.NATIONAL_SOURCE

#: Neutrale Gegnerstaerke: ein Gegner ausserhalb der gewaehlten Huerde
#: wird NICHT abgewertet, er bekommt nur keinen Bonus.
NEUTRAL_STRENGTH = 1.00


def clamp_uefa_max_rank(value):
    """Die naechste zulaessige UEFA-Huerde. Ohne Angabe: die weiteste."""
    return _clamp_band(value, big_games.UEFA_RANK_BANDS,
                       big_games.DEFAULT_UEFA_MAX_RANK)


def clamp_fifa_max_rank(value):
    """Die naechste zulaessige FIFA-Huerde. Ohne Angabe: die weiteste."""
    return _clamp_band(value, national_big_games.FIFA_RANK_BANDS,
                       national_big_games.DEFAULT_FIFA_MAX_RANK)


def _clamp_band(value, bands, default):
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number in bands:
        return number
    # Nie ueber die groesste belegte Stufe hinaus: es gibt keine Daten
    # jenseits der gespeicherten Liste, und erfundene Stufen waeren keine.
    if number > max(bands):
        return max(bands)
    for band in bands:
        if number <= band:
            return band
    return default


def _is_club(match):
    return (match.get("source") or SOURCE_CLUB) == SOURCE_CLUB


def stage_qualifies(match):
    """
    Zulassung allein ueber Runde und Wettbewerb - ohne jeden Gegnerbezug.

    Genau die bestehenden Regeln, nur an einer Stelle gebuendelt:
    europaeischer K.o., Supercup, K.o. der Klub-WM und nationales
    Pokalfinale auf der Vereinsseite; WM-/EM-K.o. sowie Halbfinale und
    Finale der kontinentalen Meisterschaften auf der Nationalseite.
    """
    stage = match.get("stage")
    competition_id = match.get("league_id")
    if _is_club(match):
        tier = big_games.competition_tier(competition_id)
        return bool(big_games.is_importance_qualified(stage, tier))
    return bool(national_big_games.is_stage_qualified(competition_id, stage))


def opponent_qualifies(match, uefa_max_rank, fifa_max_rank):
    """Zulassung allein ueber den Gegner - gemessen an der gewaehlten Huerde."""
    band = match.get("opponent_band")
    cutoff = uefa_max_rank if _is_club(match) else fifa_max_rank
    return big_games.band_within_cutoff(band, cutoff)


def resolve_match(match, uefa_max_rank=None, fifa_max_rank=None):
    """
    Entscheidet EIN gespeichertes Spiel unter der gewaehlten Huerde neu.

    Rueckgabe ein Dict mit
        qualifies   zaehlt das Spiel ueberhaupt?
        reasons     welche Wege haben es zugelassen
        strength    Gegnerstaerke (neutral, wenn ausserhalb der Huerde)
        importance  Bedeutung der Runde (unveraendert gespeichert)
        factor      Wettbewerbsfaktor (CL > EL > Conference, Supercup tiefer)
        weight      das Produkt, also das Kontextgewicht des Spiels

    Das Gewicht bleibt beschraenkt: Staerke <= 1.50, Bedeutung <= 1.15,
    Faktor <= 1.00. Es gibt keine sich aufschaukelnde Multiplikation.
    """
    uefa_max_rank = clamp_uefa_max_rank(uefa_max_rank)
    fifa_max_rank = clamp_fifa_max_rank(fifa_max_rank)

    durch_gegner = opponent_qualifies(match, uefa_max_rank, fifa_max_rank)
    durch_runde = stage_qualifies(match)

    reasons = []
    if durch_gegner:
        reasons.append("opponent")
    if durch_runde:
        reasons.append("stage")

    # Der Elitebonus haengt AUSSCHLIESSLICH an der Gegnerhuerde. Eine
    # ueber die Runde zugelassene Partie gegen einen Gegner ausserhalb der
    # Auswahl bekommt neutrale Staerke - nie einen Bonus, nie einen Abzug.
    strength = (match.get("strength") if durch_gegner else NEUTRAL_STRENGTH)
    if strength is None:
        strength = NEUTRAL_STRENGTH
    importance = match.get("importance")
    if importance is None:
        importance = big_games.IMPORTANCE_BASE
    factor = (big_games.competition_factor(match.get("league_id"))
              if _is_club(match) else big_games.COMPETITION_FACTOR_DEFAULT)

    return {
        "qualifies": bool(reasons),
        "reasons": reasons,
        "strength": float(strength),
        "importance": float(importance),
        "factor": float(factor),
        "weight": float(strength) * float(importance) * float(factor),
    }


def qualified_matches(matches, uefa_max_rank=None, fifa_max_rank=None):
    """
    Die unter der gewaehlten Huerde zaehlenden Spiele, mit neuem Gewicht.

    Die Spielzeile wird nicht veraendert; es entsteht je Spiel eine Kopie
    mit dem neu aufgeloesten ``weight`` und der Begruendung. Alles andere
    - Minuten, Bewertung, Tore, Vorlagen - bleibt unberuehrt.
    """
    out = []
    for match in matches or []:
        if (match.get("minutes") or 0) <= 0:
            continue
        entscheidung = resolve_match(match, uefa_max_rank, fifa_max_rank)
        if not entscheidung["qualifies"]:
            continue
        angepasst = dict(match)
        angepasst["weight"] = entscheidung["weight"]
        angepasst["strength"] = entscheidung["strength"]
        angepasst["competition_factor"] = entscheidung["factor"]
        angepasst["qualification_reasons"] = entscheidung["reasons"]
        out.append(angepasst)
    return out


__all__ = [
    "SOURCE_CLUB", "SOURCE_NATIONAL", "NEUTRAL_STRENGTH",
    "clamp_uefa_max_rank", "clamp_fifa_max_rank",
    "stage_qualifies", "opponent_qualifies", "resolve_match",
    "qualified_matches",
]
