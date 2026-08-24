"""
Namensnormalisierung und Trefferbewertung fuer die Spielersuche.

WARUM EIN EIGENES MODUL
-----------------------
Die Normalisierung lag bisher als _fold_accents() mitten im
Vergleichsloader und wurde von dort in andere Module importiert. Das
erzeugt genau die Import-Abhaengigkeit, die man nicht will: Wer nur
Namen vergleichen moechte, zieht den gesamten Vergleichsloader mit.

Dieses Modul hat deshalb KEINE Projektimporte. Es kennt nur Zeichen.

WAS DIE ALTE FASSUNG NICHT KONNTE
---------------------------------
Sie faltete Akzente und schrieb klein - mehr nicht. Interpunktion blieb
stehen. Das fuehrte zu einem nachweisbaren Suchausfall:

    Poolname:      "L. Díaz"   ->  "l. diaz"
    Nutzereingabe: "L.Diaz"    ->  "l.diaz"

"l.diaz" ist kein Teilstring von "l. diaz" - der Punkt trennt einmal mit
und einmal ohne Leerzeichen. Fuer den Nutzer sind beide Schreibweisen
dasselbe; fuer die Suche waren sie es nicht.

WAS HIER NICHT PASSIERT
-----------------------
Zwei verschiedene Spieler werden NIE zusammengefuehrt. Die
Normalisierung dient ausschliesslich dem FINDEN. Die Identitaet ist und
bleibt die stabile player_id des Anbieters - siehe dedupe_by_id().
"""

import unicodedata


#: Zeichen, die ein Namensteil trennen, aber selbst nichts bedeuten.
#: Punkt und Apostroph gehoeren dazu ("L.Diaz", "N'Golo"), ebenso der
#: Bindestrich ("Alexander-Arnold"): Wer "alexander arnold" tippt, meint
#: denselben Spieler.
_TRENNZEICHEN = ".,'`´’-–—_/\\"


def normalize_name(text):
    """
    Namen auf eine vergleichbare Form bringen.

    Schritte, in dieser Reihenfolge:
        1. Unicode zerlegen und Diakritika entfernen  (Díaz -> Diaz)
        2. Kleinschreibung
        3. Trennzeichen zu Leerzeichen                (L.Diaz -> l diaz)
        4. mehrfachen Leerraum vereinheitlichen
        5. aussen trimmen

    Rueckgabe: normalisierter Name, oder "" bei leerer Eingabe.
    """
    if not text:
        return ""

    zerlegt = unicodedata.normalize("NFKD", str(text))
    ohne_marken = "".join(c for c in zerlegt if not unicodedata.combining(c))

    zeichen = []
    for c in ohne_marken.lower():
        zeichen.append(" " if c in _TRENNZEICHEN else c)

    return " ".join("".join(zeichen).split())


def name_tokens(text):
    """Die einzelnen Namensbestandteile in normalisierter Form."""
    normalisiert = normalize_name(text)
    return normalisiert.split() if normalisiert else []


def compact_name(text):
    """
    Name ohne jeden Leerraum - fuer Eingaben, die Trennzeichen weglassen.

    "L.Diaz" und "L. Díaz" ergeben beide "ldiaz". Damit findet auch, wer
    ganz ohne Trennung tippt.
    """
    return normalize_name(text).replace(" ", "")


def matches(query, name):
    """
    Passt die Suchanfrage zu diesem Namen?

    Bewusst grosszuegig, weil die Bewertung (match_rank) anschliessend
    sortiert: Lieber einen Kandidaten mehr anbieten als den gesuchten
    Spieler verschweigen.
    """
    q = normalize_name(query)
    n = normalize_name(name)
    if not q or not n:
        return False

    if q in n:
        return True

    # Ohne Trennzeichen vergleichen: "ldiaz" gegen "l diaz".
    qc, nc = compact_name(query), compact_name(name)
    if qc and qc in nc:
        return True

    # Mehrteilige Anfrage: Der LETZTE Bestandteil ist der Anker.
    q_teile, n_teile = name_tokens(query), name_tokens(name)
    if len(q_teile) > 1:
        return _mehrteilig_passt(q_teile, n_teile)

    return False


def _mehrteilig_passt(q_teile, n_teile):
    """
    Passt eine mehrteilige Anfrage ("Luis Diaz", "L.Diaz") zum Namen?

    Zwei Bedingungen, und die erste ist die wichtige:

      1. Der LETZTE Anfragebestandteil - fast immer der Nachname - muss
         einen Namensbestandteil von mindestens drei Zeichen als Praefix
         treffen. Er ist der Anker.
      2. Alle uebrigen Bestandteile muessen ebenfalls passen, wobei ein
         einbuchstabiger Namensteil als Initiale gilt ("L." zu "Luis").

    WARUM DER ANKER NOETIG IST
    -------------------------
    Ohne ihn traf "L.Diaz" auch "D. Calvert-Lewin": "l" passte als
    Praefix auf "lewin", und "diaz" passte als vermeintliche Initiale auf
    das "D.". Zwei zufaellige Teiltreffer ergaben einen Volltreffer.

    Mit dem Anker muss "diaz" einen echten Namensbestandteil treffen -
    und "D. Calvert-Lewin" hat keinen, der mit "diaz" beginnt.
    """
    anker = q_teile[-1]
    anker_trifft = any(
        len(nt) >= 3 and nt.startswith(anker) for nt in n_teile
    )
    if not anker_trifft:
        return False

    return all(_teil_passt(qt, n_teile) for qt in q_teile[:-1])


