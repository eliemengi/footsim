"""
Der Identitaetsvertrag der Profiluebersetzung (V2-C18).

DER FEHLER, DEN DIESE DATEI FESTHAELT
--------------------------------------
team_identity.translate_profiles legte die Profile einer nationalen
Ligadatei auf die football-data-Kennungen, unter denen die Champions
League gefuehrt wird. Uebersetzt wurde dabei nur der DICT-SCHLUESSEL.
Das Feld profil["team_id"] blieb im Namensraum des Providers stehen.

Fuer die fuenf Top-Ligen faellt das nicht auf, weil beide Raeume dort
dieselben Zahlen benutzen. Fuer die 18 mit C13 ergaenzten Ligen laufen
sie auseinander. Nachgemessen an einer laufenden Ligaphase:

    Sporting CP     Spielplan 498   Profil 228
    Slavia Praha    Spielplan 930   Profil 560
    Bodoe/Glimt     Spielplan 5721  Profil 327
    PSV             Spielplan 674   Profil 197
    Shakhtar        Spielplan 1887  Profil 550
    ... zehn von 36 Teilnehmern

inference._ligastaerke_anwenden liest die Vereinskennung aus dem
PROFIL. Fuer diese zehn Vereine schlug die Ligazuordnung deshalb fehl,
und die zweite Modellstufe fiel in 96 von 126 offenen Partien still
aus - ausgerechnet bei den Vereinen, fuer die sie gebaut wurde.

Der Vertrag lautet ab hier ausnahmslos:

    heraus[fd_id]["team_id"] == fd_id

Er gilt fuer BEIDE Provider, damit kein Aufrufer eine
Fallunterscheidung braucht.
"""

import pytest

from src.data import national_sources as ns
from src.features import team_identity as ti


def _profil(team_id, matches=10):
    """Ein Profil in der Form, die build_season_profiles liefert."""
    return {
        "team_id": team_id,
        "team_name": "Verein %s" % team_id,
        "attack_home": 1.2, "attack_away": 1.1,
        "defence_home": 0.9, "defence_away": 0.95,
        "matches_used": matches,
    }


@pytest.fixture(autouse=True)
def _frischer_crosswalk():
    """Der Bruecken-Puffer darf nicht zwischen Tests haengenbleiben."""
    ti.reset_cache()
    yield
    ti.reset_cache()


# ===========================================================================
# 1  Der Vertrag selbst
# ===========================================================================

def test_schluessel_und_payload_liegen_im_selben_namensraum():
    """
    Die eine Zusage. Fuer JEDE Liga, ohne Fallunterscheidung.

    Bewusst ueber alle echten Profilquellen gefahren statt ueber eine
    ausgedachte: Die Regel soll fuer den Bestand gelten, mit dem die
    Laufzeit tatsaechlich rechnet.
    """
    geprueft = 0
    for code in ns.profile_source_codes():
        roh = {7: _profil(7), 11: _profil(11), 4242: _profil(4242)}
        heraus, _spur = ti.translate_profiles(roh, code)
        for schluessel, profil in heraus.items():
            assert profil["team_id"] == schluessel, (
                "%s: Schluessel %r traegt team_id %r"
                % (code, schluessel, profil["team_id"]))
            geprueft += 1
    assert geprueft, "keine einzige Liga geprueft - der Test ist blind"


def test_eingabeprofile_werden_nicht_veraendert():
    """
    Kein In-place-Schreiben.

    pit_profiles puffert seine Quellprofile ueber mehrere Ligen und
    Saisons. Wuerde hier im Original geschrieben, deutete ein
    spaeterer Leser einen gepufferten Wert anders als sein Erzeuger.
    """
    original = _profil(4242)
    kopie = dict(original)
    roh = {4242: original}

    for code in ns.profile_source_codes():
        ti.translate_profiles(roh, code)

    assert original == kopie, "translate_profiles hat die Eingabe veraendert"
    assert roh[4242] is original, "die Eingabeabbildung wurde ersetzt"


def test_die_rueckgabe_ist_eine_andere_abbildung_als_die_eingabe():
    roh = {4242: _profil(4242)}
    heraus, _ = ti.translate_profiles(roh, "PL")
    assert heraus is not roh


# ===========================================================================
# 2  Die beiden Provider
# ===========================================================================

def test_football_data_ligen_bleiben_inhaltlich_unveraendert():
    """
    Fuer den football-data-Namensraum ist die Uebersetzung ein
    Nullschritt. Geprueft wird, dass sie auch wirklich nichts
    verschiebt - ausser der Zusage, die schon vorher galt.
    """
    roh = {57: _profil(57), 64: _profil(64)}
    heraus, spur = ti.translate_profiles(roh, "PL")

    assert set(heraus) == {57, 64}
    assert spur["translated"] == 0
    assert spur["dropped_unmapped"] == 0
    for schluessel, profil in heraus.items():
        assert profil["team_id"] == schluessel
        # Alles ausser der Kennung ist unveraendert durchgereicht.
        erwartet = dict(_profil(schluessel))
        assert profil == erwartet


