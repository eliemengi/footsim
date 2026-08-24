"""
Das Schutzgitter fuer den Browsercode.

HINTERGRUND
-----------
Am 24.08.2026 war FootSim im Browser vollstaendig tot: Simulation,
Vergleiche, Live, Spielervergleich und das Laden der Wettbewerbe -
alles gleichzeitig. Ursache war eine einzige versehentlich doppelt
eingefuegte Passage in pcPlayerDataStatus(), die dieselben Namen ein
zweites Mal deklarierte. Der Browser bricht bei einem SyntaxError die
GESAMTE Datei ab, deshalb faellt nicht ein Bereich aus, sondern jeder.

Die Testsuite war dabei gruen. 2.505 Tests, und keiner davon hat die
Datei jemals geladen - sie haben in ihr nach Zeichenketten gesucht.

Diese Datei schliesst genau diese Luecke. Sie prueft zwei verschiedene
Dinge, weil eine Pruefung nicht gereicht haette:

    Schicht 1  Parsen        faengt echte Syntaxfehler
    Schicht 2  Bindungen     faengt doppelte const/let - DEN Ausfall

Die Selbsttests am Ende sind der wichtigste Teil: Sie belegen, dass die
Pruefung tatsaechlich anschlaegt. Eine Pruefung, die nur bestaetigt,
dass heute alles in Ordnung ist, koennte auch kaputt sein und niemand
wuesste es.
"""

import pytest

from tests.js_source_check import (
    check_file,
    duplicate_declarations,
    duplicate_function_declarations,
    parse,
    syntax_errors,
    unreachable_statements,
)

#: Die Dateien, die im Browser ausgefuehrt werden. Faellt eine von ihnen
#: aus, ist die Anwendung fuer den Nutzer nicht benutzbar.
BROWSERDATEIEN = ["static/script.js", "static/sw.js"]


class TestWerkzeugIstVorhanden:
    """
    Ein still uebersprungener Test ist schlimmer als kein Test.

    Genau diese Sorte falscher Sicherheit hat den Ausfall ueberhaupt
    erst durchgelassen. Fehlt der Parser, soll die Suite rot werden.
    """

    def test_parser_laesst_sich_bauen(self):
        assert parse("const a = 1;").type == "program"

    def test_moderne_syntax_wird_verstanden(self):
        """
        script.js nutzt optional chaining und den Nullish-Operator.

        Ein Parser, der nur ES2017 kann, wuerde hier Fehlalarme melden -
        deshalb ist das eine Zusicherung und keine Nebensache.
        """
        modern = "const a = b?.c ?? d; const f = async () => await g();"
        assert syntax_errors(modern) == []


class TestBrowserdateienSindLadbar:

    @pytest.mark.parametrize("pfad", BROWSERDATEIEN)
    def test_datei_hat_keinen_syntaxfehler(self, pfad):
        fehler = check_file(pfad)["syntax"]
        assert fehler == [], (
            f"{pfad} ist nicht parsebar - der Browser wuerde die gesamte "
            f"Datei verwerfen. Erste Stelle: {fehler[:1]}"
        )

    @pytest.mark.parametrize("pfad", BROWSERDATEIEN)
    def test_datei_hat_keine_doppelte_bindung(self, pfad):
        """Die Pruefung, die den Ausfall vom 24.08.2026 gefunden haette."""
        doppelt = check_file(pfad)["duplikate"]
        assert doppelt == [], (
            f"{pfad} deklariert einen Namen zweimal im selben "
            f"Gueltigkeitsbereich. Der Browser lehnt die Datei ab: {doppelt}"
        )

    @pytest.mark.parametrize("pfad", BROWSERDATEIEN)
    def test_datei_hat_keine_doppelte_funktion(self, pfad):
        """
        Gleichnamige Funktionen sind erlaubt, aber die verlaesslichste
        Signatur eines zweimal eingefuegten Blocks. Die Engine schweigt
        dazu - deshalb muss der Test reden.
        """
        doppelt = check_file(pfad)["doppelte_funktionen"]
        assert doppelt == [], (
            f"{pfad} deklariert eine Funktion zweimal im selben Bereich. "
            f"Die spaetere gewinnt stillschweigend: {doppelt}"
        )

    @pytest.mark.parametrize("pfad", BROWSERDATEIEN)
    def test_datei_hat_keinen_unerreichbaren_code(self, pfad):
        """
        Kein Fehler an sich, aber die Form, in der die Regression auftrat:
        ein zweiter Block hinter einem return.
        """
        tot = check_file(pfad)["unerreichbar"]
        assert tot == [], (
            f"{pfad} enthaelt Code hinter return/throw. Das ist die Signatur "
            f"einer versehentlich doppelt eingefuegten Passage: {tot}"
        )


