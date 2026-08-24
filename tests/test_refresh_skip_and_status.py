"""
Der Import-Skip und die zwei Wahrheiten ueber einen Pool.

DER FEHLER, DEN DIESE DATEI FESTHAELT
-------------------------------------
Dieser Befehl war wirkungslos, ohne das zu melden:

    refresh_players.py --league pd --season 2026 --refetch-players

--refetch-players setzte den Profilcache-Bypass. Danach kehrte
import_one_league() zurueck, bevor ein einziges Profil angefasst wurde,
weil der Skip nur --force kannte. Der Bypass war gesetzt und wurde nie
benutzt. Wer zwei Werte korrigieren wollte, hatte keinen funktionierenden
Weg ausser einem vollstaendigen Ligarefresh.

Dahinter lag ein zweiter, groesserer Widerspruch: Es gab zwei Wahrheiten
ueber dieselbe Liga.

    --report / --diagnose   bewerteten den Pool INHALTLICH
    der Import-Skip         las den GESPEICHERTEN Vermerk

LaLiga stand deshalb im Report als unvollstaendig und wurde beim Import
trotzdem als "bereits vollstaendig" abgetan. Beide Aussagen waren fuer
sich korrekt - sie beantworteten nur verschiedene Fragen, ohne das
kenntlich zu machen.

Kein Test hier spricht mit dem Anbieter: import_league() wird durch einen
Mitschreiber ersetzt, der festhaelt, ob und wie er gerufen wurde.
"""

import pytest

import refresh_players
from src.data import player_pool


@pytest.fixture
def pool_umgebung(tmp_path, monkeypatch):
    """Pool und Status in einem Wegwerfverzeichnis."""
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    monkeypatch.setattr(player_pool, "POOL_DIR", str(pool_dir))
    monkeypatch.setattr(player_pool, "STATUS_PATH", str(pool_dir / "status.json"))
    return pool_dir


def vollstaendiger_pool(league="pd", season=2026, teams=20, je_team=6):
    """
    Ein Pool, der die inhaltliche Pruefung besteht.

    evaluate_pool() verlangt genuegend Spieler und eine ausreichende
    Vereinsabdeckung - deshalb echte Teams statt eines Alibieintrags.
    """
    spieler = []
    for team_id in range(1, teams + 1):
        for n in range(je_team):
            spieler.append({
                "player_id": team_id * 100 + n,
                "name": f"Spieler {team_id}-{n}",
                "team_id": team_id,
                "team_name": f"Verein {team_id}",
                "league_code": league,
                "minutes_by_scope": {"club_all": 900, "league": 900},
                "metrics_by_scope": {},
            })
    return {"league": league, "season": season,
            "pages_done": [1], "players": spieler}


def duenner_pool(league="pd", season=2026):
    """Ein Pool, den der Anbieter erkennbar unvollstaendig geliefert hat."""
    return {
        "league": league, "season": season, "pages_done": [1],
        "players": [{"player_id": 1, "name": "Einziger", "team_id": 1,
                     "team_name": "Verein 1", "league_code": league,
                     "minutes_by_scope": {"club_all": 90}}],
    }


@pytest.fixture
def mitschreiber(monkeypatch):
    """Ersetzt import_league und haelt fest, wie es gerufen wurde."""
    aufrufe = []

    def ersatz(league_code, season, fetch_page, build_entry, **kwargs):
        aufrufe.append({"league": league_code, "season": season, **kwargs})
        return {"status": player_pool.STATUS_COMPLETE}

    monkeypatch.setattr(refresh_players, "import_league", ersatz)
    return aufrufe


# ---------------------------------------------------------------------------
# Der reparierte Skip
# ---------------------------------------------------------------------------

