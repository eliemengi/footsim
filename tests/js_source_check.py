"""
Echte Pruefung von JavaScript-Quelltext - Parser statt Textsuche.

WARUM ES DIESE DATEI GIBT
-------------------------
Am 24.08.2026 fiel FootSim im Browser vollstaendig aus. In
pcPlayerDataStatus() stand nach einem "return null" ein zweiter, fast
identischer Block, der dieselben Namen noch einmal deklarierte. Der
Browser meldete, der Bezeichner "status" sei bereits deklariert.

Ein SyntaxError beim Laden bricht die GESAMTE Datei ab. Gleichzeitig
waren deshalb Simulation, Vergleiche, Live, Spielervergleich und das
Laden der Wettbewerbe tot - durch eine einzige doppelt eingefuegte
Passage.

Die Python-Testsuite war dabei durchgehend gruen. Sie konnte den Fehler
nicht sehen: Die vorhandenen script.js-Tests sind Substringsuchen
(str.index, str.count). Dass ein Text eine Zeichenkette enthaelt, sagt
nichts darueber, ob die Datei ueberhaupt ladbar ist.

ZWEI SCHICHTEN, WEIL EINE NICHT REICHT
--------------------------------------
Der entscheidende Punkt, der bei der Werkzeugauswahl auffiel:

    1. SYNTAXFEHLER  - "const x = ;"   faellt beim Parsen auf.
    2. SCOPEFEHLER   - zweimal dasselbe const ist syntaktisch tadellos.
                       Genau das war der echte Ausfall.

Ein Parser allein haette die Regression NICHT gefunden. Deshalb pruefen
wir zusaetzlich die Bindungen je Gueltigkeitsbereich - auf dem Baum des
Parsers, nicht mit regulaeren Ausdruecken.

WARUM tree-sitter UND NICHT esprima
-----------------------------------
static/script.js verwendet optional chaining und den Nullish-Operator.
Das Python-Paket esprima kennt ES2017 und scheitert an beidem - es
haette entweder Fehlalarme erzeugt oder, schlimmer, still uebersprungen
werden muessen. tree-sitter-javascript versteht die aktuelle Syntax,
liegt als fertiges Windows-Rad vor und braucht kein Node im PATH.

Eine Eigenheit muss man dabei kennen: tree-sitter ist fehlertolerant.
Es wirft nicht, sondern haengt ERROR- und MISSING-Knoten in den Baum.
syntax_errors() sucht deshalb genau nach diesen Knoten.
"""

import functools


#: Knoten, die einen eigenen lexikalischen Gueltigkeitsbereich aufspannen.
#: const und let gelten jeweils bis zur naechsten dieser Grenzen.
_SCOPE_KNOTEN = frozenset({
    "program",
    "statement_block",
    "class_body",
    "for_statement",
    "for_in_statement",
    "switch_body",
    "catch_clause",
    "arrow_function",
    "function_declaration",
    "function_expression",
    "generator_function",
    "generator_function_declaration",
    "method_definition",
})

#: Anweisungen, nach denen der Rest desselben Blocks nicht mehr laeuft.
_ABBRUCH_KNOTEN = frozenset({
    "return_statement",
    "throw_statement",
    "break_statement",
    "continue_statement",
})

#: Deklarationen, die hochgezogen werden und deshalb auch nach einem
#: return noch gueltig sind. Sie gelten nicht als unerreichbar.
_HOCHGEZOGEN = frozenset({
    "function_declaration",
    "generator_function_declaration",
    "class_declaration",
    "comment",
})


@functools.lru_cache(maxsize=1)
def _parser():
    """
    Der Parser, einmal gebaut und wiederverwendet.

    Bewusst KEIN stilles Ueberspringen bei fehlendem Paket: Ein Test, der
    sich selbst deaktiviert, erzeugt genau die falsche Sicherheit, die zu
    diesem Ausfall gefuehrt hat. Fehlt tree-sitter, soll der Import
    scheitern und die Installation nachgeholt werden.
    """
    import tree_sitter_javascript
    from tree_sitter import Language, Parser

    return Parser(Language(tree_sitter_javascript.language()))


def parse(quelle):
    """Parst JavaScript-Quelltext und gibt den Wurzelknoten zurueck."""
    if isinstance(quelle, str):
        quelle = quelle.encode("utf-8")
    return _parser().parse(quelle).root_node


def _durchlaufen(knoten):
    """Alle Knoten des Baums, Wurzel zuerst."""
    stapel = [knoten]
    while stapel:
        aktuell = stapel.pop()
        yield aktuell
        stapel.extend(reversed(aktuell.children))


def _text(knoten):
    return knoten.text.decode("utf-8", errors="replace")


def syntax_errors(quelle):
    """
    Alle Syntaxfehler der Quelle.

    Rueckgabe: Liste von dicts mit zeile, spalte, art und ausschnitt.
    Leere Liste bedeutet: die Datei ist parsebar.
    """
    treffer = []
    for knoten in _durchlaufen(parse(quelle)):
        if knoten.type == "ERROR":
            art = "ERROR"
        elif knoten.is_missing:
            art = "MISSING"
        else:
            continue
        treffer.append({
            "zeile": knoten.start_point[0] + 1,
            "spalte": knoten.start_point[1] + 1,
            "art": art,
            "ausschnitt": _text(knoten)[:80],
        })
    return sorted(treffer, key=lambda t: (t["zeile"], t["spalte"]))