class TestManuellerFixIstErhalten:
    """
    Der Nutzer hat den Ausfall manuell repariert, indem er genau den
    doppelten Block entfernt hat. Diese Klasse haelt das fest.
    """

    def _funktion(self, name):
        with open("static/script.js", "rb") as f:
            wurzel = parse(f.read())

        stapel = [wurzel]
        while stapel:
            knoten = stapel.pop()
            if knoten.type == "function_declaration":
                bezeichner = knoten.child_by_field_name("name")
                if bezeichner is not None and bezeichner.text.decode() == name:
                    return knoten
            stapel.extend(knoten.children)
        return None

    def test_die_funktion_gibt_es_noch(self):
        assert self._funktion("pcPlayerDataStatus") is not None

    @pytest.mark.parametrize("name", ["status", "referenz", "minuten"])
    def test_genau_eine_deklaration_je_name(self, name):
        """
        Die drei Namen aus der Fehlermeldung des Browsers. Jeder von
        ihnen darf in dieser Funktion genau einmal gebunden werden.
        """
        knoten = self._funktion("pcPlayerDataStatus")
        assert knoten is not None

        quelle = knoten.text
        doppelt = [d for d in duplicate_declarations(quelle) if d["name"] == name]
        assert doppelt == [], (
            f"{name} wird in pcPlayerDataStatus erneut doppelt deklariert - "
            f"der manuelle Fix des Nutzers wurde rueckgaengig gemacht."
        )

    def test_kein_block_hinter_return(self):
        knoten = self._funktion("pcPlayerDataStatus")
        assert unreachable_statements(knoten.text) == []


