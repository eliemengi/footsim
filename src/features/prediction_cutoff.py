"""
Der eine Prediction-Cutoff (V2-C10).

DIE REGEL
---------
Fuer eine Vorhersage duerfen ausschliesslich Informationen verwendet
werden, die zum festgelegten Stichtag bereits verfuegbar waren.

WARUM ES DIESE DATEI GIBT
-------------------------
Der Stichtag existierte vor C10 dreimal, in drei Formaten:

    dataset.prediction_cutoff(datum)   datetime, naiv, Spieltag 12:00
    pit_profiles.require_cutoff(x)     ISO-TEXT, meist nur das Datum
    snapshot_reader._als_utc(x)        ISO-Text, teils mit Zonenanhang

Sie stimmten ueberein, solange niemand hinsah. Gemessen wurde folgender
Fall: Ein Snapshot mit captured_at "2025-03-11T06:00:00+00:00" liegt

    vor "2025-03-11T12:00:00"        -> Training nimmt ihn
    nach "2025-03-11"                -> Laufzeit nimmt ihn nicht

Derselbe Match, derselbe Datenbestand, zwei verschiedene
Informationsstaende. Der Vergleich ist ein TEXTvergleich, und
"2025-03-11" ist ein Praefix von "2025-03-11T06:00:00" - kuerzer heisst
kleiner. Das ist kein Tippfehler in einer Zeile, sondern die
zwangslaeufige Folge davon, dass drei Stellen dasselbe Wort
verschieden buchstabieren.

ZWEI SKALEN, BEIDE AUSDRUECKLICH
--------------------------------
Der Bestand kennt zwei Genauigkeiten, und das laesst sich nicht
wegdefinieren:

    Tagesskala      data/historical fuehrt ausschliesslich "date".
                    point_in_time.match_time() liest "utc_date" und
                    "utcDate" - beide fehlen dort. Ein Vergleich auf
                    Stundenebene ist mit diesen Dateien unmoeglich.

    Zeitpunktskala  Zeitleiste und Snapshotarchiv fuehren echte
                    Zeitstempel. Dort ist die Stunde entscheidbar und
                    entscheidet auch.

Diese Datei liefert BEIDE als benannte Zugriffe (day_key und
instant_key) statt einer, die je nach Aufrufer etwas anderes bedeutet.
Wer die falsche waehlt, tut es sichtbar.

ZEITZONEN
---------
Der kanonische Wert ist zeitzonenbehaftet und in UTC. Nach aussen -
Serialisierung, Artefakte, Metadaten - geht ausschliesslich er.

Intern rechnet das Projekt seit jeher in NAIVER UTC:
match_timeline._to_datetime() rechnet jeden Zeitstempel auf UTC um und
streift die Zone ab, damit zwei Quellen nicht um den Zonenversatz
auseinanderliegen. Diese Skala wird hier nicht umgebaut - ein solcher
Umbau traefe point_in_time, die Zeitleiste, jeden Vergleich und den
eingefrorenen C9-Stand.

Stattdessen ist die Umrechnung an genau EINER Stelle gebuendelt und
benannt: naive Eingaben gelten als UTC (nicht als Ortszeit), und
zonenbehaftete werden umgerechnet, nicht abgeschnitten. Wer lokale Zeit
hereinreicht, bekommt sie als UTC gelesen - deshalb steht es hier so
deutlich.

FAIL CLOSED
-----------
Kein Standardwert, keine stille Gegenwart. Ohne Stichtag gibt es keine
Vorhersage. "Jetzt" entsteht ausschliesslich in now(), am Rand, und
wird von dort weitergereicht.
"""

from datetime import date, datetime, time, timedelta, timezone

from src.features.pit_profiles import MissingCutoff

#: Fassung des Cutoff-Vertrags.
CONTRACT_VERSION = 1

#: Die Stunde, auf die ein reines Datum gehoben wird.
#:
#: Zwoelf, und der Wert ist nicht frei waehlbar: Er MUSS mit
#: match_timeline.FALLBACK_KICKOFF_HOUR uebereinstimmen. Dort bekommt
#: eine Partie ohne Anstosszeit den Zeitstempel Tag@12:00; hier bekommt
#: der Stichtag derselben Partie Tag@12:00. Der Filter ist strikt
#: kleiner, also faellt die Partie aus ihrem EIGENEN Merkmalsfenster.
#:
#: Waere diese Stunde groesser als die Rueckfallstunde, geriete jede
#: Partie ohne Anstosszeit in ihre eigenen Merkmale - ein Selbstleck,
#: das keine Kennzahl auffangen wuerde, weil es wie ein sehr gutes
#: Modell aussieht. Waere sie kleiner, verschwaende man einen halben
#: Tag Information.
#:
#: assert_hours_match() prueft die Gleichheit, und ein Test ruft sie.
#: Vor C10 stand die Kopplung nirgends und haette bei einer Aenderung
#: an einer der beiden Stellen still nachgegeben.
CUTOFF_HOUR = 12

