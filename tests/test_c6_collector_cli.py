"""
Die Sammler-CLI und der systemd-Vertrag (V2-C6).

WAS HIER GEPRUEFT WIRD
----------------------
Die CLI ist die Schnittstelle, die der Timer bedient - und der Timer
liest nur den Exit-Code. Meldet ein halber Lauf eine 0, steht der
Dienst monatelang auf gruen, waehrend die Haelfte der Historie fehlt.
Genau darauf zielt der groesste Teil dieser Datei.

Die systemd-Vorlagen werden als TEXT geprueft. Das ist kein Ersatz
dafuer, sie einmal auf dem Server zu starten - aber es faengt das ab,
was sich statisch entscheiden laesst: fehlendes WorkingDirectory,
vergessenes Persistent, ein Schluessel in der Unit-Datei.

OHNE NETZ
---------
Der Transport wird durchgereicht und durch Attrappen ersetzt.
"""

import json
import os
import pathlib
import re
from datetime import datetime, timezone

import pytest

import collect_snapshots as cli
from src.data import availability_snapshots as av
from src.data import snapshot_archive as archive
from src.data import snapshot_collector as sc

UTC = timezone.utc
DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "systemd"


@pytest.fixture
def archiv(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(sc, "LOCK_PATH", str(tmp_path / "collector.lock"))
    monkeypatch.setattr(sc, "RUN_DIR", str(tmp_path / "runs"))
    return tmp_path


def _squad(team_id=157):
    return {"response": [{"team": {"id": team_id, "name": f"T{team_id}"},
                          "players": [{"id": 1, "name": "A"}]}],
            "results": 1, "paging": {"current": 1, "total": 1}}


def _injuries():
    return {"response": [
        {"player": {"id": 10, "type": "Missing Fixture", "reason": "Injury"},
         "team": {"id": 157},
         "fixture": {"id": 900, "date": "2025-10-01T18:30:00+00:00"}}],
        "results": 1, "paging": {"current": 1, "total": 1}}


def _ok_transport(payload_fuer=None):
    def transport(endpoint, params):
        if payload_fuer is not None:
            nutz = payload_fuer(endpoint, params)
        elif endpoint == av.ENDPOINT_SQUAD:
            nutz = _squad(params["team"])
        else:
            nutz = _injuries()
        return sc.TransportResult(
            True, payload=nutz, status_code=200,
            quota={"x-ratelimit-requests-remaining": 7000,
                   "x-ratelimit-requests-limit": 7500})
    return transport


def _fehler_transport(endpoint, params):
    return sc.TransportResult(False, error="HTTP 500", status_code=500)


# ===========================================================================
# Aufruf und Exit-Codes
# ===========================================================================

class TestAufruf:

    def test_ohne_argumente_passiert_nichts(self, archiv, capsys):
        assert cli.main([]) == cli.EXIT_USAGE

    def test_hilfe_ist_abrufbar(self):
        with pytest.raises(SystemExit) as fehler:
            cli.build_parser().parse_args(["--help"])
        assert fehler.value.code == 0

    def test_eine_unbekannte_art_wird_gemeldet(self, archiv):
        assert cli.main(["--daily", "--kinds", "gibtsnicht"]) == cli.EXIT_USAGE

    def test_eine_unbekannte_liga_wird_gemeldet(self, archiv):
        assert cli.main(["--leagues", "gibtsnicht"]) == cli.EXIT_USAGE

    def test_eine_unsinnige_grenze_wird_gemeldet(self, archiv):
        assert cli.main(["--daily", "--limit", "0"]) == cli.EXIT_USAGE

    def test_die_abdeckung_laeuft_ohne_netz(self, archiv, capsys):
        assert cli.main(["--coverage"]) == cli.EXIT_OK
        ausgabe = capsys.readouterr().out
        assert "Archivbestand" in ausgabe
        assert "nutzbar ab" in ausgabe

    def test_listen_werden_zerlegt(self):
        assert cli.parse_liste("bl1, cl ,,pd") == ["bl1", "cl", "pd"]
        assert cli.parse_int_liste("157, 165") == [157, 165]

    def test_eine_unzahl_wird_abgelehnt(self):
        import argparse

        with pytest.raises(argparse.ArgumentTypeError):
            cli.parse_int_liste("157,keine_zahl")


class TestExitCodes:

    def test_ein_vollstaendiger_lauf_meldet_null(self, archiv):
        code = cli.main(["--leagues", "bl1", "--kinds", "availability"],
                        transport=_ok_transport())
        assert code == cli.EXIT_OK

    def test_ein_teillauf_meldet_drei(self, archiv):
        """
        Der wichtigste Exit-Code. Ein halber Lauf, der 0 meldet, laesst
        den Timer monatelang gruen aussehen, waehrend die Haelfte der
        Historie fehlt.
        """
        def transport(endpoint, params):
            if params.get("team") == 1:
                return sc.TransportResult(True, payload=_squad(1),
                                          status_code=200)
            return _fehler_transport(endpoint, params)

        code = cli.main(["--teams", "1,2", "--kinds", "squad"],
                        transport=transport)
        assert code == cli.EXIT_PARTIAL

    def test_ein_gescheiterter_lauf_meldet_vier(self, archiv):
        code = cli.main(["--teams", "1,2", "--kinds", "squad"],
                        transport=_fehler_transport)
        assert code == cli.EXIT_FAILED

    def test_ein_laufender_sammler_meldet_fuenf(self, archiv):
        sperre = sc.CollectorLock(path=sc.LOCK_PATH).acquire()
        try:
            code = cli.main(["--teams", "1", "--kinds", "squad"],
                            transport=_ok_transport())
            assert code == cli.EXIT_BUSY
        finally:
            sperre.release()

    def test_die_codes_sind_paarweise_verschieden(self):
        codes = [cli.EXIT_OK, cli.EXIT_USAGE, cli.EXIT_PARTIAL,
                 cli.EXIT_FAILED, cli.EXIT_BUSY]
        assert len(set(codes)) == len(codes)

    def test_jeder_laufstatus_hat_einen_eigenen_code(self):
        assert set(cli.STATUS_TO_EXIT) == {sc.RUN_COMPLETE, sc.RUN_PARTIAL,
                                           sc.RUN_FAILED}
        assert len(set(cli.STATUS_TO_EXIT.values())) == 3


# ===========================================================================
# Laufarten
# ===========================================================================

class TestLaufarten:

    def test_ein_probelauf_schreibt_weder_snapshot_noch_bericht(self, archiv):
        code = cli.main(["--teams", "157", "--kinds", "squad", "--dry-run"],
                        transport=_ok_transport())
        assert code == cli.EXIT_OK
        assert archive.list_snapshots(av.KIND_SQUAD) == []
        assert not os.path.isdir(sc.RUN_DIR)

    def test_ein_echter_lauf_schreibt_einen_bericht(self, archiv):
        cli.main(["--teams", "157", "--kinds", "squad"],
                 transport=_ok_transport())
        berichte = os.listdir(sc.RUN_DIR)
        assert len(berichte) == 1
        bericht = json.load(open(os.path.join(sc.RUN_DIR, berichte[0]),
                                 encoding="utf-8"))
        assert bericht["status"] == sc.RUN_COMPLETE
        assert bericht["snapshots_stored"] == 1
        assert bericht["season"]
        assert bericht["scope_discovery"]["teams"] == 1

    def test_no_report_unterdrueckt_den_bericht(self, archiv):
        cli.main(["--teams", "157", "--kinds", "squad", "--no-report"],
                 transport=_ok_transport())
        assert not os.path.isdir(sc.RUN_DIR)

    def test_ein_gezielter_teamlauf_fragt_keine_ligen_ab(self, archiv):
        gesehen = []

        def transport(endpoint, params):
            gesehen.append(endpoint)
            return sc.TransportResult(True, payload=_squad(params.get("team", 1)),
                                      status_code=200)

        cli.main(["--teams", "157"], transport=transport)
        assert set(gesehen) == {av.ENDPOINT_SQUAD}

    def test_ein_gezielter_ligalauf_fragt_keine_kader_ab(self, archiv):
        gesehen = []

        def transport(endpoint, params):
            gesehen.append(endpoint)
            return sc.TransportResult(True, payload=_injuries(),
                                      status_code=200)

        cli.main(["--leagues", "bl1"], transport=transport)
        assert set(gesehen) == {av.ENDPOINT_INJURIES}

    def test_der_probemodus_haelt_seine_grenze_ein(self, archiv):
        gesehen = []

        def transport(endpoint, params):
            gesehen.append(params)
            return sc.TransportResult(True, payload=_squad(params.get("team", 1)),
                                      status_code=200)

        cli.main(["--teams", "1,2,3,4,5", "--kinds", "squad", "--limit", "2"],
                 transport=transport)
        assert len(gesehen) == 2

    def test_die_saison_ist_waehlbar(self, archiv):
        gesehen = []

        def transport(endpoint, params):
            gesehen.append(dict(params))
            return sc.TransportResult(True, payload=_injuries(),
                                      status_code=200)

        cli.main(["--leagues", "bl1", "--season", "2024"], transport=transport)
        assert gesehen[0]["season"] == 2024

    def test_die_json_ausgabe_ist_gueltiges_json(self, archiv, capsys):
        cli.main(["--teams", "157", "--kinds", "squad", "--json"],
                 transport=_ok_transport())
        ausgabe = capsys.readouterr().out
        # Vor dem JSON steht eine Statuszeile - ab der ersten Klammer.
        bericht = json.loads(ausgabe[ausgabe.index("{"):])
        assert bericht["status"] == sc.RUN_COMPLETE

    def test_ein_zweiter_lauf_schreibt_nichts_doppelt(self, archiv):
        cli.main(["--teams", "157", "--kinds", "squad"],
                 transport=_ok_transport())
        cli.main(["--teams", "157", "--kinds", "squad"],
                 transport=_ok_transport())
        assert len(archive.list_snapshots(av.KIND_SQUAD)) == 1

    def test_die_sperre_wird_nach_dem_lauf_freigegeben(self, archiv):
        cli.main(["--teams", "157", "--kinds", "squad"],
                 transport=_ok_transport())
        assert not os.path.exists(sc.LOCK_PATH)

    def test_die_sperre_wird_auch_nach_einem_fehler_freigegeben(self, archiv):
        cli.main(["--teams", "1", "--kinds", "squad"],
                 transport=_fehler_transport)
        assert not os.path.exists(sc.LOCK_PATH)

    def test_ignore_lock_laeuft_ohne_sperre(self, archiv):
        sperre = sc.CollectorLock(path=sc.LOCK_PATH).acquire()
        try:
            code = cli.main(["--teams", "157", "--kinds", "squad",
                             "--ignore-lock"], transport=_ok_transport())
            assert code == cli.EXIT_OK
        finally:
            sperre.release()


class TestAusgabe:

    def test_die_zusammenfassung_nennt_die_kennzahlen(self, archiv, capsys):
        cli.main(["--teams", "157", "--kinds", "squad"],
                 transport=_ok_transport())
        ausgabe = capsys.readouterr().out
        for begriff in ("COMPLETE", "geplant", "neu gesichert",
                        "unveraendert", "Anfragen", "Kontingent",
                        "Abdeckung"):
            assert begriff in ausgabe, begriff

    def test_die_zusammenfassung_zeigt_keine_geheimnisse(self, archiv, capsys,
                                                        monkeypatch):
        monkeypatch.setenv("APISPORTS_KEY", "SUPERGEHEIM123")
        cli.main(["--teams", "157", "--kinds", "squad"],
                 transport=_ok_transport())
        ausgabe = capsys.readouterr().out
        assert "SUPERGEHEIM123" not in ausgabe
        assert "rapidapi" not in ausgabe.lower()

    def test_ein_probelauf_ist_als_solcher_erkennbar(self, archiv, capsys):
        cli.main(["--teams", "157", "--kinds", "squad", "--dry-run"],
                 transport=_ok_transport())
        assert "PROBELAUF" in capsys.readouterr().out

    def test_fehlgeschlagene_scopes_werden_benannt(self, archiv, capsys):
        cli.main(["--teams", "1", "--kinds", "squad"],
                 transport=_fehler_transport)
        ausgabe = capsys.readouterr().out
        assert "Fehlgeschlagene Scopes" in ausgabe
        assert "HTTP 500" in ausgabe


# ===========================================================================
# systemd
# ===========================================================================

class TestSystemdVorlagen:

    @pytest.fixture
    def service(self):
        pfad = DEPLOY / "footsim-snapshots.service"
        assert pfad.exists(), "die Service-Vorlage fehlt"
        return pfad.read_text(encoding="utf-8")

    @pytest.fixture
    def timer(self):
        pfad = DEPLOY / "footsim-snapshots.timer"
        assert pfad.exists(), "die Timer-Vorlage fehlt"
        return pfad.read_text(encoding="utf-8")

    def test_der_dienst_ist_ein_einmallauf(self, service):
        assert "Type=oneshot" in service

    def test_der_dienst_hat_ein_arbeitsverzeichnis(self, service):
        assert re.search(r"^WorkingDirectory=\S+", service, re.M)

    def test_der_dienst_ruft_die_cli_auf(self, service):
        start = re.search(r"^ExecStart=(.+)$", service, re.M)
        assert start
        assert "collect_snapshots.py" in start.group(1)
        assert "--daily" in start.group(1)

    def test_der_dienst_ruft_eine_python_umgebung_auf(self, service):
        """
        Kein blosses "python": Unter systemd gibt es kein aktiviertes
        venv und oft nicht einmal ein PATH mit dem richtigen Python.
        """
        start = re.search(r"^ExecStart=(\S+)", service, re.M).group(1)
        assert start.startswith("/")
        assert "python" in start

    def test_der_dienst_hat_ein_zeitlimit(self, service):
        assert re.search(r"^TimeoutStartSec=\S+", service, re.M)

    def test_der_dienst_startet_nicht_endlos_neu(self, service):
        assert "Restart=no" in service

    def test_ein_teillauf_gilt_als_erfolg(self, service):
        """
        Exit 3 ist partial: echte Snapshots gesichert, nur nicht alles.
        Er darf den Dienst nicht als fehlgeschlagen markieren - die
        Unvollstaendigkeit steht im Laufbericht.
        """
        zeile = re.search(r"^SuccessExitStatus=(.+)$", service, re.M)
        assert zeile
        werte = zeile.group(1).split()
        assert str(cli.EXIT_OK) in werte
        assert str(cli.EXIT_PARTIAL) in werte
        # Ein gescheiterter oder blockierter Lauf NICHT.
        assert str(cli.EXIT_FAILED) not in werte
        assert str(cli.EXIT_BUSY) not in werte

    def test_der_dienst_traegt_keinen_schluessel(self, service):
        """
        Der Schluessel kommt aus der EnvironmentFile des Servers und
        gehoert niemals in eine versionierte Unit-Datei.
        """
        assert "EnvironmentFile=" in service
        assert "APISPORTS_KEY=" not in service
        for verdaechtig in ("x-rapidapi-key", "Environment=APISPORTS"):
            assert verdaechtig not in service

    def test_der_dienst_ist_abgesichert(self, service):
        for zusage in ("NoNewPrivileges=true", "PrivateTmp=true",
                       "ProtectSystem=", "ReadWritePaths="):
            assert zusage in service, zusage

    def test_der_dienst_hat_ressourcengrenzen(self, service):
        assert re.search(r"^MemoryMax=\S+", service, re.M)
        assert re.search(r"^CPUQuota=\S+", service, re.M)

    def test_der_dienst_logt_ins_journal(self, service):
        assert "StandardOutput=journal" in service
        assert "SyslogIdentifier=" in service

    def test_der_timer_laeuft_taeglich_in_utc(self, timer):
        zeile = re.search(r"^OnCalendar=(.+)$", timer, re.M)
        assert zeile
        assert "UTC" in zeile.group(1), (
            "ohne UTC verschoebe die Sommerzeit den Erhebungszeitpunkt")
        assert re.search(r"\d{2}:\d{2}:\d{2}", zeile.group(1))

    def test_der_timer_holt_verpasste_laeufe_nach(self, timer):
        """
        Ohne Persistent faellt ein Tag ersatzlos aus - und eine Luecke
        in dieser Historie laesst sich nicht nachtraeglich schliessen.
        """
        assert "Persistent=true" in timer

    def test_der_timer_streut_den_startzeitpunkt(self, timer):
        assert re.search(r"^RandomizedDelaySec=\S+", timer, re.M)

    def test_der_timer_gehoert_zu_timers_target(self, timer):
        assert "WantedBy=timers.target" in timer

    def test_der_timer_traegt_keinen_schluessel(self, timer):
        assert "APISPORTS" not in timer

    def test_die_betriebsdokumentation_existiert(self):
        pfad = DEPLOY / "README.md"
        assert pfad.exists()
        text = pfad.read_text(encoding="utf-8")
        for begriff in ("systemctl enable", "systemctl disable",
                        "journalctl", "list-timers", "--dry-run",
                        "--coverage", "collector.lock"):
            assert begriff in text, begriff

    def test_die_dokumentation_nennt_alle_exit_codes(self):
        text = (DEPLOY / "README.md").read_text(encoding="utf-8")
        for code in (cli.EXIT_OK, cli.EXIT_PARTIAL, cli.EXIT_FAILED,
                     cli.EXIT_BUSY, cli.EXIT_USAGE):
            assert f"| {code} |" in text, code

    def test_die_dokumentation_enthaelt_keinen_schluessel(self):
        text = (DEPLOY / "README.md").read_text(encoding="utf-8")
        assert "APISPORTS_KEY=" not in text

    def test_die_vorlagen_werden_nicht_aktiviert(self):
        """
        Die Dateien liegen im Repository, nicht in /etc/systemd. C6
        bereitet den Timer vor und schaltet ihn nicht ein.
        """
        assert (DEPLOY / "footsim-snapshots.service").exists()
        assert not os.path.exists(
            "/etc/systemd/system/footsim-snapshots.timer")


# ===========================================================================
# Abgrenzung
# ===========================================================================

class TestAbgrenzung:

    def test_die_cli_startet_kein_flask(self):
        """
        Geprueft wird der ausfuehrbare Code, nicht die Dokumentation.
        Der Modulkopf ERKLAERT ausfuehrlich, warum der Sammler nicht am
        Flask-Prozess haengt - eine Textsuche faende genau diese
        Erklaerung und schluege fehl.
        """
        import ast

        baum = ast.parse(pathlib.Path(cli.__file__).read_text(
            encoding="utf-8"))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Expr) and isinstance(
                    knoten.value, ast.Constant) and isinstance(
                        knoten.value.value, str):
                knoten.value.value = ""
        code = ast.unparse(baum).lower()

        assert "flask" not in code
        assert "gunicorn" not in code
        assert "from app import" not in code
        assert "import app" not in code

    def test_die_cli_trainiert_kein_modell(self):
        quelle = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
        for verboten in ("train_cl_model", "save_bundle", "run_evaluation",
                         "release_stage"):
            assert verboten not in quelle

    def test_die_cli_gibt_keinen_schluessel_aus(self):
        quelle = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
        assert "APISPORTS_KEY" not in quelle
        assert "_headers()" not in quelle

    def test_keine_ui_kennt_den_sammler(self):
        wurzel = pathlib.Path(__file__).resolve().parents[1]
        dateien = (list((wurzel / "templates").rglob("*.html"))
                   + list((wurzel / "static").rglob("*.js")))
        for pfad in dateien:
            text = pfad.read_text(encoding="utf-8", errors="replace")
            for begriff in ("collect_snapshots", "snapshot_collector",
                            "availability_snapshots"):
                assert begriff not in text, f"{begriff} in {pfad.name}"

    def test_der_webprozess_startet_den_sammler_nicht(self):
        """
        Unter Gunicorn liefe er sonst in jedem Worker und bei jedem
        Neustart. Die Dateisperre faengt das ab, aber sie ist die
        zweite Verteidigungslinie - die erste ist, ihn dort gar nicht
        aufzurufen.
        """
        wurzel = pathlib.Path(__file__).resolve().parents[1]
        quelle = (wurzel / "app.py").read_text(encoding="utf-8")
        for begriff in ("collect_snapshots", "snapshot_collector",
                        "run_collection"):
            assert begriff not in quelle, begriff
