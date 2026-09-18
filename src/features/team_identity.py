"""
Vereinsidentitaet ueber Providergrenzen (V2-C13).

DIE REGEL
---------
Eine Zahl ist keine Vereinsidentitaet. Erst Provider plus Zahl ergeben
eine.

WARUM DAS NICHT THEORETISCH IST
-------------------------------
Nachgemessen an den 63 Champions-League-Vereinen: 28 ihrer
football-data-IDs bezeichnen im API-Football-Namensraum einen ANDEREN
Verein.

    football-data 498 = Sporting CP      API-Football 498 = Sampdoria
    football-data 732 = Celtic           API-Football 732 = Zaragoza
    football-data  57 = Arsenal          API-Football  57 = Ipswich
    football-data  64 = Liverpool        API-Football  64 = Hull City
    football-data  66 = Manchester Utd   API-Football  66 = Aston Villa

Ein Profil, das ueber eine rohe ID gebaut wird, traegt dann die
Ergebnisse eines fremden Vereins - und nichts an den Zahlen sieht
falsch aus. Genau dieser Fehler ist im forensischen Audit vor C13
tatsaechlich passiert, in einem Analyseskript.

DIE RICHTUNG DER BRUECKE
------------------------
squad_crosswalk (V2-C7) bildet football-data -> API-Football ab, weil
die Transferhistorie so gebraucht wurde. Der Profilpfad braucht die
Gegenrichtung: Er baut Profile aus einer API-Football-Ligadatei und
muss sie auf die football-data-Kennungen legen, unter denen die
Champions League gefuehrt wird.

Die Umkehrung wird hier gebildet, EINMAL und mit Konfliktpruefung. Ein
API-Football-Verein, auf den zwei football-data-Vereine zeigen, waere
mehrdeutig; er wird dann aus BEIDEN Richtungen entfernt. Unbekannt ist
besser als vielleicht falsch - dieselbe Regel wie in C7.

WAS HIER NICHT PASSIERT
-----------------------
Kein Fuzzy-Matching zur Laufzeit. Der Crosswalk wird aus den lokalen
Dateien gebaut und geprueft; er wird nicht bei jedem Aufruf neu
geraten. Wer nicht in ihm steht, bekommt kein nationales Profil.
"""

import functools

from src.data.national_sources import (
    PROVIDER_API_FOOTBALL, PROVIDER_FOOTBALL_DATA, league_provider)


class IdentityError(ValueError):
    """
    Eine Vereinsidentitaet ist nicht aufloesbar oder mehrdeutig.

    Eigene Klasse, damit ein Aufrufer sie von einem gewoehnlichen
    Fehler unterscheiden kann. Sie wird nie stillschweigend behandelt:
    Der betroffene Verein bekommt kein nationales Profil.
    """


@functools.lru_cache(maxsize=1)
def _bruecke():
    """
    Die geprueften Brueckentabellen, einmal gebaut.

    Rueckgabe: (fd_zu_api, api_zu_fd, diagnose).

    Gepuffert, weil der Aufbau die Crosswalkdateien liest und der
    Datensatzbau ihn je Spieltag braeuchte. Der Inhalt haengt
    ausschliesslich an lokalen Dateien, nicht an der Zeit.
    """
    from src.features.squad_crosswalk import build_team_crosswalk

    fd_zu_api, roh = build_team_crosswalk()

    rueckwaerts = {}
    konflikte = {}
    for fd_id, api_id in fd_zu_api.items():
        if api_id in rueckwaerts:
            konflikte.setdefault(api_id, {rueckwaerts[api_id]}).add(fd_id)
        else:
            rueckwaerts[api_id] = fd_id

    # Mehrdeutige Ziele fliegen aus BEIDEN Richtungen. Ein Profil, das
    # zwei Vereinen gehoeren koennte, gehoert keinem.
    for api_id in konflikte:
        rueckwaerts.pop(api_id, None)
    vorwaerts = {fd: api for fd, api in fd_zu_api.items()
                 if api not in konflikte}

    diagnose = {
        "entries_forward": len(vorwaerts),
        "entries_backward": len(rueckwaerts),
        "ambiguous_targets": {int(k): sorted(v)
                              for k, v in konflikte.items()},
        "source_diagnosis": {k: v for k, v in (roh or {}).items()
                             if not isinstance(v, (list, dict))},
    }
    return vorwaerts, rueckwaerts, diagnose


def reset_cache():
    """Den Puffer leeren - fuer Tests, die den Crosswalk austauschen."""
    _bruecke.cache_clear()


def to_api_football(fd_team_id):
    """
    Die API-Football-Kennung eines football-data-Vereins, oder None.

    None heisst "nicht aufloesbar" und ist ein gueltiges Ergebnis. Es
    heisst NICHT "nimm dieselbe Zahl".
    """
    vorwaerts, _, _ = _bruecke()
    return vorwaerts.get(fd_team_id)


def to_football_data(api_team_id):
    """
    Die football-data-Kennung eines API-Football-Vereins, oder None.

    Die Richtung, die der Profilpfad braucht: Aus einer nationalen
    Ligadatei kommen API-Football-Kennungen, die Champions League
    fuehrt football-data-Kennungen.
    """
    _, rueckwaerts, _ = _bruecke()
    return rueckwaerts.get(api_team_id)