#: Ein Datensatz GENAU am Stichtag gilt als unbekannt.
#:
#: Uebernommen aus point_in_time.CUTOFF_INCLUSIVE und
#: pit_profiles.CUTOFF_INCLUSIVE, nicht neu entschieden. Die Regel
#: kostet im schlimmsten Fall einen Stand und verhindert, dass ein zur
#: Anpfiffsekunde erhobener Kader in die Vorhersage derselben Partie
#: geraet.
CUTOFF_INCLUSIVE = False

#: Das kanonische Textformat der Zeitpunktskala.
#:
#: Ohne Zonenanhang, feste Laenge. Beides ist noetig, weil an mehreren
#: Stellen TEXTE verglichen werden (snapshot_archive vergleicht
#: captured_at lexikografisch). Ein Vergleich zwischen
#: "2025-03-11T12:00:00+00:00" und "2025-03-11T12:00:00" ist
#: lexikografisch falsch, obwohl beide denselben Zeitpunkt meinen -
#: gemessen, siehe Modulkopf.
INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S"
DAY_FORMAT = "%Y-%m-%d"


def assert_hours_match(timeline_hour=None):
    """
    Die Kopplung zwischen Stichtagsstunde und Rueckfallstunde pruefen.

    Bricht ab, wenn sie auseinanderlaufen. Der Aufruf gehoert in einen
    Test, nicht in den heissen Pfad - aber er gehoert in DIESE Datei,
    damit die Begruendung neben der Zahl steht.
    """
    if timeline_hour is None:
        from src.features import match_timeline as mt

        timeline_hour = mt.FALLBACK_KICKOFF_HOUR

    if timeline_hour != CUTOFF_HOUR:
        raise ValueError(
            f"Stichtagsstunde {CUTOFF_HOUR} und Rueckfallstunde "
            f"{timeline_hour} stimmen nicht ueberein. Eine Partie ohne "
            f"Anstosszeit bekommt den Zeitstempel Tag@{timeline_hour}:00 "
            f"und ihr Stichtag liegt bei Tag@{CUTOFF_HOUR}:00; laufen "
            f"die beiden auseinander, faellt die Partie entweder in ihr "
            f"eigenes Merkmalsfenster oder ein halber Tag Information "
            f"geht verloren.")
    return True