class TestRefetchPlayersUmgehtDenSkip:

    def test_refetch_players_ueberspringt_nicht_mehr(self, pool_umgebung,
                                                     mitschreiber):
        """Der Kern der Reparatur."""
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        ok = refresh_players.import_one_league("pd", 2026, refetch_players=True)

        assert ok
        assert len(mitschreiber) == 1, (
            "die Liga wurde uebersprungen - --refetch-players ist wieder "
            "wirkungslos"
        )

    def test_refetch_players_schaltet_auch_resume_ab(self, pool_umgebung,
                                                     mitschreiber):
        """
        Die zweite Haelfte derselben Reparatur. resume ueberspringt bereits
        geladene Seiten - und damit jeden Spielerabruf darauf. Ohne diese
        Zusicherung waere das Flag ein zweites Mal wirkungslos, diesmal
        eine Ebene tiefer.
        """
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        refresh_players.import_one_league("pd", 2026, refetch_players=True)

        assert mitschreiber[0]["resume"] is False

    def test_normaler_lauf_ueberspringt_weiterhin(self, pool_umgebung,
                                                  mitschreiber):
        """
        Das gewollte Verhalten bleibt: Ein fertiger, inhaltlich guter Pool
        wird nicht ohne Anlass neu geladen.
        """
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        ok = refresh_players.import_one_league("pd", 2026)

        assert ok
        assert mitschreiber == [], "der Skip greift nicht mehr"

    def test_force_ueberspringt_ebenfalls_nicht(self, pool_umgebung,
                                                mitschreiber):
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        refresh_players.import_one_league("pd", 2026, force=True)
        assert len(mitschreiber) == 1

    def test_force_und_refetch_players_bleiben_getrennt(self, pool_umgebung,
                                                        mitschreiber):
        """
        Sie beantworten verschiedene Fragen: force die nach den
        Ligaseiten, refetch_players die nach den Spielerprofilen. Wer nur
        Profile erneuern will, soll nicht force kennen muessen.
        """
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        # Beide erreichen den Import, aber ueber verschiedene Bedingungen.
        refresh_players.import_one_league("pd", 2026, force=True)
        refresh_players.import_one_league("pd", 2026, refetch_players=True)

        assert len(mitschreiber) == 2

    def test_die_kombination_funktioniert_weiterhin(self, pool_umgebung,
                                                    mitschreiber):
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        refresh_players.import_one_league("pd", 2026, force=True,
                                          refetch_players=True)
        assert mitschreiber[0]["resume"] is False


# ---------------------------------------------------------------------------
# Die zwei Wahrheiten
# ---------------------------------------------------------------------------