def _mit_kanonischer_id(profil, fd_id):
    """
    Eine KOPIE des Profils, deren team_id im football-data-Raum liegt.

    Flach kopiert, weil genau ein Feld ersetzt wird und die uebrigen
    Werte Zahlen und Zeichenketten sind. Eine tiefe Kopie waere hier
    Aufwand ohne Wirkung; entscheidend ist nur, dass das Objekt des
    Aufrufers unberuehrt bleibt.

    Kein zweites Feld fuer die Provider-ID: Nachgemessen liest sie im
    Profilpfad niemand. Wer die Gegenrichtung braucht, fragt den
    geprueften Crosswalk (to_api_football) - eine zweite, im Profil
    mitgefuehrte Kopie koennte von ihm abweichen.
    """
    if not isinstance(profil, dict):                 # pragma: no cover
        raise IdentityError(
            f"Profil zu {fd_id!r} ist kein Objekt: {type(profil).__name__}")
    return dict(profil, team_id=fd_id)


def translate_profiles(profile_nach_api_id, league_code):
    """
    Profile einer Ligadatei auf den football-data-Namensraum legen.

    DER KERN DER SACHE
    Es wird NICHT gefragt "gibt es die football-data-ID 732 in dieser
    Ligadatei". Diese Frage waere die Falle: In NL1 gaebe es die 732
    moeglicherweise, sie waere dort aber ein anderer Verein.

    Stattdessen werden ALLE Profile der Liga gebaut und anschliessend
    diejenigen behalten, deren API-Football-Kennung sich eindeutig auf
    eine football-data-Kennung zurueckfuehren laesst. Wer sich nicht
    zurueckfuehren laesst, faellt weg. Damit kann kein Verein die
    Ergebnisse eines numerisch kollidierenden fremden Vereins
    bekommen - die Zahl wird nie als Schluessel wiederverwendet.

    Fuer Ligen im football-data-Namensraum ist die Uebersetzung die
    Identitaet; die IDs stammen bereits aus demselben Raum wie die CL.

    DER SCHLUESSEL ALLEIN GENUEGT NICHT (V2-C18)
    --------------------------------------------
    Bis hierher wurde nur der Dict-SCHLUESSEL uebersetzt. Das Feld
    profil["team_id"] blieb im Namensraum des Providers stehen, aus
    dessen Ligadatei das Profil gebaut wurde. Fuer die fuenf Top-Ligen
    faellt das nicht auf, weil beide Raeume dort dieselben Zahlen
    benutzen. Fuer die 18 mit C13 ergaenzten Ligen laufen sie
    auseinander - und ein Verbraucher, der die Identitaet aus dem
    Profil statt aus dem Schluessel liest, bekam eine Zahl, die in
    SEINEM Namensraum einen anderen oder gar keinen Verein bezeichnet.

    Gemessen hat das die Ligastaerkekorrektur getroffen
    (inference._ligastaerke_anwenden liest die Team-ID aus dem Profil):
    Zehn der 36 Teilnehmer einer laufenden Ligaphase verloren dadurch
    ihre Ligazuordnung, und die zweite Modellstufe fiel in 96 von 126
    offenen Partien still aus - ausgerechnet bei den Vereinen, fuer
    die sie gebaut wurde.

    Deshalb gilt hier ab sofort ausnahmslos:

        heraus[fd_id]["team_id"] == fd_id

    Schluessel und kanonische Payload-ID liegen im selben Raum. Das
    ist dieselbe Zusage, die strength_provider fuer den nationalen
    Pfad bereits gibt (dort merged["team_id"] = team_id).

    Die Eingabeprofile werden dabei NICHT veraendert. Der Aufrufer
    (pit_profiles.domestic_profiles) puffert seine Quellprofile ueber
    mehrere Ligen und Saisons hinweg; ein In-place-Schreiben wuerde
    einen gepufferten Wert nachtraeglich umdeuten.
    """
    provider = league_provider(league_code)

    if provider == PROVIDER_FOOTBALL_DATA:
        # Auch hier normalisiert, nicht nur durchgereicht: Die Zusage
        # "Schluessel gleich team_id" soll ohne Fallunterscheidung
        # gelten. Inhaltlich ist es fuer diesen Provider ein
        # Nullschritt, denn beide Zahlen stammen aus demselben Raum.
        heraus = {fd_id: _mit_kanonischer_id(profil, fd_id)
                  for fd_id, profil in profile_nach_api_id.items()}
        return heraus, {
            "league": league_code, "provider": provider,
            "translated": 0, "kept": len(heraus),
            "dropped_unmapped": 0, "id_normalised": len(heraus)}

    if provider != PROVIDER_API_FOOTBALL:            # pragma: no cover
        raise IdentityError(
            f"{league_code!r} hat den unbekannten Provider {provider!r}")

    heraus = {}
    verworfen = 0
    for api_id, profil in profile_nach_api_id.items():
        fd_id = to_football_data(api_id)
        if fd_id is None:
            verworfen += 1
            continue
        heraus[fd_id] = _mit_kanonischer_id(profil, fd_id)

    return heraus, {
        "league": league_code, "provider": provider,
        "translated": len(heraus), "kept": len(heraus),
        "dropped_unmapped": verworfen, "id_normalised": len(heraus)}


def identity_report():
    """Der Zustand der Brücke - fuer Artefakt und Bericht."""
    vorwaerts, rueckwaerts, diagnose = _bruecke()
    return {
        "forward_entries": len(vorwaerts),
        "backward_entries": len(rueckwaerts),
        "ambiguous_targets": diagnose["ambiguous_targets"],
        "rule": ("Provider plus Zahl ergeben eine Identitaet. Eine Zahl "
                 "allein nicht."),
        "reverse_direction": ("API-Football -> football-data, weil die "
                              "Champions League in football-data-"
                              "Kennungen gefuehrt wird."),
        "on_conflict": ("Ein API-Football-Verein, auf den zwei "
                        "football-data-Vereine zeigen, wird aus beiden "
                        "Richtungen entfernt."),
    }