class PredictionCutoff:
    """
    Ein Stichtag - unveraenderlich, in UTC, mit beiden Skalen.

    Erzeugen ueber die Klassenmethoden, nicht ueber den Konstruktor:
    Jede von ihnen steht fuer eine fachliche Herkunft, und genau die
    soll im Aufruf lesbar sein.

        for_match_day("2025-03-11")   ein historisches Spiel
        parse("2025-03-11T12:00:00")  ein serialisierter Stichtag
        at(datetime(...))             ein bekannter Zeitpunkt
        now()                         der Rand der Laufzeit
    """

    __slots__ = ("_utc", "_precision")

    #: Der Stichtag stammt aus einem reinen Datum und wurde auf
    #: CUTOFF_HOUR gehoben.
    PRECISION_DAY = "day"

    #: Der Stichtag war bereits ein Zeitpunkt.
    PRECISION_INSTANT = "instant"

    def __init__(self, utc, precision):
        if utc.tzinfo is None:                           # pragma: no cover
            raise MissingCutoff("PredictionCutoff braucht UTC")
        self._utc = utc
        self._precision = precision

    # -- Erzeugung --------------------------------------------------------

    @classmethod
    def for_match_day(cls, tag):
        """
        Der Stichtag eines Spieltags.

        tag: "YYYY-MM-DD", date oder datetime. Ein datetime wird auf
        seinen Datumsanteil reduziert - wer den Zeitpunkt behalten will,
        nimmt at().

        Das ist der Trainingsvertrag: dataset.build_dataset setzt genau
        diesen Stichtag fuer jede Zeile.
        """
        if tag is None:
            raise MissingCutoff(
                "Ein Spieltag ohne Datum hat keinen Stichtag.")

        if isinstance(tag, datetime):
            tag = tag.date()
        elif isinstance(tag, str):
            text = tag.strip()
            if len(text) < 10:
                raise MissingCutoff(f"Unbrauchbarer Spieltag: {tag!r}")
            try:
                tag = date.fromisoformat(text[:10])
            except ValueError as fehler:
                raise MissingCutoff(
                    f"Unbrauchbarer Spieltag: {tag!r}") from fehler
        elif not isinstance(tag, date):
            raise MissingCutoff(f"Unbrauchbarer Spieltag: {tag!r}")

        return cls(datetime.combine(tag, time(CUTOFF_HOUR, 0),
                                    tzinfo=timezone.utc),
                   cls.PRECISION_DAY)

    @classmethod
    def at(cls, zeitpunkt):
        """
        Ein bekannter Zeitpunkt als Stichtag.

        Naiv heisst UTC. Diese Annahme ist die einzige im ganzen
        Vertrag, sie steht hier und sie ist begruendet: Das Projekt
        rechnet intern durchgehend in naiver UTC (siehe Modulkopf).
        Eine naive Eingabe als Ortszeit zu lesen waere die
        gefaehrlichere Annahme, weil sie vom Rechner abhinge.
        """
        if zeitpunkt is None:
            raise MissingCutoff("Ein Stichtag darf nicht None sein.")
        if not isinstance(zeitpunkt, datetime):
            raise MissingCutoff(
                f"at() braucht ein datetime, bekommen: {zeitpunkt!r}")

        if zeitpunkt.tzinfo is None:
            zeitpunkt = zeitpunkt.replace(tzinfo=timezone.utc)
        return cls(zeitpunkt.astimezone(timezone.utc),
                   cls.PRECISION_INSTANT)

    @classmethod
    def parse(cls, text):
        """
        Einen serialisierten Stichtag zurueckholen.

        Akzeptiert "YYYY-MM-DD" (Tagesskala), volle ISO-Zeitpunkte mit
        und ohne Zone sowie das "Z"-Suffix. Die Rundreise ueber iso()
        ist verlustfrei; ein Test haelt das fest.
        """
        if text is None:
            raise MissingCutoff("Ein Stichtag darf nicht None sein.")
        if isinstance(text, PredictionCutoff):
            return text
        if isinstance(text, datetime):
            return cls.at(text)
        if isinstance(text, date):
            return cls.for_match_day(text)

        roh = str(text).strip()
        if len(roh) == 10:
            return cls.for_match_day(roh)
        try:
            wert = datetime.fromisoformat(roh.replace("Z", "+00:00"))
        except ValueError as fehler:
            raise MissingCutoff(
                f"Unbrauchbarer Stichtag: {text!r}") from fehler
        return cls.at(wert)

    @classmethod
    def now(cls, jetzt=None):
        """
        Der Rand der Laufzeit - die EINZIGE Stelle mit "jetzt".

        jetzt laesst sich injizieren; ohne Angabe gilt die Systemuhr in
        UTC. Tiefer liegende Funktionen duerfen diese Methode NICHT
        rufen: Sobald zwei Stellen unabhaengig "jetzt" bestimmen, sind
        zwei Laeufe derselben Simulation nicht mehr vergleichbar.
        """
        return cls.at(jetzt if jetzt is not None
                      else datetime.now(timezone.utc))

    # -- Skalen -----------------------------------------------------------

    @property
    def utc(self):
        """Der kanonische, zeitzonenbehaftete Wert."""
        return self._utc

    @property
    def precision(self):
        return self._precision

    def instant_key(self):
        """
        Die Zeitpunktskala als Text: "YYYY-MM-DDTHH:MM:SS".

        Fuer Zeitleiste und Snapshotarchiv. Ohne Zonenanhang und mit
        fester Laenge, damit der dort uebliche TEXTvergleich stimmt.
        """
        return self._utc.strftime(INSTANT_FORMAT)

    def day_key(self):
        """
        Die Tagesskala als Text: "YYYY-MM-DD".

        Fuer den Profilpfad. team_profile.build_season_profiles und
        point_in_time.is_known_at vergleichen Datumsanteile; eine
        Uhrzeit waere dort wirkungslos, weil die Historie keine fuehrt -
        aber sie waere sichtbar und wuerde Gleichheit vortaeuschen, wo
        keine geprueft wird.
        """
        return self._utc.strftime(DAY_FORMAT)

    def naive_utc(self):
        """Der Wert auf der internen Skala: UTC ohne Zonenangabe."""
        return self._utc.replace(tzinfo=None)

    def iso(self):
        """Serialisierung nach aussen: ISO 8601 mit Z."""
        return self._utc.strftime(INSTANT_FORMAT) + "Z"

    # -- Die Grenzregel ---------------------------------------------------

    def allows(self, zeitpunkt, inclusive=None):
        """
        War dieser Zeitpunkt zum Stichtag bereits bekannt?

        Naive Zeitpunkte gelten als UTC - dieselbe Annahme wie in at(),
        aus demselben Grund. Ein unlesbarer Zeitpunkt ist NICHT bekannt:
        Ein Datensatz, dessen Zeit sich nicht pruefen laesst, darf nicht
        stillschweigend in die Vergangenheit gerechnet werden.
        """
        inclusive = CUTOFF_INCLUSIVE if inclusive is None else inclusive

        if zeitpunkt is None:
            return False
        if isinstance(zeitpunkt, str):
            try:
                zeitpunkt = datetime.fromisoformat(
                    zeitpunkt.strip().replace("Z", "+00:00"))
            except ValueError:
                return False
        if isinstance(zeitpunkt, datetime):
            if zeitpunkt.tzinfo is None:
                zeitpunkt = zeitpunkt.replace(tzinfo=timezone.utc)
        elif isinstance(zeitpunkt, date):
            zeitpunkt = datetime.combine(zeitpunkt, time(CUTOFF_HOUR, 0),
                                         tzinfo=timezone.utc)
        else:
            return False

        if inclusive:
            return zeitpunkt <= self._utc
        return zeitpunkt < self._utc

    # -- Verhalten --------------------------------------------------------

    def shifted(self, **delta):
        """Ein verschobener Stichtag - fuer Tests und Replayfenster."""
        return PredictionCutoff.at(self._utc + timedelta(**delta))

    def __eq__(self, andere):
        return (isinstance(andere, PredictionCutoff)
                and self._utc == andere._utc)

    def __lt__(self, andere):
        return self._utc < andere._utc

    def __hash__(self):
        return hash(self._utc)

    def __repr__(self):
        return f"PredictionCutoff({self.iso()!r}, {self._precision})"