class TestStatusVereinheitlicht:

    def test_vermerk_complete_inhalt_complete(self, pool_umgebung):
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        stand = player_pool.effective_pool_status("pd", 2026)
        assert stand["status"] == player_pool.STATUS_COMPLETE
        assert stand["agree"] is True

    def test_vermerk_complete_inhalt_widerspricht(self, pool_umgebung):
        """
        Genau der Fall LaLiga. Der Inhalt gewinnt - sonst entsteht wieder
        der Widerspruch zwischen Report und Import.
        """
        player_pool.write_pool(duenner_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        stand = player_pool.effective_pool_status("pd", 2026)
        assert stand["stored"] == player_pool.STATUS_COMPLETE
        assert stand["status"] == player_pool.STATUS_PROVIDER_INCOMPLETE
        assert stand["agree"] is False
        assert "widerspricht" in stand["reason"]

    def test_vermerk_unvollstaendig_schlaegt_guten_inhalt(self, pool_umgebung):
        """Was noch laeuft, ist nicht fertig - egal wie gut es aussieht."""
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_IN_PROGRESS)

        stand = player_pool.effective_pool_status("pd", 2026)
        assert stand["status"] == player_pool.STATUS_IN_PROGRESS

    def test_ohne_jeden_vermerk_gilt_pending(self, pool_umgebung):
        stand = player_pool.effective_pool_status("pd", 2026)
        assert stand["status"] == player_pool.STATUS_PENDING

    def test_skip_folgt_der_zusammengefuehrten_wahrheit(self, pool_umgebung):
        player_pool.write_pool(duenner_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        # Der alte is_pool_complete() sagt weiterhin ja - er beantwortet
        # die technische Frage nach dem Importvorgang.
        assert player_pool.is_pool_complete("pd", 2026) is True
        # Die Skip-Entscheidung folgt jetzt der inhaltlichen Frage.
        assert player_pool.is_import_skippable("pd", 2026) is False

    def test_ein_widerspruch_wird_beim_import_nicht_verschwiegen(
            self, pool_umgebung, mitschreiber, capsys):
        """
        Frueher stand hier stillschweigend "bereits vollstaendig,
        uebersprungen". Jetzt muss der Grund sichtbar sein.
        """
        player_pool.write_pool(duenner_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        refresh_players.import_one_league("pd", 2026)

        ausgabe = capsys.readouterr().out
        assert "Inhalt" in ausgabe
        assert len(mitschreiber) == 1, "trotz Widerspruch uebersprungen"

    def test_prozessabbruch_hinterlaesst_kein_falsches_complete(
            self, pool_umgebung):
        """
        Ein abgebrochener Lauf steht auf in_progress. Der darf beim
        naechsten Mal nicht als fertig durchgehen.
        """
        player_pool.write_pool(duenner_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_IN_PROGRESS)

        assert player_pool.is_import_skippable("pd", 2026) is False

    def test_leere_anbieterseiten_gelten_nicht_als_vollstaendig(
            self, pool_umgebung):
        player_pool.write_pool({"league": "pd", "season": 2026,
                                "pages_done": [1], "players": []})
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        stand = player_pool.effective_pool_status("pd", 2026)
        assert stand["status"] == player_pool.STATUS_PROVIDER_INCOMPLETE
        assert any("keine Spieler" in p for p in stand["issues"])

    def test_teilweise_teamabdeckung_faellt_auf(self, pool_umgebung):
        """20 erwartete Vereine, nur 10 geliefert."""
        player_pool.write_pool(vollstaendiger_pool(teams=10, je_team=12))
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        stand = player_pool.effective_pool_status("pd", 2026)
        assert stand["status"] == player_pool.STATUS_PROVIDER_INCOMPLETE
        assert stand["teams"] == 10
        assert stand["expected_teams"] == 20

    def test_die_kennzahlen_stehen_im_ergebnis(self, pool_umgebung):
        """Report und Diagnose sollen aus derselben Quelle schoepfen."""
        player_pool.write_pool(vollstaendiger_pool())
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_COMPLETE)

        stand = player_pool.effective_pool_status("pd", 2026)
        for feld in ("players", "teams", "with_minutes", "expected_teams",
                     "team_coverage", "issues", "stored", "evaluated",
                     "status", "agree", "reason"):
            assert feld in stand, feld


# ---------------------------------------------------------------------------
# Die CLI-Form
# ---------------------------------------------------------------------------

class TestCliForm:
    """
    Der Nutzer bekam frueher "error: unrecognized arguments: 278 762".
    Diese Tests halten fest, dass die Form jetzt existiert.
    """

    def _parse(self, argv):
        import sys
        from unittest.mock import patch

        with patch.object(sys, "argv", ["refresh_players.py"] + argv):
            # main() baut den Parser selbst; hier wird nur geprueft, dass
            # argparse die Form annimmt - deshalb der Abbruch davor.
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("--season", type=int)
            parser.add_argument("--refetch-player", action="append", type=int,
                                dest="refetch_player")
            parser.add_argument("--refetch-team", action="append", type=int,
                                dest="refetch_team")
            parser.add_argument("--dry-run", action="store_true")
            return parser.parse_args(argv)

    def test_ein_spieler(self):
        args = self._parse(["--season", "2026", "--refetch-player", "278"])
        assert args.refetch_player == [278]

    def test_mehrere_spieler(self):
        args = self._parse(["--season", "2026",
                            "--refetch-player", "278",
                            "--refetch-player", "762"])
        assert args.refetch_player == [278, 762]

    def test_mit_dry_run(self):
        args = self._parse(["--season", "2026", "--refetch-player", "278",
                            "--dry-run"])
        assert args.dry_run is True

    def test_der_echte_parser_kennt_die_option(self):
        """Nicht der Nachbau oben, sondern der Parser aus main()."""
        import subprocess
        import sys

        ergebnis = subprocess.run(
            [sys.executable, "refresh_players.py", "--help"],
            capture_output=True, text=True, timeout=120,
        )
        assert "--refetch-player" in ergebnis.stdout
        assert "--refetch-team" in ergebnis.stdout
