"""
Kein Test darf einem anderen seinen Zustand hinterlassen.

DER FEHLER, DEN DIESE DATEI VERHINDERT
--------------------------------------
Sechs Testdateien setzten WTF_CSRF_ENABLED auf False - alle auf
demselben modulglobalen Flask-Objekt, keine stellte es zurueck:

    test_auth.py, test_audit_hardening.py, test_email_verification.py,
    test_password_reset_token.py, test_privacy_and_deletion.py,
    test_security_hardening.py

Alle sechs haengen an der postgres_db-Fixture. Daraus wurde eine
Abhaengigkeit von zwei Dingen, die mit dem Pruefgegenstand nichts zu tun
haben: der alphabetischen Dateireihenfolge und der Verfuegbarkeit einer
Datenbank.

    Lokal   postgres_db laeuft -> CSRF ab dann global aus -> spaetere
            POST-Tests kommen durch, ohne je ein Token zu schicken.
    CI      postgres_db ueberspringt -> Fixturekoerper laeuft nie ->
            CSRF bleibt an -> dieselben Tests antworten 400.

Fuenf Tests fielen deshalb in der CI, die lokal gruen waren. Nicht weil
die Anwendung kaputt war, sondern weil die Suite von ihrer eigenen
Reihenfolge abhing.

Die Sicherung sitzt in tests/conftest.py (_flask_konfiguration_isolieren)
und stellt app.config nach jedem Test wieder her. Diese Datei belegt,
dass sie wirkt - auch fuer Fixtures, die es erst spaeter geben wird.
"""

import pytest

pytest.importorskip("app", reason="app-Modul nicht importierbar")

import app as main_app  # noqa: E402

#: Der Wert, den die Anwendung ohne Zutun eines Tests hat.
#: CSRFProtect wird in app.py unbedingt initialisiert.
ERWARTETER_AUSGANGSWERT = True


def _csrf_zustand():
    return main_app.app.config.get("WTF_CSRF_ENABLED", True)


class TestAusgangszustand:

    def test_csrf_ist_ausserhalb_von_tests_aktiv(self):
        """
        Der Bezugspunkt fuer alles Weitere. Waere er False, liefe die
        gesamte Suite an der Produktionswirklichkeit vorbei.
        """
        assert _csrf_zustand() is ERWARTETER_AUSGANGSWERT

    def test_die_produktivlogik_schaltet_csrf_nicht_ab(self):
        """
        Die Sicherung darf niemals dadurch erreicht werden, dass der
        Schutz selbst weicher wird.
        """
        import inspect

        quelle = inspect.getsource(main_app)
        assert "csrf.init_app(app)" in quelle
        assert 'config["WTF_CSRF_ENABLED"] = False' not in quelle
        assert "config['WTF_CSRF_ENABLED'] = False" not in quelle


class TestZustandLecktNicht:
    """
    Die drei Tests hier laufen alphabetisch in dieser Reihenfolge. Der
    mittlere aendert die Konfiguration, die beiden anderen pruefen, dass
    davor und danach der Ausgangszustand gilt.
    """

    def test_a_vorher_gilt_der_ausgangszustand(self):
        assert _csrf_zustand() is ERWARTETER_AUSGANGSWERT

    def test_b_ein_test_darf_csrf_voruebergehend_abschalten(self):
        main_app.app.config["WTF_CSRF_ENABLED"] = False
        assert _csrf_zustand() is False

    def test_c_danach_gilt_wieder_der_ausgangszustand(self):
        """Ohne die Sicherung in conftest.py waere das hier False."""
        assert _csrf_zustand() is ERWARTETER_AUSGANGSWERT, (
            "die Konfigurationsaenderung aus dem vorigen Test ist "
            "uebriggeblieben - die Isolation greift nicht mehr"
        )


class TestBeliebigeSchluesselWerdenZurueckgesetzt:
    """
    Die Sicherung darf nicht auf CSRF zugeschnitten sein. Die naechste
    Fixture aendert vielleicht etwas anderes.
    """

    def test_a_ein_neuer_schluessel_wird_gesetzt(self):
        main_app.app.config["FOOTSIM_ISOLATIONSPROBE"] = "gesetzt"
        main_app.app.config["TESTING"] = True
        assert main_app.app.config["FOOTSIM_ISOLATIONSPROBE"] == "gesetzt"

    def test_b_der_neue_schluessel_ist_wieder_weg(self):
        assert "FOOTSIM_ISOLATIONSPROBE" not in main_app.app.config, (
            "ein im vorigen Test hinzugefuegter Schluessel blieb stehen"
        )


class TestReihenfolgeSpieltKeineRolle:
    """
    Der eigentliche Anspruch: Ein Test muss allein dasselbe Ergebnis
    liefern wie im Gesamtlauf. Diese Tests starten pytest deshalb in
    einem eigenen Prozess - nur so ist die Reihenfolge wirklich anders.
    """

    def _lauf(self, *argumente):
        import subprocess
        import sys

        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             *argumente],
            capture_output=True, text=True, timeout=600,
        )

    @pytest.mark.parametrize("datei", [
        "tests/test_block_b1_champions_league.py",
        "tests/test_block_b2_cl_flow.py",
    ])
    def test_datei_besteht_auch_voellig_allein(self, datei):
        """
        Genau diese beiden Dateien fielen in der CI um. Allein
        ausgefuehrt gab es vorher niemanden, der CSRF abgeschaltet
        zurueckliess.
        """
        ergebnis = self._lauf(datei)
        assert ergebnis.returncode == 0, (
            f"{datei} besteht nur im Verbund, nicht allein:\n"
            f"{ergebnis.stdout[-1500:]}"
        )

    def test_umgekehrte_reihenfolge_aendert_nichts(self):
        """
        Erst die Datei, die CSRF abschaltet, dann die, die darunter
        gelitten hat - und danach umgekehrt. Beide Male gruen.
        """
        vorwaerts = self._lauf("tests/test_auth.py",
                               "tests/test_block_b1_champions_league.py")
        rueckwaerts = self._lauf("tests/test_block_b1_champions_league.py",
                                 "tests/test_auth.py")

        assert vorwaerts.returncode == 0, vorwaerts.stdout[-1500:]
        assert rueckwaerts.returncode == 0, rueckwaerts.stdout[-1500:]