# ---------------------------------------------------------------------------
# Ein- und Ausgang
# ---------------------------------------------------------------------------

def require(cutoff):
    """
    Einen Stichtag erzwingen - fail closed.

    Jeder zeitkritische Pfad ruft das am Eingang. None ist ein Fehler,
    kein Anlass, auf den neuesten Stand zu springen.
    """
    if cutoff is None:
        raise MissingCutoff(
            "Dieser Pfad braucht einen ausdruecklichen "
            "prediction_cutoff. Historisches Training und Replay "
            "liefern ihn aus dem Spieltag "
            "(PredictionCutoff.for_match_day), die Laufzeit einmalig "
            "am Rand (PredictionCutoff.now).")
    if isinstance(cutoff, PredictionCutoff):
        return cutoff
    return PredictionCutoff.parse(cutoff)


def contract():
    """Der Vertrag in Textform - fuer Artefakt und Bericht."""
    return {
        "contract_version": CONTRACT_VERSION,
        "canonical_timezone": "UTC",
        "canonical_serialization": "ISO 8601, Sekundengenau, Suffix Z",
        "cutoff_hour": CUTOFF_HOUR,
        "cutoff_inclusive": CUTOFF_INCLUSIVE,
        "boundary_rule": (
            "Ein Datensatz GENAU am Stichtag gilt als unbekannt "
            "(strikt kleiner). Uebernommen aus "
            "point_in_time.CUTOFF_INCLUSIVE, nicht neu entschieden."),
        "naive_input_rule": (
            "Ein naiver Zeitpunkt gilt als UTC, nicht als Ortszeit. Das "
            "Projekt rechnet intern durchgehend in naiver UTC "
            "(match_timeline._to_datetime rechnet um und streift die "
            "Zone ab); eine Ortszeitannahme haenge am Rechner."),
        "scales": {
            "day_key": ("YYYY-MM-DD, fuer den Profilpfad. Die Historie "
                        "fuehrt nur 'date'; eine Uhrzeit waere dort "
                        "wirkungslos, aber sichtbar."),
            "instant_key": ("YYYY-MM-DDTHH:MM:SS ohne Zonenanhang, fuer "
                            "Zeitleiste und Snapshotarchiv. Feste "
                            "Laenge, weil dort Texte verglichen "
                            "werden."),
        },
        "fail_closed": (
            "Ohne Stichtag ein MissingCutoff. Kein Standardwert, kein "
            "Rueckfall auf den neuesten Stand."),
        "now_is_an_edge": (
            "PredictionCutoff.now() ist die einzige Stelle, die die "
            "Systemuhr liest. Tiefer liegende Funktionen bekommen den "
            "Stichtag gereicht."),
        "hour_coupling": (
            f"CUTOFF_HOUR ({CUTOFF_HOUR}) muss "
            f"match_timeline.FALLBACK_KICKOFF_HOUR entsprechen, sonst "
            f"faellt eine Partie ohne Anstosszeit in ihr eigenes "
            f"Merkmalsfenster. assert_hours_match() prueft es."),
    }