def _gebundene_namen(knoten):
    """
    Die Namen, die eine Deklaration bindet.

    Deckt auch Zerlegungen ab: eine Objektzerlegung bindet ihre
    Kurzschreibungs-Bezeichner, eine Feldzerlegung ihre Elemente.
    """
    namen = []
    for deklarator in knoten.children:
        if deklarator.type != "variable_declarator":
            continue
        ziel = deklarator.child_by_field_name("name")
        if ziel is None:
            continue
        if ziel.type == "identifier":
            namen.append((_text(ziel), ziel.start_point[0] + 1))
            continue
        # Zerlegungsmuster: alle gebundenen Bezeichner einsammeln.
        for unter in _durchlaufen(ziel):
            if unter.type == "shorthand_property_identifier_pattern":
                namen.append((_text(unter), unter.start_point[0] + 1))
            elif (unter.type == "identifier"
                    and unter.parent is not None
                    and unter.parent.type in ("array_pattern", "pair_pattern",
                                              "object_assignment_pattern")):
                namen.append((_text(unter), unter.start_point[0] + 1))
    return namen


def _direkte_kinder_bis_scope(scope_knoten):
    """
    Alle Knoten unterhalb des Bereichs, die noch zu ihm gehoeren.

    Steigt ab, haelt aber an jeder neuen Bereichsgrenze an - sonst wuerde
    eine innere Funktion faelschlich als Teil der aeusseren gezaehlt und
    jede gleichnamige Hilfsvariable saehe wie ein Duplikat aus.

    Die Rueckgabe ist nach Quelltextposition sortiert. Das ist keine
    Kosmetik: Ohne sie meldet die Duplikatpruefung die spaetere
    Deklaration als die erste, und der Hinweis zeigt auf die falsche
    Zeile.
    """
    gefunden = []
    stapel = list(scope_knoten.children)
    while stapel:
        aktuell = stapel.pop()
        gefunden.append(aktuell)
        if aktuell.type in _SCOPE_KNOTEN:
            continue
        stapel.extend(aktuell.children)

    return sorted(gefunden, key=lambda k: k.start_byte)


def duplicate_declarations(quelle):
    """
    Doppelte const/let-Bindungen im selben Gueltigkeitsbereich.

    Das ist die Pruefung, die den Ausfall vom 24.08.2026 gefunden haette.
    Sie ist KEIN Syntaxcheck: dieselbe const-Bindung zweimal parst
    einwandfrei, die Engine lehnt sie erst beim Binden ab.

    var wird bewusst NICHT geprueft - eine Mehrfachdeklaration mit var
    ist in JavaScript erlaubt und in aelterem Code Absicht.

    Rueckgabe: Liste von dicts mit name, erste_zeile, zweite_zeile, scope.
    """
    treffer = []

    for scope_knoten in _durchlaufen(parse(quelle)):
        if scope_knoten.type not in _SCOPE_KNOTEN:
            continue

        gesehen = {}
        for knoten in _direkte_kinder_bis_scope(scope_knoten):
            if knoten.type != "lexical_declaration":
                continue
            for name, zeile in _gebundene_namen(knoten):
                if name in gesehen:
                    treffer.append({
                        "name": name,
                        "erste_zeile": gesehen[name],
                        "zweite_zeile": zeile,
                        "scope": scope_knoten.type,
                        "scope_zeile": scope_knoten.start_point[0] + 1,
                    })
                else:
                    gesehen[name] = zeile

    return sorted(treffer, key=lambda t: t["zweite_zeile"])


def unreachable_statements(quelle):
    """
    Anweisungen, die nach return/throw/break/continue stehen.

    Der Ausfall vom 24.08.2026 hatte genau diese Form: ein Block hinter
    einem return. Unerreichbarer Code ist fuer sich genommen kein Fehler,
    aber ein sehr verlaesslicher Hinweis auf eine versehentlich doppelt
    eingefuegte Passage.

    Hochgezogene Deklarationen (function, class) und Kommentare zaehlen
    nicht - sie sind auch nach einem return regulaer.
    """
    treffer = []
    for knoten in _durchlaufen(parse(quelle)):
        if knoten.type not in ("statement_block", "program"):
            continue

        gefunden_bei = None
        for kind in knoten.named_children:
            if gefunden_bei is not None and kind.type not in _HOCHGEZOGEN:
                treffer.append({
                    "zeile": kind.start_point[0] + 1,
                    "nach_zeile": gefunden_bei,
                    "art": kind.type,
                    "ausschnitt": _text(kind).split("\n")[0][:80],
                })
                break
            if kind.type in _ABBRUCH_KNOTEN and gefunden_bei is None:
                gefunden_bei = kind.start_point[0] + 1

    return sorted(treffer, key=lambda t: t["zeile"])


def check_file(pfad):
    """
    Eine Datei vollstaendig pruefen.

    Rueckgabe: dict mit pfad, syntax, duplikate und unerreichbar.
    """
    with open(pfad, "rb") as f:
        quelle = f.read()
    return {
        "pfad": pfad,
        "syntax": syntax_errors(quelle),
        "duplikate": duplicate_declarations(quelle),
        "unerreichbar": unreachable_statements(quelle),
    }