def test_api_football_ligen_werden_ueber_den_crosswalk_uebersetzt():
    """
    Der Kern: Schluessel UND Payload wandern gemeinsam.

    Die Zuordnung kommt aus dem geprueften Crosswalk, nicht aus einer
    Namensaehnlichkeit und nicht aus der Annahme, dieselbe Zahl
    bedeute denselben Verein.
    """
    api_zu_fd = {}
    for api_id in range(1, 4000):
        fd = ti.to_football_data(api_id)
        if fd is not None and fd != api_id:
            api_zu_fd[api_id] = fd
        if len(api_zu_fd) >= 5:
            break
    if not api_zu_fd:
        pytest.skip("kein Crosswalkeintrag mit abweichender Zahl vorhanden")

    roh = {api_id: _profil(api_id) for api_id in api_zu_fd}
    heraus, spur = ti.translate_profiles(roh, "NL1")

    for api_id, fd_id in api_zu_fd.items():
        assert fd_id in heraus, "Verein %s nicht uebersetzt" % api_id
        assert heraus[fd_id]["team_id"] == fd_id
        # Die Provider-ID darf NICHT mehr als Identitaet dastehen.
        assert heraus[fd_id]["team_id"] != api_id
    assert spur["translated"] == len(heraus)


def test_unaufloesbare_vereine_fallen_weg_statt_zu_raten():
    """
    Unbekannt bleibt unbekannt. Kein Rueckfall auf dieselbe Zahl.
    """
    unbekannt = 987654321
    assert ti.to_football_data(unbekannt) is None

    heraus, spur = ti.translate_profiles({unbekannt: _profil(unbekannt)},
                                         "NL1")
    assert heraus == {}
    assert spur["dropped_unmapped"] == 1
    assert unbekannt not in heraus


def test_numerische_kollision_zwischen_providern_wird_nicht_verwechselt():
    """
    Die Falle, gegen die C13 gebaut wurde.

    Dieselbe Zahl bezeichnet in beiden Namensraeumen verschiedene
    Vereine. Eine Uebersetzung, die die Zahl behaelt, wuerde einem
    Verein die Ergebnisse eines fremden geben - und nichts an den
    Zahlen saehe falsch aus.
    """
    kollisionen = [api for api in range(1, 4000)
                   if (ti.to_football_data(api) or api) != api][:3]
    if not kollisionen:
        pytest.skip("kein Crosswalkeintrag mit abweichender Zahl vorhanden")

    for api_id in kollisionen:
        fd_id = ti.to_football_data(api_id)
        heraus, _ = ti.translate_profiles({api_id: _profil(api_id)}, "NL1")
        # Das Profil steht unter der football-data-Kennung, NICHT unter
        # der Providerzahl - und traegt genau diese Kennung.
        assert set(heraus) == {fd_id}
        assert heraus[fd_id]["team_id"] == fd_id
        assert api_id not in heraus


def test_ein_unbekannter_provider_wird_abgewiesen():
    with pytest.raises(Exception):
        ti.translate_profiles({1: _profil(1)}, "gibtesnicht")


# ===========================================================================
# 3  Wiederholte Anwendung
# ===========================================================================

def test_eine_zweite_uebersetzung_derselben_eingabe_ist_stabil():
    """
    Zweimal dieselbe Eingabe ergibt zweimal dasselbe Ergebnis.

    Ausdruecklich NICHT geprueft wird, ob man die AUSGABE erneut
    hineingeben darf: Die Funktion erwartet Profile im Namensraum
    ihres Providers. Ihr Ergebnis liegt bereits im Zielraum und ist
    keine gueltige Eingabe mehr. Diese Erwartung steht hier, damit
    niemand sie fuer eine Luecke haelt.
    """
    roh = {4242: _profil(4242)}
    a, spur_a = ti.translate_profiles(roh, "PL")
    b, spur_b = ti.translate_profiles(roh, "PL")
    assert a == b
    assert spur_a == spur_b


# ===========================================================================
# 4  Kein Rueckschritt im echten Bestand
# ===========================================================================

def test_die_echten_top5_profile_behalten_ihre_kennungen():
    """
    Regressionsschutz auf dem tatsaechlichen Bestand: Die Top-5-Ligen
    waren vom Fehler nie betroffen und duerfen es auch nicht werden.
    """
    from src.features.pit_profiles import PitProfileRepository

    repo = PitProfileRepository()
    profile = repo.domestic_profiles(2025, "2025-08-01T12:00:00")
    if not profile:
        pytest.skip("keine lokalen Ligadateien vorhanden")

    for schluessel, profil in profile.items():
        assert profil["team_id"] == schluessel, (
            "Profil unter %r traegt team_id %r"
            % (schluessel, profil["team_id"]))