class TestDiePruefungSchlaegtWirklichAn:
    """
    Selbsttests. Ohne sie waere nicht belegt, dass die Pruefung mehr tut
    als gruen zu leuchten.
    """

    def test_echter_syntaxfehler_wird_gefunden(self):
        fehler = syntax_errors("function f( { return 1; }")
        assert fehler, "ein offensichtlicher Syntaxfehler blieb unbemerkt"

    def test_der_historische_ausfall_wird_gefunden(self):
        """
        Der Code in genau der Form, die am 24.08.2026 die Anwendung
        lahmgelegt hat: ein zweiter Block hinter einem return.
        """
        kaputt = (
            "function pcPlayerDataStatus(comparison, slot) {\n"
            "    const status = comparison.a;\n"
            "    const referenz = comparison.b;\n"
            "    const minuten = comparison.c;\n"
            "    if (!status) return null;\n"
            "    return { status, referenz, minuten };\n"
            "    const status = comparison.a;\n"
            "    const referenz = comparison.b;\n"
            "    const minuten = comparison.c;\n"
            "}\n"
        )

        # Erst der Beleg, warum ein reiner Parser nicht gereicht haette.
        assert syntax_errors(kaputt) == [], (
            "Annahme dieser Datei: doppelte Bindungen sind KEIN Parsefehler"
        )

        doppelt = duplicate_declarations(kaputt)
        namen = {d["name"] for d in doppelt}
        assert namen == {"status", "referenz", "minuten"}

        # Und die Zeilenangabe muss in die richtige Richtung zeigen.
        for eintrag in doppelt:
            assert eintrag["erste_zeile"] < eintrag["zweite_zeile"]

        assert unreachable_statements(kaputt), "der tote Block blieb unbemerkt"

    def test_doppeltes_let_wird_gefunden(self):
        doppelt = duplicate_declarations("let a = 1;\nlet a = 2;\n")
        assert [d["name"] for d in doppelt] == ["a"]

    def test_zerlegung_wird_mitgeprueft(self):
        """Auch eine Objektzerlegung bindet Namen."""
        doppelt = duplicate_declarations("const { a } = x;\nconst a = 2;\n")
        assert [d["name"] for d in doppelt] == ["a"]

    def test_unerreichbarer_code_wird_gefunden(self):
        tot = unreachable_statements("function f() { return 1; const a = 2; }")
        assert tot and tot[0]["art"] == "lexical_declaration"

    @pytest.mark.parametrize("quelle,name", [
        ("const g = 1;\nfunction g(){}\n", "g"),
        ("let h = 1;\nfunction h(){}\n", "h"),
        ("function k(){}\nconst k = 1;\n", "k"),
        ("class K {}\nconst K = 1;\n", "K"),
        ("const L = 1;\nclass L {}\n", "L"),
    ])
    def test_gemischte_bindungen_werden_gefunden(self, quelle, name):
        """
        Diese fuenf Paarungen erzeugen in Chromium exakt dieselbe Meldung
        wie der Ausfall vom 24.08.2026 - "Identifier ... has already been
        declared". Die erste Fassung dieser Pruefung hat sie ALLE
        uebersehen, weil sie nur const gegen const verglich.

        Nachgemessen in einer echten Engine, nicht angenommen.
        """
        doppelt = duplicate_declarations(quelle)
        assert [d["name"] for d in doppelt] == [name], (
            f"gemischte Bindung von {name!r} blieb unbemerkt - genau diese "
            f"Luecke hat der urspruengliche Fehler ausgenutzt"
        )

    def test_zwei_gleiche_funktionen_sind_kein_fehler(self):
        """
        In Chromium nachgemessen: erlaubt. Wer das als Fehler meldet,
        erzeugt Fehlalarme - deshalb steht es in einer eigenen Pruefung.
        """
        quelle = "function f(){return 1;}\nfunction f(){return 2;}\n"
        assert duplicate_declarations(quelle) == []
        assert [d["name"] for d in duplicate_function_declarations(quelle)] == ["f"]

    def test_gleichnamige_funktionen_in_getrennten_bereichen_sind_erlaubt(self):
        quelle = ("function a(){ function inner(){} }\n"
                  "function b(){ function inner(){} }\n")
        assert duplicate_function_declarations(quelle) == []


class TestKeineFehlalarme:
    """
    Eine Pruefung, die bei gutem Code anschlaegt, wird abgeschaltet -
    und dann schuetzt sie gar nichts mehr.
    """

    def test_gleicher_name_in_getrennten_funktionen_ist_erlaubt(self):
        quelle = (
            "function a() { const x = 1; return x; }\n"
            "function b() { const x = 2; return x; }\n"
        )
        assert duplicate_declarations(quelle) == []

    def test_verschattung_in_einem_inneren_block_ist_erlaubt(self):
        quelle = "function a() { const x = 1; if (x) { const x = 2; return x; } }"
        assert duplicate_declarations(quelle) == []

    def test_gleicher_name_in_zwei_pfeilfunktionen_ist_erlaubt(self):
        quelle = (
            "const f = () => { const t = 1; return t; };\n"
            "const g = () => { const t = 2; return t; };\n"
        )
        assert duplicate_declarations(quelle) == []

    def test_var_darf_doppelt_stehen(self):
        """
        Mehrfaches var ist in JavaScript erlaubt. Wer es meldet, erzeugt
        in gewachsenem Code hunderte Fehlalarme.
        """
        assert duplicate_declarations("var a = 1;\nvar a = 2;\n") == []

    def test_funktion_nach_return_ist_kein_toter_code(self):
        """Funktionsdeklarationen werden hochgezogen und bleiben gueltig."""
        quelle = "function f() { return g(); function g() { return 1; } }"
        assert unreachable_statements(quelle) == []

    def test_schleifenzaehler_je_schleife_ist_erlaubt(self):
        quelle = (
            "function f() {\n"
            "  for (let i = 0; i < 3; i++) { g(i); }\n"
            "  for (let i = 0; i < 5; i++) { g(i); }\n"
            "}\n"
        )
        assert duplicate_declarations(quelle) == []