def _teil_passt(anfrage_teil, name_teile):
    """
    Passt ein Bestandteil der Anfrage zu irgendeinem Bestandteil des Namens?

    Der zweite Fall unten ist der wichtige: Der Anbieter kuerzt Vornamen
    ab ("L. Diaz"), Nutzer tippen sie aber aus ("Luis Diaz"). Ein
    einbuchstabiger Namensteil gilt deshalb als Initiale und passt zu
    jedem Anfragebestandteil, der mit diesem Buchstaben beginnt.

    Das allein wuerde zu breit greifen - "L" passt auf jedes Wort mit L.
    Deshalb gilt es nur innerhalb der Regel "ALLE Anfragebestandteile
    muessen passen": Der Nachname muss ebenfalls treffen, und erst beide
    zusammen ergeben einen Treffer.
    """
    for nt in name_teile:
        if nt.startswith(anfrage_teil):
            return True
        # Initiale im Namen gegen ausgeschriebenen Vornamen der Anfrage.
        if len(nt) == 1 and anfrage_teil.startswith(nt):
            return True
    return False


def match_rank(query, name):
    """
    Wie gut passt der Treffer? Kleiner ist besser.

        0  exakter vollstaendiger Name
        1  exakter Name ohne Trennzeichen
        2  ein Namensbestandteil stimmt genau
        3  ein Namensbestandteil beginnt mit der Anfrage
        4  Teilstring irgendwo im Namen
        5  passt nur ueber die Bestandteilsregel
        9  passt nicht

    Damit steht bei "diaz" ein Spieler namens "Diaz" vor einem
    "Diazongua", und bei "l diaz" steht "L. Diaz" ganz oben.
    """
    q = normalize_name(query)
    n = normalize_name(name)
    if not q or not n:
        return 9

    if q == n:
        return 0
    if compact_name(query) and compact_name(query) == compact_name(name):
        return 1

    teile = name_tokens(name)
    if q in teile:
        return 2
    if any(t.startswith(q) for t in teile):
        return 3
    if q in n:
        return 4
    if matches(query, name):
        return 5
    return 9


def sort_key(query, eintrag, name_feld="name"):
    """
    Sortierschluessel fuer ein Suchergebnis.

    Reihenfolge: Trefferguete, dann Einsatzminuten absteigend (wer
    spielt, ist wahrscheinlicher gemeint), dann Name, dann player_id.
    Die letzten beiden machen die Reihenfolge stabil und reproduzierbar -
    ohne sie haengt sie an der Reihenfolge der Quellen.
    """
    name = (eintrag or {}).get(name_feld)
    minuten = (eintrag or {}).get("minutes")
    try:
        minuten = float(minuten) if minuten is not None else -1.0
    except (TypeError, ValueError):
        minuten = -1.0

    return (
        match_rank(query, name),
        -minuten,
        normalize_name(name),
        (eintrag or {}).get("player_id") or 0,
    )


#: Wie vollstaendig ein Suchergebnis ist - je hoeher, desto besser.
#:
#: Wird beim Zusammenfuehren mehrerer Quellen gebraucht: Steht derselbe
#: Spieler in Pool UND Kaderindex, gewinnt der Eintrag mit den
#: reichhaltigeren Angaben.
_QUELLEN_RANG = {
    "pool": 4,
    "live_search": 3,
    "verified_squad": 2,
    "current_squad": 1,
}


def completeness(eintrag):
    """
    Wie brauchbar ist dieser Eintrag? Groesser ist besser.

    Zaehlt gefuellte Felder und gewichtet die Quelle. Ein Pooleintrag mit
    Minuten und Position schlaegt einen reinen Kadereintrag.
    """
    if not eintrag:
        return (0, 0)

    felder = ("name", "team_name", "position", "league_code", "age")
    gefuellt = sum(1 for f in felder if eintrag.get(f))
    if eintrag.get("minutes"):
        gefuellt += 1

    return (_QUELLEN_RANG.get(eintrag.get("source_type"), 0), gefuellt)


def dedupe_by_id(eintraege):
    """
    Doppelte Spieler zusammenfuehren - ausschliesslich ueber player_id.

    NIEMALS ueber den Namen: Gleichnamige Spieler sind verschiedene
    Personen und muessen beide erscheinen.

    Bei mehreren Eintraegen derselben ID gewinnt der vollstaendigste
    (siehe completeness). Fehlende Felder werden aus den uebrigen
    ergaenzt, damit nichts verloren geht, was eine Quelle wusste.
    """
    nach_id = {}
    ohne_id = []

    for eintrag in eintraege or []:
        pid = (eintrag or {}).get("player_id")
        if pid is None:
            ohne_id.append(eintrag)
            continue

        pid = int(pid)
        vorhanden = nach_id.get(pid)
        if vorhanden is None:
            nach_id[pid] = dict(eintrag)
            continue

        if completeness(eintrag) > completeness(vorhanden):
            zusammen = dict(eintrag)
            for schluessel, wert in vorhanden.items():
                if zusammen.get(schluessel) in (None, "", []) and wert not in (None, "", []):
                    zusammen[schluessel] = wert
            nach_id[pid] = zusammen
        else:
            for schluessel, wert in eintrag.items():
                if vorhanden.get(schluessel) in (None, "", []) and wert not in (None, "", []):
                    vorhanden[schluessel] = wert

    return list(nach_id.values()) + ohne_id
