/* ============================================================
   FootSim - Frontend

   Aufbau:
     1. Elemente und Zustand
     2. Hilfsfunktionen
     3. Saisonwahl
     4. Modus Umschalter
     5. Wettbewerbe
     6. Spieltage
     7. Champions League Runden
     8. Tabs
     9. Spiele und Simulationssteuerung
    10. Tabelle
    11. Torjäger
    12. Simulation
    13. Ligenvergleich, national
    14. Ligenvergleich im Pokal
    15. Start
   ============================================================ */


/* ---------- 1. ELEMENTE UND ZUSTAND ---------- */

const el = (id) => document.getElementById(id);

/* ---------- Internationalisierung ---------- */

const I18N_STORAGE_KEY = "footsim_lang";
const I18N_DEFAULT_LOCALE = "en";

/* ---------- CSRF Helper ---------- */
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

/** Updates the token every future getCsrfToken() call will read. */
function setCsrfToken(token) {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && token) meta.setAttribute('content', token);
}

/**
 * Fetches a fresh token for the current session without a full page
 * reload. Safe to call anytime: GET isn't CSRF-protected, and
 * generate_csrf() server-side reuses the session's token if one still
 * exists - it only replaces a token that is missing, invalid, or
 * expired, which is exactly the condition this recovers from.
 */
async function refreshCsrfToken() {
    try {
        const response = await fetch('/api/auth/csrf-token');
        if (!response.ok) return null;
        const data = await response.json();
        if (data && data.csrf_token) {
            setCsrfToken(data.csrf_token);
            return data.csrf_token;
        }
    } catch (_) {
        // No network, no recovery this time - the caller falls back to
        // reporting the original CSRF failure.
    }
    return null;
}
const I18N_SUPPORTED_LOCALES = new Set(["de", "en"]);

let activeLocale = document.documentElement.lang === "de" ? "de" : I18N_DEFAULT_LOCALE;
let activeTranslations = {};
let englishTranslations = {};

function normalizeLocale(value) {
    if (typeof value !== "string") return null;
    const base = value.trim().toLowerCase().replace("_", "-").split("-", 1)[0];
    return I18N_SUPPORTED_LOCALES.has(base) ? base : null;
}

function browserLocale() {
    const languages = Array.isArray(navigator.languages) && navigator.languages.length
        ? navigator.languages
        : [navigator.language];
    for (const language of languages) {
        const normalized = normalizeLocale(language);
        if (normalized) return normalized;
    }
    return I18N_DEFAULT_LOCALE;
}

function persistedLocale() {
    try {
        return normalizeLocale(window.localStorage.getItem(I18N_STORAGE_KEY));
    } catch (_) {
        return null;
    }
}

function explicitLocale() {
    return normalizeLocale(new URL(window.location.href).searchParams.get("lang"));
}

function selectedLocale() {
    return explicitLocale() || persistedLocale() || browserLocale();
}

function catalogValue(catalog, key) {
    const value = catalog && catalog[key];
    return typeof value === "string" ? value : null;
}

/**
 * Letzter Ausweg, wenn ein Schluessel in keinem Katalog steht.
 *
 * Frueher wurde der Schluessel selbst angezeigt - im UI standen dann
 * woertlich Zeichenfolgen wie "player.scopeHint.club_all". Das ist fuer
 * Nutzer bedeutungslos und sieht nach einem Defekt aus.
 *
 * Stattdessen wird der letzte Bestandteil lesbar gemacht. Das ist kein
 * Ersatz fuer eine Uebersetzung, aber es ist Text statt Technik.
 */
function humanizeKey(key) {
    if (typeof key !== "string" || !key) return "";
    const letzter = key.split(".").pop() || key;
    const worte = letzter
        .replace(/[_-]+/g, " ")
        .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
        .trim();
    return worte ? worte.charAt(0).toUpperCase() + worte.slice(1) : "";
}

function t(key, params = {}) {
    const template = catalogValue(activeTranslations, key)
        || catalogValue(englishTranslations, key)
        || humanizeKey(key);
    return template.replace(/\{([A-Za-z0-9_]+)\}/g, (placeholder, name) => (
        Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : placeholder
    ));
}

function activeIntlLocale() {
    return activeLocale === "de" ? "de-DE" : "en-US";
}

function visibleApiError(data, fallbackKey = "error.requestFailed", params = {}) {
    const errorKey = data && (data.error_key || data.errorKey || data.code);
    if (typeof errorKey === "string"
        && (catalogValue(activeTranslations, errorKey) || catalogValue(englishTranslations, errorKey))) {
        // error_params erlaubt dem Backend, Werte in die Meldung zu
        // reichen, die nur es kennt - etwa die betroffene Saison. Damit
        // bleibt die Jahreszahl aus dem Uebersetzungskatalog heraus,
        // ohne dass jeder Aufrufer sie selbst mitgeben muesste.
        const merged = { ...params, ...((data && data.error_params) || {}) };
        return t(errorKey, merged);
    }
    // Legacy endpoints still expose German prose in `error`. Only show it
    // in a German UI; English falls back to a translated, stable message.
    if (activeLocale === "de" && data && typeof data.error === "string") return data.error;
    return t(fallbackKey, params);
}

const SCOPE_TRANSLATION_KEYS = {
    club_all: "scope.clubAll",
    league: "scope.league",
    cl: "scope.cl",
    euro: "scope.euro",
    world_cup: "scope.worldCup",
    national: "scope.national",
    all: "scope.all",
    big_games: "scope.bigGames",
};

const POSITION_TRANSLATION_KEYS = {
    Goalkeeper: "playerPosition.goalkeeper",
    Defender: "playerPosition.defender",
    Midfielder: "playerPosition.midfielder",
    Attacker: "playerPosition.attacker",
};

function translatedScope(scope, fallback = "") {
    const key = SCOPE_TRANSLATION_KEYS[scope];
    return key ? t(key) : fallback;
}

function translatedPosition(position, fallback = "") {
    const key = POSITION_TRANSLATION_KEYS[position];
    return key ? t(key) : fallback;
}

function localizedMetric(meta) {
    if (!meta || typeof meta !== "object") return meta;
    const labelKey = meta.key ? `metric.${meta.key}` : null;
    const hasLabel = labelKey && (catalogValue(activeTranslations, labelKey) || catalogValue(englishTranslations, labelKey));
    return {
        ...meta,
        label: hasLabel ? t(labelKey) : meta.label,
        // Existing API metric descriptions are German prose. Until their
        // stable keys are added, omit them in English rather than mixing
        // languages in an otherwise English player result.
        description: activeLocale === "en" ? "" : (meta.description || ""),
    };
}

function localizedPlayer(player) {
    if (!player || typeof player !== "object") return player;
    return {
        ...player,
        position_label: translatedPosition(player.position, player.position_label || ""),
        scope_label: translatedScope(player.scope, player.scope_label || ""),
    };
}

function localizedComparisonPayload(data) {
    if (!data || typeof data !== "object") return data;
    const comparison = data.comparison && typeof data.comparison === "object"
        ? {
            ...data.comparison,
            metrics: (data.comparison.metrics || []).map(localizedMetric),
        }
        : data.comparison;
    return {
        ...data,
        player_a: localizedPlayer(data.player_a),
        player_b: localizedPlayer(data.player_b),
        scope_label: translatedScope(data.scope, data.scope_label || ""),
        comparison,
    };
}

// Live-API liefert fuer die Statusanzeige aus Kompatibilitaetsgruenden noch
// ein deutsches Fallback-Label. Im sichtbaren UI wird deshalb immer zuerst
// der stabile Provider-Code uebersetzt. Fuer einen neuen, unbekannten Code
// zeigen englische Oberflaechen nur den Code statt deutscher Fremdprosa.
const LIVE_STATUS_TRANSLATION_KEYS = {
    TBD: "live.status.tbd",
    NS: "live.status.scheduled",
    "1H": "live.status.firstHalf",
    "2H": "live.status.secondHalf",
    ET: "live.status.extraTime",
    P: "live.status.penalties",
    LIVE: "live.status.live",
    HT: "live.status.halfTime",
    BT: "live.status.breakBeforeExtraTime",
    SUSP: "live.status.suspended",
    INT: "live.status.suspended",
    FT: "live.status.finished",
    AET: "live.status.finishedAet",
    PEN: "live.status.finishedPenalties",
    PST: "live.status.postponed",
    CANC: "live.status.cancelled",
    ABD: "live.status.abandoned",
    AWD: "live.status.awarded",
    WO: "live.status.walkover",
};

function localizedLiveStatus(subject) {
    const statusShort = typeof (subject && subject.status_short) === "string"
        ? subject.status_short.toUpperCase()
        : "";
    const key = LIVE_STATUS_TRANSLATION_KEYS[statusShort];
    if (key) return t(key);

    if (activeLocale === "en") return statusShort || t("live.status.unknown");
    return (subject && subject.status_label) || statusShort || t("live.status.unknown");
}

const MATCH_STAT_TRANSLATION_KEYS = {
    "Ball Possession": "matchCenter.stats.ballPossession",
    "Total Shots": "matchCenter.stats.totalShots",
    "Shots on Goal": "matchCenter.stats.shotsOnGoal",
    "Corner Kicks": "matchCenter.stats.cornerKicks",
    Fouls: "matchCenter.stats.fouls",
    Offsides: "matchCenter.stats.offsides",
    "Shots off Goal": "matchCenter.stats.shotsOffGoal",
    "Blocked Shots": "matchCenter.stats.blockedShots",
    "Shots insidebox": "matchCenter.stats.shotsInsideBox",
    "Shots outsidebox": "matchCenter.stats.shotsOutsideBox",
    "Goalkeeper Saves": "matchCenter.stats.goalkeeperSaves",
    "Total passes": "matchCenter.stats.totalPasses",
    "Passes accurate": "matchCenter.stats.accuratePasses",
    "Passes %": "matchCenter.stats.passAccuracy",
    "Yellow Cards": "matchCenter.stats.yellowCards",
    "Red Cards": "matchCenter.stats.redCards",
    expected_goals: "matchCenter.stats.expectedGoals",
};

function localizedMatchStatLabel(stat) {
    const key = stat && MATCH_STAT_TRANSLATION_KEYS[stat.key];
    return key ? t(key) : ((stat && stat.label) || "");
}

function localizedBigGamesMetricLabel(metric) {
    if (!metric || !metric.key) return (metric && metric.label) || "";
    const key = `bigGames.metric.${metric.key}`;
    if (catalogValue(activeTranslations, key) || catalogValue(englishTranslations, key)) {
        return t(key);
    }
    // Avoid mixing the legacy German backend label into an English result
    // while a newly introduced metric key is not yet in a catalog.
    return activeLocale === "de" ? (metric.label || metric.key) : metric.key;
}

async function loadCatalog(locale) {
    const response = await fetch(`/static/i18n/${locale}.json`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`i18n catalog ${locale} unavailable`);
    const payload = await response.json();
    return payload && typeof payload === "object" ? payload : {};
}

function applyTranslations() {
    document.documentElement.lang = activeLocale;
    document.body.dataset.locale = activeLocale;
    document.querySelectorAll("[data-i18n]").forEach((node) => {
        node.textContent = t(node.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((node) => {
        node.setAttribute("aria-label", t(node.dataset.i18nAria));
    });
    document.querySelectorAll("[data-i18n-title]").forEach((node) => {
        node.title = t(node.dataset.i18nTitle);
    });
    // Dynamisch gesetzte Texte mitnehmen. applyTranslations() erreicht
    // sonst nur data-i18n-Elemente; alles per textContent Geschriebene
    // bliebe in der alten Sprache - oder, beim ersten Lauf, beim rohen
    // Schluessel stehen.
    if (typeof pcRetranslateDynamicText === "function") {
        pcRetranslateDynamicText();
    }

    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
        node.placeholder = t(node.dataset.i18nPlaceholder);
    });
    document.querySelectorAll(".language-btn").forEach((button) => {
        const selected = button.dataset.language === activeLocale;
        button.classList.toggle("active", selected);
        button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
}

async function initI18n() {
    const explicit = explicitLocale();
    if (explicit) {
        try {
            window.localStorage.setItem(I18N_STORAGE_KEY, explicit);
        } catch (_) {
            // The first-party server cookie remains the persistence fallback.
        }
    }
    const requested = selectedLocale();
    const documentLocale = normalizeLocale(document.documentElement.lang) || I18N_DEFAULT_LOCALE;

    try {
        englishTranslations = await loadCatalog("en");
        activeLocale = requested;
        activeTranslations = requested === "en" ? englishTranslations : await loadCatalog(requested);
    } catch (_) {
        // The server-rendered language remains usable when a catalog cannot be
        // retrieved (for example while an older PWA shell is offline).
        activeLocale = documentLocale;
        activeTranslations = {};
        englishTranslations = {};
    }

    // A persisted explicit choice must also update server-rendered metadata,
    // title and API status text after reload. Do one controlled reload only.
    if (requested !== documentLocale) {
        const url = new URL(window.location.href);
        url.searchParams.set("lang", requested);
        window.location.replace(url.toString());
        return false;
    }

    applyTranslations();
    return true;
}

function selectLocale(locale) {
    const normalized = normalizeLocale(locale);
    if (!normalized) return;
    // Eine bewusste Wahl wird auch dann festgehalten, wenn sie die
    // bereits aktive Sprache bestaetigt. Sonst entschiede spaeter wieder
    // die Browsersprache ueber eine Entscheidung, die der Nutzer
    // getroffen hat - im Onboarding ist genau das der Regelfall.
    try {
        window.localStorage.setItem(I18N_STORAGE_KEY, normalized);
    } catch (_) {
        // The first-party ?lang= bridge still makes the active choice work if
        // a privacy setting blocks local browser storage.
    }
    // Ohne Sprachwechsel gibt es nichts neu zu rendern. Aufrufer, die
    // trotzdem weiterschalten muessen (PWA-Onboarding), duerfen sich
    // deshalb nicht auf eine Navigation verlassen.
    if (normalized === activeLocale) return;
    const url = new URL(window.location.href);
    url.searchParams.set("lang", normalized);
    window.location.assign(url.toString());
}

const seasonDropdownBtn  = el("season-dropdown-btn");
const seasonDropdownLabel = el("season-dropdown-label");
const seasonDropdownList  = el("season-dropdown-list");

const competitionList   = el("competition-list");
const matchdaySection   = el("matchday-section");
const matchdayList      = el("matchday-list");
const matchdayHint      = el("matchday-hint");

// Champions League Phase Navigation (Block B2)
const clPhaseSection    = el("cl-phase-section");
const clMatchdaySection = el("cl-matchday-section");
const clMatchdayList    = el("cl-matchday-list");
const clMatchdayHint    = el("cl-matchday-hint");
const clKoStageSection  = el("cl-ko-stage-section");
const clKoStageList     = el("cl-ko-stage-list");
const clKoEmpty         = el("cl-ko-empty");

const leftEmptyState    = el("left-empty-state");
const statusBox         = el("status");

const tabBar            = el("tab-bar");
const emptyState        = el("empty-state");
const tabTable          = el("tab-table");
const tabScorers        = el("tab-scorers");
const tabFixtures       = el("tab-fixtures");
const tabSimulation     = el("tab-simulation");

const tableTitle        = el("table-title");
const tableContent      = el("table-content");
const tableTypeSwitch   = el("table-type-switch");
const scorersTitle      = el("scorers-title");
const scorersContent    = el("scorers-content");

const fixturesEyebrow   = el("fixtures-eyebrow");
const fixturesTitle     = el("fixtures-title");
const fixturesEmpty     = el("fixtures-empty");
const matchList         = el("match-list");
const simControls       = el("sim-controls");
const selectedMatchLabel = el("selected-match-label");
const simulateBtn       = el("simulate-btn");

const simEmpty          = el("sim-empty");
const resultBox         = el("result");
const knockoutSection   = el("knockout-section");
const knockoutContent   = el("knockout-content");
const backToFixtures    = el("back-to-fixtures");

const seasonSimEmpty    = el("season-sim-empty");
const seasonSimControls = el("season-sim-controls");
const seasonSimBtn      = el("season-sim-btn");
const seasonSimRerun    = el("season-sim-rerun");
const seasonSimResult   = el("season-sim-result");
const seasonSimTitle    = el("season-sim-title");
const seasonSimEyebrow  = el("season-sim-eyebrow");
const seasonSimFavorite = el("season-sim-favorite");
const seasonSimFavPct   = el("season-sim-favorite-pct");
const seasonSimInfo     = el("season-sim-info");
const seasonSimTable    = el("season-sim-table");
const seasonSimLeagueLabel = el("season-sim-league-label");

// CL-Ligasimulation: eigene Elemente statt Mitbenutzung der Domestic-
// Saisonsimulation, damit an deren Zustandslogik nichts angefasst wird.
const clSeasonSimEmpty    = el("cl-season-sim-empty");
const clSeasonSimControls = el("cl-season-sim-controls");
const clSeasonSimBtn      = el("cl-season-sim-btn");
const clSeasonSimRerun    = el("cl-season-sim-rerun");
const clSeasonSimResult   = el("cl-season-sim-result");
const clSeasonSimTitle    = el("cl-season-sim-title");
const clSeasonSimFavorite = el("cl-season-sim-favorite");
const clSeasonSimFavPct   = el("cl-season-sim-favorite-pct");
const clSeasonSimInfo     = el("cl-season-sim-info");
const clSeasonSimTable    = el("cl-season-sim-table");
const clSeasonSimLabel    = el("cl-season-sim-label");

const compareEyebrow    = el("compare-eyebrow");
const compareHeading    = el("compare-heading");
const compareHint       = el("compare-hint");
const phaseSection      = el("phase-section");
const phaseHint         = el("phase-hint");
const compareLeagueList = el("compare-league-list");
const compareBtn        = el("compare-btn");
const compareStatus     = el("compare-status");
const compareEmpty      = el("compare-empty");
const compareResult     = el("compare-result");

// Transfervergleich ist seit Phase 2 ein eigener Hauptbereich und rendert
// deshalb in eigene Container statt in die des Ligenvergleichs.
const transferEmpty     = el("transfer-empty");
const transferResult    = el("transfer-result");

const state = {
    seasons: [],
    season: null,          // null bedeutet laufende Saison
    seasonLabel: "",
    selectedSeason: null,  // immer die im Season-Picker sichtbare Saison, nie null - nur fuer CL-Requests genutzt

    competitions: [],
    competitionCode: null,
    competitionType: null,
    competitionName: null,

    matchday: null,
    matches: [],
    selectedMatch: null,
    selectedMatchId: null,

    clRound: null,       // deprecated - kept for backward compat only
    clLegMode: null,     // deprecated - kept for backward compat only
    clPhase: "league",   // "league" | "knockout"
    clKoStage: null,     // z.B. "LAST_16", null wenn noch keine gewählt
    clSeasonSim: null,   // letztes Ligasimulations-Ergebnis, eigener State

    activeTab: "table",
    tableType: "TOTAL",

    compareMode: "domestic",
    comparePhase: "all",
    compareSelection: [],

    // Untermodus innerhalb des Bereichs "compare": league | transfer
    compareSection: "league",

    // Genau einer von: simulation | compare | live | players
    activeArea: "simulation",
};

/* Live-Bereich. Bewusst ein eigenes Objekt statt weiterer Felder in
   state: der Live-Bereich hat seinen eigenen Lebenszyklus (Tagwahl,
   Ladezustand, Auto-Refresh) und beruehrt nichts aus der Simulation. */
const liveState = {
    selectedDate: null,   // "YYYY-MM-DD", absolutes Datum, nicht relativ
    loading: false,
    ready: false,        // wurde der Bereich schon einmal geladen?
    requestToken: 0,     // verwirft Antworten zu bereits ueberholten Anfragen
    lastData: null,       // letzte erfolgreiche Antwort, fuer die Wiederaufnahme
    refreshTimer: null,   // genau ein Auto-Refresh-Timer, nie mehrere
    stripSettleTimer: null,
    // Reihenfolge der Gruppen beim ersten Rendern eines Tages.
    // Hintergrund-Ticks uebernehmen sie, damit die Liste waehrend des
    // Lesens nicht neu sortiert wird. {date, leagueIds}
    favoriteOrder: null,
};

const PHASE_TEXTS = {
    all:      "compare.phaseHint",
    league:   "compare.leaguePhaseHint",
    knockout: "compare.knockoutPhaseHint",
};

const COMPARE_SECTION_KEYS = {
    Offensive: "compare.section.offense",
    Defensive: "compare.section.defense",
    Ergebnisse: "compare.section.results",
    Datenbasis: "compare.section.dataBasis",
    Teilnahme: "compare.section.participation",
    Wettbewerb: "compare.section.competition",
    Leistung: "compare.section.performance",
    Tore: "compare.section.goals",
    Turnierverlauf: "compare.section.progression",
};

const CUP_STAGE_KEYS = {
    Ligaphase: "phase.league",
    Playoffs: "compare.stage.playoffs",
    Achtelfinale: "compare.stage.roundOf16",
    Viertelfinale: "compare.stage.quarterFinal",
    Halbfinale: "compare.stage.semiFinal",
    Finale: "compare.stage.final",
};

const CUP_COMPARISON_PHASE_KEYS = {
    all: "compare.phase.completeSeason",
    league: "compare.phase.leagueOnly",
    knockout: "compare.phase.knockoutOnly",
};

const COMPARE_WEIGHT_LABEL_KEYS = {
    teams_in_knockout: "compare.metric.teams_in_knockout",
    avg_depth: "compare.metric.avg_depth",
    advance_rate: "compare.metric.advance_rate",
    points_per_match: "compare.metric.points_per_match",
    win_percent: "compare.metric.win_percent",
    goal_difference_per_match: "compare.metric.goal_difference_per_match",
};

const COMPARE_WEIGHT_LEGACY_LABEL_KEYS = {
    "Davon in der K o Phase": "compare.metric.teams_in_knockout",
    "Durchschnittlich erreichte Runde": "compare.metric.avg_depth",
    Weiterkommensquote: "compare.metric.advance_rate",
    "Punkte pro Spiel": "compare.metric.points_per_match",
    Siegquote: "compare.metric.win_percent",
    "Tordifferenz pro Spiel": "compare.metric.goal_difference_per_match",
};

function compareSectionLabel(section) {
    const key = COMPARE_SECTION_KEYS[section.title];
    return key ? t(key) : section.title;
}

function compareMetricLabel(row) {
    return row.key ? t(`compare.metric.${row.key}`) : row.label;
}

function cupStageLabel(label) {
    const key = CUP_STAGE_KEYS[label];
    return key ? t(key) : label;
}

function cupComparisonPhaseLabel(phase, fallback) {
    const key = CUP_COMPARISON_PHASE_KEYS[phase];
    return key ? t(key) : cupStageLabel(fallback);
}

function compareWeightLabel(weight) {
    const key = COMPARE_WEIGHT_LABEL_KEYS[weight.key]
        || COMPARE_WEIGHT_LEGACY_LABEL_KEYS[weight.label];
    return key ? t(key) : weight.label;
}


/* ---------- 2. HILFSFUNKTIONEN ---------- */

function setStatus(text, isError = false) {
    statusBox.textContent = text;
    statusBox.classList.toggle("error", isError);
}

function show(node) { if (node) node.classList.remove("hidden"); }
function hide(node) { if (node) node.classList.add("hidden"); }

function clearActive(selector) {
    document.querySelectorAll(selector).forEach(n => n.classList.remove("active"));
}

/** Baut ein Element. Text immer ueber textContent, nie ueber innerHTML. */
function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

/* ---------- Lieblingsteam-Abgleich ----------
   FootSim nutzt zwei Datenquellen mit getrennten Team-ID-Raeumen:
   football-data.org (Tabellen, Spielplan, Wappen) und API-Football
   (Live, Teamprofil). Dieselbe Zahl bedeutet dort verschiedene
   Vereine. Verglichen wird deshalb nur innerhalb der Quelle, aus der
   die gespeicherte ID stammt - lieber keine Markierung als eine
   falsche. Ein Mapping zwischen beiden Raeumen gibt es im Projekt
   bewusst nicht.                                                   */
function isFavoriteTeamId(teamId, namespace) {
    if (!window.favoriteTeamId || teamId === null || teamId === undefined) return false;
    if ((window.favoriteTeamSource || "football-data") !== namespace) return false;
    return String(window.favoriteTeamId) === String(teamId);
}

function crest(url, className) {
    const img = make("img", className);
    img.src = url;
    img.alt = "";
    img.loading = "lazy";
    img.onerror = () => { img.style.visibility = "hidden"; };
    return img;
}

async function fetchJson(url, options) {
    if (options && ['POST', 'PUT', 'PATCH', 'DELETE'].includes((options.method || 'GET').toUpperCase())) {
        options.headers = { ...options.headers, 'X-CSRFToken': getCsrfToken() };
    }
    const response = await fetch(url, options);
    let data = null;

    try {
        data = await response.json();
    } catch (error) {
        throw new Error(t("error.responseUnreadable"));
    }

    if (!response.ok) {
        const error = new Error(visibleApiError(data, "error.requestFailed", { status: response.status }));
        // Den strukturierten Teil der Antwort mitgeben. Ohne ihn bliebe
        // nur der fertig formatierte Text, und ein Aufrufer koennte
        // einen FACHLICHEN Zustand ("diese Saison hat noch keine Daten")
        // nicht mehr von einem technischen Fehler unterscheiden.
        error.data = data;
        error.status = response.status;
        throw error;
    }

    return data;
}

/** Haengt die gewählte Saison an eine URL an. */
function withSeason(url) {
    if (state.season === null) return url;
    return url + (url.includes("?") ? "&" : "?") + `season=${state.season}`;
}

/**
 * Haengt die im Season-Picker sichtbare Saison IMMER explizit an - auch
 * wenn sie die laufende ist. Nur fuer CL-Requests gedacht: CL hat einen
 * eigenen, von den Domestic-Ligen unabhaengigen Rollover-Zeitpunkt bei
 * football-data, deshalb darf sich CL nicht auf die Auto-Erkennung des
 * Backends verlassen (state.season bleibt fuer Domestic unveraendert null).
 */
function withExplicitSeason(url) {
    if (state.selectedSeason === null || state.selectedSeason === undefined) return url;
    return url + (url.includes("?") ? "&" : "?") + `season=${state.selectedSeason}`;
}

function formatValue(value, unit) {
    if (value === null || value === undefined) return "-";
    return `${value}${unit || ""}`;
}


/* ---------- 2b. NATIVE BRUECKE (nur iOS-App) ----------------------------
 *
 * Die iOS-Huelle stellt Nachrichtenkanaele unter
 * window.webkit.messageHandlers bereit. Im normalen Browser und in der
 * Android-TWA existiert dieses Objekt schlicht nicht.
 *
 * DEFENSIV IN BEIDE RICHTUNGEN
 * Jeder Aufruf prueft die gesamte Kette einzeln - window.webkit, dann
 * messageHandlers, dann den konkreten Kanal, dann postMessage als
 * Funktion. Ein "if (window.webkit)" allein genuegt nicht: Ein Kanal,
 * den die App (noch) nicht registriert hat, fehlt einzeln, und der
 * Zugriff darauf wuerde werfen. Deshalb zusaetzlich try/catch: Eine
 * kaputte Bruecke darf niemals die Simulation verhindern - sie ist
 * Beiwerk, nicht Voraussetzung.
 *
 * KEINE SICHERHEITSENTSCHEIDUNG
 * Diese Bruecke transportiert ausschliesslich Darstellungs- und
 * Komfortsignale. Weder Authentifizierung noch Autorisierung noch
 * Datenzugriff haengen an ihr oder am Plattformparameter. Wer sie
 * faelscht, loest bestenfalls eine Vibration aus.
 *
 * PAYLOADS
 * Klein und typisiert. Jedes Feld wird vor dem Senden geprueft; nicht
 * passende Werte werden verworfen statt uebertragen. Die App darf sich
 * darauf verlassen, dass ein empfangenes Feld den erwarteten Typ hat. */

const NATIVE_KANAELE = ["haptic", "share"];

/** Ist die Seite in der iOS-Huelle? Rein informativ, nie autorisierend. */
function istNativeHuelle() {
    return document.documentElement.getAttribute("data-platform") === "ios";
}

/** Liefert den Kanal oder null. Prueft die vollstaendige Kette. */
function nativerKanal(name) {
    if (!NATIVE_KANAELE.includes(name)) return null;
    try {
        const bruecke = window.webkit && window.webkit.messageHandlers;
        if (!bruecke) return null;
        const kanal = bruecke[name];
        if (!kanal || typeof kanal.postMessage !== "function") return null;
        return kanal;
    } catch (error) {
        return null;
    }
}

/**
 * Sendet eine Nachricht an die Huelle. Gibt zurueck, ob es geklappt hat -
 * der Aufrufer darf das ignorieren, muss es aber nie abfangen.
 */
function sendeNativ(name, nutzlast) {
    const kanal = nativerKanal(name);
    if (!kanal) return false;
    try {
        kanal.postMessage(nutzlast);
        return true;
    } catch (error) {
        return false;
    }
}

/**
 * Haptisches Signal.
 *
 * staerke: "light" | "medium" | "heavy" - alles andere wird zu "medium".
 * Ein fester Wertebereich statt freier Zeichenkette, damit die App keine
 * Eingabe validieren muss, die sie nicht kennt.
 */
function nativeHaptik(staerke) {
    const erlaubt = ["light", "medium", "heavy"];
    sendeNativ("haptic", {
        style: erlaubt.includes(staerke) ? staerke : "medium",
    });
}

/* Laengengrenzen der Teilen-Nutzlast.
 *
 * Ein Share Sheet zeigt ohnehin nur wenige Zeilen an; alles darueber
 * hinaus waere unsichtbarer Ballast. Die Grenzen sind deshalb kein
 * Selbstzweck, sondern verhindern, dass ein Fehler in einer aufrufenden
 * Stelle megabytegrosse Zeichenketten ueber die Bruecke schiebt. */
const TEILEN_MAX_TITEL = 120;
const TEILEN_MAX_TEXT = 600;
const TEILEN_MAX_URL = 2048;

/** Trimmt, prueft den Typ und kuerzt auf die Hoechstlaenge. */
function sauberesTextfeld(wert, maximum) {
    if (typeof wert !== "string") return null;
    const bereinigt = wert.trim();
    if (!bereinigt) return null;
    return bereinigt.slice(0, maximum);
}

/**
 * Teilen ueber das native Share Sheet.
 *
 * VORBEREITET, NOCH NICHT SICHTBAR AUSGELOEST. Es gibt bewusst keinen
 * Teilen-Knopf in der Oberflaeche - die Platzierung wird getrennt
 * freigegeben. Vorgesehene Stelle: der Ergebnisbereich #result, direkt
 * neben der Ueberschrift der Simulationsauswertung, sichtbar nur wenn
 * istNativeHuelle() zutrifft (siehe docs/ios-app.md).
 *
 * URL-BEHANDLUNG
 * Erlaubt ist ausschliesslich eine http(s)-Adresse der EIGENEN Herkunft.
 * Damit fallen javascript:, data:, blob:, file: und jede fremde Domain
 * heraus - nicht weil hier ein Angriff erwartet wird, sondern weil eine
 * Bruecke, die alles durchreicht, keine Grenze ist. Die Huelle prueft
 * zusaetzlich ein zweites Mal gegen ihre eigene Allowlist.
 *
 * Es werden ausschliesslich diese drei Felder uebertragen. Cookies,
 * Sitzungsmerkmale, Tokens oder personenbezogene Daten gehen NIE ueber
 * die Bruecke.
 */
function nativeTeilen({ titel, text, url } = {}) {
    const nutzlast = {};

    const gepruefterTitel = sauberesTextfeld(titel, TEILEN_MAX_TITEL);
    if (gepruefterTitel) nutzlast.title = gepruefterTitel;

    const gepruefterText = sauberesTextfeld(text, TEILEN_MAX_TEXT);
    if (gepruefterText) nutzlast.text = gepruefterText;

    const rohe = sauberesTextfeld(url, TEILEN_MAX_URL);
    if (rohe) {
        try {
            const geprueft = new URL(rohe, window.location.origin);
            const schemaOk = geprueft.protocol === "https:" || geprueft.protocol === "http:";
            if (schemaOk && geprueft.origin === window.location.origin) {
                nutzlast.url = geprueft.href;
            }
        } catch (error) {
            /* Unbrauchbare URL wird weggelassen, nicht gesendet. */
        }
    }

    if (!nutzlast.title && !nutzlast.text && !nutzlast.url) return false;
    return sendeNativ("share", nutzlast);
}


/* ---------- 3. SAISONWAHL ---------- */

async function loadSeasons() {
    try {
        const seasons = await fetchJson("/api/seasons");
        state.seasons = seasons;

        const current = seasons.find(s => s.is_current) || seasons[0];

        if (current) {
            state.season = null;                 // laufende Saison als Standard
            state.seasonLabel = current.label;
            state.selectedSeason = current.season;
        }

        renderSeasons();
    } catch (error) {
        seasonList.appendChild(make("div", "loading-hint", t("status.seasonsUnavailable")));
    }
}


function renderSeasons() {
    seasonDropdownList.innerHTML = "";

    // Laufende Saison als Standard-Label setzen
    const current = state.seasons.find(s => s.is_current) || state.seasons[0];
    if (current) seasonDropdownLabel.textContent = current.label;

    state.seasons.forEach(season => {
        const item = make("button", "season-dropdown-item");

        const top = make("div", "season-item-top");
        top.appendChild(make("span", "season-item-label", season.label));
        if (season.is_current) top.appendChild(make("span", "season-item-badge", t("season.current")));
        if (season.is_complete) top.appendChild(make("span", "season-item-badge season-item-done", t("season.completed")));

        item.appendChild(top);
        item.appendChild(make("span", "season-item-sub", season.description));

        if (season.is_current) item.classList.add("active");

        item.addEventListener("click", () => {
            clearActive(".season-dropdown-item");
            item.classList.add("active");
            seasonDropdownLabel.textContent = season.label;
            hide(seasonDropdownList);

            selectSeason(season, item);
        });

        seasonDropdownList.appendChild(item);
    });

    // Dropdown oeffnen/schliessen
    seasonDropdownBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        seasonDropdownList.classList.toggle("hidden");
    });

    // Klick ausserhalb schliesst das Dropdown
    document.addEventListener("click", () => {
        hide(seasonDropdownList);
    });
}


function selectSeason(season, _btn) {

    // Bei der laufenden Saison keinen Parameter senden, damit die
    // Autoerkennung im Backend greift.
    state.season = season.is_current ? null : season.season;
    state.seasonLabel = season.label;
    // selectedSeason haelt immer die sichtbare Saison, auch bei "aktuell" -
    // CL-Requests verwenden ausschliesslich diesen Wert (withExplicitSeason).
    state.selectedSeason = season.season;

    resetSimulationView();
    resetCompareView();

    setStatus(t("status.seasonSelected", { season: season.label }));

    // Wettbewerbe neu laden, weil sich die Untertitel je Saison aendern
    loadCompetitions();
}


function resetSimulationView() {
    state.competitionCode = null;
    state.competitionType = null;
    state.matchday = null;
    state.matches = [];
    state.selectedMatch = null;
    state.selectedMatchId = null;
    state.clRound = null;
    state.clLegMode = null;
    state.clPhase = "league";
    state.clKoStage = null;
    state.clSeasonSim = null;

    matchList.innerHTML = "";
    matchdayList.innerHTML = "";
    clMatchdayList.innerHTML = "";
    clKoStageList.innerHTML = "";
    clSeasonSimTable.innerHTML = "";

    hide(matchdaySection);
    hide(clPhaseSection);
    hide(clMatchdaySection);
    hide(clKoStageSection);
    hide(clKoEmpty);
    hide(tabBar);
    hide(tabTable);
    hide(tabScorers);
    hide(tabFixtures);
    hide(el("tab-cl-season"));
    hide(clSeasonSimResult);
    hide(tabSimulation);
    hide(simControls);
    hide(resultBox);

    show(leftEmptyState);
    show(emptyState);
    show(simEmpty);
    show(fixturesEmpty);
}


function resetCompareView() {
    state.compareSelection = [];
    compareBtn.disabled = true;
    compareStatus.textContent = t("compare.minimumTwo");
    compareResult.innerHTML = "";
    hide(compareResult);
    show(compareEmpty);

    compareLeagueList.querySelectorAll(".compare-league-option").forEach(node => {
        node.classList.remove("selected");
        const check = node.querySelector(".compare-check");
        if (check) check.textContent = "";
    });
}


/* ---------- 4. HAUPTNAVIGATION: VIER BEREICHE ----------

   Simulation | Vergleiche | Live | Spieler

   Zu jedem Bereich gehoert ein <main class="app-area" data-area="...">
   und je ein Knopf in der Desktop- und in der Bottom-Navigation.
   Spieler bleibt bewusst der rechte Bereich.

   Ligavergleich und Transfervergleich teilen sich seit Block 1 den
   Bereich "compare" (Vergleiche). Welcher der beiden gerade sichtbar
   ist, steuert switchCompareSection() ueber state.compareSection und
   .compare-section-card -- dasselbe grosse Card-Radiogroup-Muster wie
   pcSetMode() fuer Radar/Plots im Spielerbereich, nur eine Ebene ueber
   dem Hauptbereich-Umschalter.

   setActiveArea() ist die einzige Stelle, die den sichtbaren Hauptbereich
   umschaltet. Sie loest bewusst keine Datenabfragen aus; Ausnahmen sind
   die einmalige Initialisierung der Transfer-Dropdowns (tcControlsReady)
   und der Live-Bereich, der beim ersten Oeffnen den aktuellen Tag laedt.
------------------------------------------------------------------- */

const AREAS = ["simulation", "compare", "live", "players"];

// Die Saisonwahl gilt nur fuer Simulation und den Ligavergleich-Untermodus.
// Der Transfervergleich hat mit tc-season eine eigene, unabhaengige Saisonwahl.
function updateSeasonPickerVisibility() {
    const seasonPicker = document.querySelector(".season-picker");
    if (!seasonPicker) return;
    const relevant = state.activeArea === "simulation" ||
        (state.activeArea === "compare" && state.compareSection === "league");
    seasonPicker.classList.toggle("hidden", !relevant);
}

function setActiveArea(area) {
    if (!AREAS.includes(area)) return;

    state.activeArea = area;

    // Bereiche umschalten: genau einer sichtbar, alle anderen versteckt.
    document.querySelectorAll(".app-area").forEach(node => {
        const isActive = node.dataset.area === area;
        node.classList.toggle("hidden", !isActive);
        // Versteckte Bereiche sollen nicht per Tastatur erreichbar bleiben.
        if (isActive) {
            node.removeAttribute("inert");
            node.removeAttribute("aria-hidden");
        } else {
            node.setAttribute("inert", "");
            node.setAttribute("aria-hidden", "true");
        }
    });

    // Beide Navigationen synchron halten.
    document.querySelectorAll(".area-btn, .bottom-nav-btn").forEach(button => {
        const isActive = button.dataset.area === area;
        button.classList.toggle("active", isActive);
        if (isActive) {
            button.setAttribute("aria-current", "page");
        } else {
            button.removeAttribute("aria-current");
        }
    });

    updateSeasonPickerVisibility();

    // Transfer-Untermodus: Dropdowns einmalig aufbauen, danach nie wieder.
    if (area === "compare" && state.compareSection === "transfer") tcInitControls();
    if (area === "players") pcInitControls();

    // Auto-Refresh darf ausschliesslich laufen, waehrend der Nutzer
    // tatsaechlich im Live-Bereich ist. Jeder andere Bereich stoppt
    // beide Timer - den der Tagesliste und den des Match Centers.
    if (area === "live") {
        liveInit();
    } else {
        liveStopAutoRefresh();
        mcStopAutoRefresh();
    }

    // Nach oben, damit der neue Bereich von seinem Anfang an gelesen wird.
    window.scrollTo({ top: 0, behavior: "auto" });
}

/* ---------- 4b. BEREICHE IN DER BROWSER-HISTORY ----------

   Warum es das braucht
   --------------------
   FootSim wechselt die vier Hauptbereiche ohne Seitenwechsel. Bis hierher
   entstand dabei kein History-Eintrag - im Browser unauffaellig, in der
   spaeteren Android-App aber ein Problem: Die Zurueck-Taste haette aus
   JEDEM Bereich sofort die Anwendung geschlossen, statt zum vorigen
   Bereich zu fuehren.

   Aufgabenteilung
   ---------------
     setActiveArea()   schaltet die Ansicht um. Unveraendert, kennt keine
                       History - sie ist auch der Weg, den popstate geht.
     navigateToArea()  ist der Weg des Nutzers: erst Eintrag, dann Ansicht.

   Bewusst zwei Funktionen statt einer erweiterten: popstate MUSS
   umschalten koennen, ohne einen neuen Eintrag zu erzeugen. Ein Schalter
   innerhalb von setActiveArea() haette dieselbe Wirkung, aber jeder
   bestehende Aufrufer haette mitgeprueft werden muessen.

   Keine Schleifen: navigateToArea() kehrt bei bereits aktivem Bereich
   sofort zurueck, popstate schaltet nur bei tatsaechlicher Abweichung.
   Beides zusammen schliesst doppelte Eintraege und Ping-Pong aus.        */

const AREA_QUERY_KEY = "area";

//: Einmalige, sicherheitsrelevante Parameter. Sie gehoeren in genau einen
//: Seitenaufruf und nicht in jeden weiteren History-Eintrag - ein
//: Rueckstellungstoken soll nicht durch die gesamte Sitzung wandern.
const TRANSIENT_QUERY_KEYS = ["reset_token", "verify_error", "verified"];

function areaFromUrl(fallback) {
    try {
        const angefragt = new URL(window.location.href)
            .searchParams.get(AREA_QUERY_KEY);
        if (AREAS.includes(angefragt)) return angefragt;
    } catch (e) {
        /* Eine unlesbare URL ist kein Grund, die Navigation aufzugeben. */
    }
    return fallback;
}

function areaHistoryUrl(area) {
    // Bestehende Parameter bleiben erhalten - lang und platform steuern
    // Sprache und Android-Modus und duerfen beim Bereichswechsel nicht
    // verlorengehen. Nur die einmaligen Auth-Parameter fallen weg.
    const url = new URL(window.location.href);
    TRANSIENT_QUERY_KEYS.forEach(schluessel => url.searchParams.delete(schluessel));
    url.searchParams.set(AREA_QUERY_KEY, area);
    return url.pathname + url.search + url.hash;
}

function navigateToArea(area) {
    if (!AREAS.includes(area)) return;
    // Derselbe Bereich erzeugt keinen zweiten Eintrag.
    if (state.activeArea === area) return;

    window.history.pushState({ footsimArea: area }, "", areaHistoryUrl(area));
    setActiveArea(area);
}

window.addEventListener("popstate", (event) => {
    // Der eigene Zustand ist die verlaessliche Quelle. Fehlt er - etwa
    // weil die Auth-Behandlung die URL mit replaceState({}) bereinigt
    // hat -, entscheidet der Parameter, sonst der erste Bereich.
    const ausZustand = event.state && event.state.footsimArea;
    const ziel = AREAS.includes(ausZustand)
        ? ausZustand
        : areaFromUrl(AREAS[0]);

    if (ziel !== state.activeArea) setActiveArea(ziel);
});

document.querySelectorAll(".area-btn, .bottom-nav-btn").forEach(button => {
    button.addEventListener("click", () => navigateToArea(button.dataset.area));
});


/* ---------- 4a. VERGLEICHE: UNTERBEREICH LIGA / TRANSFER ----------

   Innerhalb des Hauptbereichs "compare" waehlt dieser Umschalter zwischen
   den zwei vollstaendig erhaltenen Funktionen Ligavergleich und Transfer-
   vergleich. Bewusst dasselbe Muster wie pcSetMode() (Radar/Plots im
   Spielerbereich): grosse Cards in einer role="radiogroup", aria-checked
   statt aria-current, kein inert/aria-hidden auf den Cards selbst.
------------------------------------------------------------------- */

const COMPARE_SECTIONS = ["league", "transfer"];

function switchCompareSection(section) {
    if (!COMPARE_SECTIONS.includes(section)) return;

    state.compareSection = section;

    document.querySelectorAll(".compare-area-section").forEach(node => {
        node.classList.toggle("hidden", node.dataset.csection !== section);
    });

    document.querySelectorAll(".compare-section-card").forEach(card => {
        const isActive = card.dataset.csection === section;
        card.classList.toggle("active", isActive);
        card.setAttribute("aria-checked", isActive ? "true" : "false");
    });

    updateSeasonPickerVisibility();

    // Transferbereich: Dropdowns einmalig aufbauen, danach nie wieder.
    if (section === "transfer") tcInitControls();
}

const compareSectionSelect = el("compare-section-select");

if (compareSectionSelect) {
    compareSectionSelect.addEventListener("click", (event) => {
        const card = event.target.closest(".compare-section-card");
        if (!card) return;
        switchCompareSection(card.dataset.csection);
    });
}


/* ---------- 4b. EINSTELLUNGSMENÜ (Drawer) ----------

   Der Drawer sperrt den Hintergrund waehrend er offen ist und stellt den
   vorherigen Scrollzustand beim Schliessen vollstaendig wieder her.
   Kein dauerhaftes overflow:hidden, kein preventDefault auf Touch-Events.
------------------------------------------------------------------- */

const settingsBtn      = el("settings-btn");
const settingsDrawer   = el("settings-drawer");
const settingsBackdrop = el("settings-backdrop");
const settingsClose    = el("settings-close");
const languageSwitch   = el("language-switch");

let drawerOpen = false;
let drawerScrollY = 0;
let drawerLastFocus = null;

function openDrawer() {
    if (drawerOpen || !settingsDrawer) return;
    drawerOpen = true;
    drawerLastFocus = document.activeElement;

    drawerScrollY = window.scrollY;
    document.body.classList.add("drawer-open");
    document.body.style.top = `-${drawerScrollY}px`;

    settingsDrawer.hidden = false;
    settingsBackdrop.hidden = false;
    show(settingsDrawer);
    show(settingsBackdrop);

    settingsBtn.setAttribute("aria-expanded", "true");
    settingsClose.focus();
}

function closeDrawer() {
    if (!drawerOpen || !settingsDrawer) return;
    drawerOpen = false;

    hide(settingsDrawer);
    hide(settingsBackdrop);
    settingsDrawer.hidden = true;
    settingsBackdrop.hidden = true;

    // Scrollzustand exakt wiederherstellen.
    document.body.classList.remove("drawer-open");
    document.body.style.top = "";
    window.scrollTo(0, drawerScrollY);

    settingsBtn.setAttribute("aria-expanded", "false");
    if (drawerLastFocus && drawerLastFocus.focus) drawerLastFocus.focus();
}

if (settingsBtn)      settingsBtn.addEventListener("click", openDrawer);
if (settingsClose)    settingsClose.addEventListener("click", closeDrawer);
if (settingsBackdrop) settingsBackdrop.addEventListener("click", closeDrawer);
if (languageSwitch) {
    languageSwitch.addEventListener("click", (event) => {
        const button = event.target.closest(".language-btn");
        if (button) selectLocale(button.dataset.language);
    });
}

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && drawerOpen) closeDrawer();
});

// Fokus im offenen Drawer halten.
document.addEventListener("focusin", (event) => {
    if (!drawerOpen) return;
    if (settingsDrawer.contains(event.target)) return;
    settingsClose.focus();
});


/* ---------- 5. WETTBEWERBE ---------- */

async function loadCompetitions() {
    try {
        const competitions = await fetchJson(withSeason("/api/competitions"));
        state.competitions = competitions;

        renderCompetitions(competitions);
        renderCompareLeagues(competitions.filter(c => c.type === "league"));

        setStatus(t("status.ready"));
    } catch (error) {
        competitionList.innerHTML = "";
        competitionList.appendChild(
            make("div", "loading-hint", t("status.competitionsLoadError", { error: error.message }))
        );
        setStatus(error.message, true);
    }
}


function renderCompetitions(competitions) {
    competitionList.innerHTML = "";

    competitions.forEach(competition => {
        const card = make("button", "competition-card");
        card.dataset.competition = competition.code;

        if (!competition.available) {
            card.classList.add("disabled");
            card.disabled = true;
        }

        const left = make("div", "competition-card-left");
        left.appendChild(crest(competition.emblem, "competition-icon"));

        const textWrap = make("div");
        textWrap.appendChild(make("div", "competition-name", competition.name));
        textWrap.appendChild(make("div", "competition-sub", competition.subtitle));

        left.appendChild(textWrap);
        card.appendChild(left);

        card.addEventListener("click", () => selectCompetition(competition, card));

        competitionList.appendChild(card);
    });
}


async function selectCompetition(competition, card) {
    if (!competition.available) return;

    clearActive(".competition-card");
    card.classList.add("active");

    state.competitionCode = competition.code;
    state.competitionType = competition.type;
    state.competitionName = competition.name;
    state.matchday = null;
    state.matches = [];
    state.selectedMatch = null;
    state.selectedMatchId = null;
    state.clPhase = "league";
    state.clKoStage = null;

    matchList.innerHTML = "";
    matchdayList.innerHTML = "";
    clMatchdayList.innerHTML = "";
    clKoStageList.innerHTML = "";

    hide(leftEmptyState);
    hide(emptyState);
    hide(matchdaySection);
    hide(clPhaseSection);
    hide(clMatchdaySection);
    hide(clKoStageSection);
    hide(clKoEmpty);
    hide(simControls);
    hide(resultBox);
    hide(seasonSimResult);
    show(simEmpty);
    show(fixturesEmpty);
    hide(knockoutSection);

    setStatus(t("status.competitionSelected", { name: competition.name }));

    if (competition.type === "league") {
        showTabsFor("league");
        await loadMatchdays(competition.code);

        switchTab("table");
        loadStandings(competition.code);
        loadScorers(competition.code);
        initSeasonSim();

    } else if (competition.type === "cl") {
        // Champions League: Phasenauswahl + Ligaphase als Default
        showTabsFor("cl_league");
        show(clPhaseSection);
        renderClPhaseButtons();

        await loadClMatchdays();

        switchTab("table");
        loadStandings("cl");
        loadScorers("cl");
        initClSeasonSim();

    } else {
        // Sonstige Pokale (Europa League etc.)
        showTabsFor("cup");
        switchTab("fixtures");
    }

    // Auf schmalen Bildschirmen (Stacked/Mobile Layout) direkt zum naechsten Schritt springen
    if (window.innerWidth <= 1000) {
        const target = competition.type === "league" ? matchdaySection : 
                       (competition.type === "cl" ? clPhaseSection : null);
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }
}


/** Blendet die Reiter ein, die zum Wettbewerbstyp passen. */
function showTabsFor(type) {
    show(tabBar);

    const tableBtn    = document.querySelector('.tab-btn[data-tab="table"]');
    const scorersBtn  = document.querySelector('.tab-btn[data-tab="scorers"]');
    const seasonBtn   = document.querySelector('.tab-btn[data-tab="season"]');
    const clSeasonBtn = document.querySelector('.tab-btn[data-tab="cl-season"]');

    if (type === "league") {
        show(tableBtn);
        show(scorersBtn);
        show(seasonBtn);
        hide(clSeasonBtn);
        setTableTypeSwitchVisible(true);
    } else if (type === "cl_league") {
        // CL Ligaphase: Tabelle + Torjaeger + eigene Ligasimulation,
        // aber keine Domestic-Saisonsimulation
        show(tableBtn);
        show(scorersBtn);
        hide(seasonBtn);
        show(clSeasonBtn);
        setTableTypeSwitchVisible(false);
    } else if (type === "cl_knockout") {
        // CL K.o.: keine Tabelle, Torjaeger bleiben (wettbewerbsweit).
        // Die Ligasimulation gehoert ausschliesslich zur Ligaphase.
        hide(tableBtn);
        show(scorersBtn);
        hide(seasonBtn);
        hide(clSeasonBtn);
        setTableTypeSwitchVisible(false);
    } else {
        // cup: nur Spiele + Spiel-Simulation
        hide(tableBtn);
        hide(scorersBtn);
        hide(seasonBtn);
        hide(clSeasonBtn);
    }
}


/* ---------- 6. SPIELTAGE ---------- */

async function loadMatchdays(competitionCode) {
    matchdayList.innerHTML = "";
    show(matchdaySection);

    const isPastSeason = state.season !== null;

    matchdayHint.textContent = isPastSeason
        ? t("matchday.completedSeason", { season: state.seasonLabel })
        : t("matchday.hint");

    try {
        const matchdays = await fetchJson(
            withSeason(`/api/matchdays?competition=${competitionCode}`)
        );

        matchdays.forEach(day => {
            const cell = make("button", "matchday-cell", String(day.matchday));

            if (day.is_current) cell.classList.add("is-current");

            if (!day.available) {
                cell.classList.add("locked");
                cell.disabled = true;
                cell.title = activeLocale === "de" && day.message
                    ? day.message
                    : t("matchday.locked");
            } else {
                cell.title = day.label;
                cell.addEventListener("click", () => selectMatchday(competitionCode, day.matchday, cell));
            }

            matchdayList.appendChild(cell);
        });
    } catch (error) {
        matchdayList.appendChild(make("div", "loading-hint", error.message));
    }
}


async function selectMatchday(competitionCode, matchday, cell) {
    clearActive(".matchday-cell");
    cell.classList.add("active");

    state.matchday = matchday;
    state.selectedMatch = null;
    state.selectedMatchId = null;

    hide(simControls);
    setStatus(t("matchday.loading", { matchday }));

    // Kern der Verbesserung: der Reiter Spiele oeffnet sich von selbst.
    // Kein Suchen und kein Scrollen mehr.
    switchTab("fixtures");

    await loadMatches(competitionCode, matchday);
}


/* ---------- 7. CHAMPIONS LEAGUE PHASENNAVIGATION (Block B2) ---------- */

function renderClPhaseButtons() {
    document.querySelectorAll(".cl-phase-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.clPhase === state.clPhase);

        // Event-Listener nur einmal registrieren (idempotent via cloneNode-Trick
        // vermeiden wir - stattdessen data-attribute als Guard)
        if (!btn.dataset.listenerBound) {
            btn.dataset.listenerBound = "true";
            btn.addEventListener("click", () => selectClPhase(btn.dataset.clPhase));
        }
    });
}


async function selectClPhase(phase) {
    state.clPhase = phase;
    state.clKoStage = null;
    state.selectedMatch = null;
    state.selectedMatchId = null;

    matchList.innerHTML = "";
    hide(simControls);
    show(fixturesEmpty);
    show(simEmpty);
    hide(resultBox);

    // Phase-Buttons aktualisieren
    document.querySelectorAll(".cl-phase-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.clPhase === phase);
    });

    if (phase === "league") {
        showTabsFor("cl_league");
        show(clMatchdaySection);
        hide(clKoStageSection);
        hide(clKoEmpty);

        await loadClMatchdays();
        switchTab("table");
        loadStandings("cl");
        initClSeasonSim();
        // Torjäger bleiben geladen (wettbewerbsweit, nicht neu laden nötig)

    } else {
        showTabsFor("cl_knockout");
        hide(clMatchdaySection);

        switchTab("fixtures");
        await loadClKoStages();
    }

    setStatus(t("championsLeague.phaseSelected", {
        phase: phase === "league" ? t("phase.league") : t("phase.knockout"),
    }));
}


async function loadClMatchdays() {
    clMatchdayList.innerHTML = "";
    show(clMatchdaySection);

    const isPastSeason = state.season !== null;

    try {
        const matchdays = await fetchJson(
            withExplicitSeason("/api/matchdays?competition=cl")
        );

        // Kein einziger Spieltag verfuegbar -> es existiert noch kein
        // echter Ligaphasen-Spielplan fuer diese Saison (z. B. vor der
        // Auslosung), nicht bloss eine normale Teil-Sperre.
        const noFixturesYet = matchdays.length > 0 && matchdays.every(day => !day.available);

        clMatchdayHint.textContent = noFixturesYet
            ? t("championsLeague.noLeagueFixturesForSeason", { season: state.seasonLabel })
            : isPastSeason
                ? t("matchday.completedSeason", { season: state.seasonLabel })
                : t("championsLeague.matchdayHint");

        matchdays.forEach(day => {
            const cell = make("button", "matchday-cell", String(day.matchday));

            if (day.is_current) cell.classList.add("is-current");

            if (!day.available) {
                cell.classList.add("locked");
                cell.disabled = true;
                cell.title = activeLocale === "de" && day.message
                    ? day.message
                    : t("matchday.locked");
            } else {
                cell.title = day.label;
                cell.addEventListener("click", () => selectClMatchday(day.matchday, cell));
            }

            clMatchdayList.appendChild(cell);
        });
    } catch (error) {
        clMatchdayList.appendChild(make("div", "loading-hint", error.message));
    }
}


async function selectClMatchday(matchday, cell) {
    clearActive("#cl-matchday-list .matchday-cell");
    cell.classList.add("active");

    state.matchday = matchday;
    state.selectedMatch = null;
    state.selectedMatchId = null;

    hide(simControls);
    setStatus(t("championsLeague.matchdayLoading", { matchday }));

    switchTab("fixtures");
    await loadMatches("cl", matchday);
}


async function loadClKoStages() {
    clKoStageList.innerHTML = "";
    hide(clKoEmpty);
    show(clKoStageSection);

    try {
        const data = await fetchJson(
            withExplicitSeason("/api/cl-stages")
        );

        if (!data.stages || data.stages.length === 0) {
            clKoEmpty.textContent = t("championsLeague.knockoutUnavailable", {
                season: state.seasonLabel,
            });
            show(clKoEmpty);
            return;
        }

        data.stages.forEach(stage => {
            const button = make("button", "round-option");
            button.appendChild(make("div", "option-head", stage.label));

            button.addEventListener("click", async () => {
                clearActive("#cl-ko-stage-list .round-option");
                button.classList.add("active");

                state.clKoStage = stage.stage;
                state.selectedMatch = null;
                state.selectedMatchId = null;

                hide(simControls);
                setStatus(t("round.loading", { round: stage.label }));

                switchTab("fixtures");
                await loadClKnockoutMatches(stage.stage, stage.label);
            });

            clKoStageList.appendChild(button);
        });

    } catch (error) {
        clKoStageList.appendChild(make("div", "loading-hint", error.message));
    }
}


async function loadClKnockoutMatches(stage, stageLabel) {
    matchList.innerHTML = "";
    hide(fixturesEmpty);

    fixturesEyebrow.textContent = stageLabel || stage;
    fixturesTitle.textContent = "Champions League";

    try {
        const data = await fetchJson(
            withExplicitSeason(`/api/cl-knockout?stage=${stage}`)
        );

        if (!data.ties || data.ties.length === 0) {
            show(fixturesEmpty);
            fixturesEmpty.querySelector("h2").textContent = t("fixtures.roundEmptyHeading");
            fixturesEmpty.querySelector("p").textContent = t("fixtures.roundEmptyHint");
            return;
        }

        state.matches = [];

        data.ties.forEach(tie => {
            tie.legs.forEach(leg => {
                const match = {
                    id: `cl_ko_${leg.home_id}_vs_${leg.away_id}`,
                    home_team: leg.home_team,
                    away_team: leg.away_team,
                    home_id: leg.home_id,
                    away_id: leg.away_id,
                    home_crest: leg.home_crest,
                    away_crest: leg.away_crest,
                    home_score: leg.home_score,
                    away_score: leg.away_score,
                    status: leg.status,
                    utc_date: leg.utc_date,
                    competition: "cl",
                };

                state.matches.push(match);
                matchList.appendChild(buildMatchCard(match));
            });
        });

        setStatus(t("fixtures.tiesLoaded", { count: data.ties.length }));

    } catch (error) {
        matchList.innerHTML = "";
        matchList.appendChild(make("div", "loading-hint", t("fixtures.knockoutUnavailable", {
            error: error.message,
        })));
    }
}


/* ---------- 8. TABS ---------- */

document.querySelectorAll(".tab-btn").forEach(button => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
});


function switchTab(tabName) {
    state.activeTab = tabName;

    clearActive(".tab-btn");
    const button = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (button) button.classList.add("active");

    hide(tabTable);
    hide(tabScorers);
    hide(tabFixtures);
    hide(el("tab-season"));
    hide(el("tab-cl-season"));
    hide(tabSimulation);
    hide(emptyState);

    if (tabName === "table")      show(tabTable);
    if (tabName === "scorers")    show(tabScorers);
    if (tabName === "fixtures")   show(tabFixtures);
    if (tabName === "season")     show(el("tab-season"));
    if (tabName === "cl-season")  show(el("tab-cl-season"));
    if (tabName === "simulation") show(tabSimulation);
}


/* ---------- 9. SPIELE UND SIMULATIONSSTEUERUNG ---------- */

async function loadMatches(competitionCode, matchday = null, round = null) {
    matchList.innerHTML = "";
    hide(fixturesEmpty);

    let url = `/api/matches?competition=${competitionCode}`;
    if (matchday !== null) url += `&matchday=${matchday}`;
    if (round !== null)    url += `&round=${round}`;

    fixturesEyebrow.textContent = matchday !== null
        ? t("matchday.label", { matchday })
        : t("round.selected");

    fixturesTitle.textContent = state.competitionName || t("fixtures.title");

    try {
        const seasonedUrl = competitionCode === "cl" ? withExplicitSeason(url) : withSeason(url);
        const matches = await fetchJson(seasonedUrl);
        state.matches = matches;

        if (!matches.length) {
            show(fixturesEmpty);
            if (competitionCode === "cl") {
                fixturesEmpty.querySelector("h2").textContent = t("fixtures.clEmptyHeading");
                fixturesEmpty.querySelector("p").textContent =
                    t("championsLeague.noLeagueFixturesForSeason", { season: state.seasonLabel });
            } else {
                fixturesEmpty.querySelector("h2").textContent = t("fixtures.noMatchesHeading");
                fixturesEmpty.querySelector("p").textContent = t("fixtures.noMatchesHint");
            }
            setStatus(t("fixtures.noMatchesFound"));
            return;
        }

        // Sort matches to prioritize favorite team.
        // /api/matches liefert football-data.org-IDs.
        if (window.favoriteTeamId) {
            matches.sort((a, b) => {
                const aIsFav = isFavoriteTeamId(a.home_id, "football-data")
                    || isFavoriteTeamId(a.away_id, "football-data");
                const bIsFav = isFavoriteTeamId(b.home_id, "football-data")
                    || isFavoriteTeamId(b.away_id, "football-data");
                return (bIsFav ? 1 : 0) - (aIsFav ? 1 : 0);
            });
        }
        matches.forEach(match => matchList.appendChild(buildMatchCard(match)));
        setStatus(t("fixtures.matchesLoaded", { count: matches.length }));

    } catch (error) {
        show(fixturesEmpty);
        fixturesEmpty.querySelector("h2").textContent = t("error.genericHeading");
        fixturesEmpty.querySelector("p").textContent = error.message;
        setStatus(error.message, true);
    }
}


function buildMatchCard(match) {
    const button = make("button", "match-option");
    const wrap = make("div", "match-card-clean");

    wrap.appendChild(buildTeamRow(match.home_team, match.home_crest, match.home_id));
    wrap.appendChild(make("div", "match-vs-clean", t("fixtures.vs")));
    wrap.appendChild(buildTeamRow(match.away_team, match.away_crest, match.away_id));

    if (match.status === "FINISHED" && match.home_score !== null && match.home_score !== undefined) {
        wrap.appendChild(make("div", "match-final-score", t("fixtures.finalScore", {
            home: match.home_score,
            away: match.away_score,
        })));
    }

    button.appendChild(wrap);

    button.addEventListener("click", () => selectMatch(match, button));

    return button;
}


function selectMatch(match, button) {
    clearActive(".match-option");
    button.classList.add("active");

    state.selectedMatch = match;
    state.selectedMatchId = match.id;

    selectedMatchLabel.textContent = t("fixtures.matchup", {
        home: match.home_team,
        away: match.away_team,
    });
    show(simControls);

    setStatus(t("fixtures.matchup", {
        home: match.home_team,
        away: match.away_team,
    }));

    // Sanft zur Steuerung fuehren, ohne den Rest der Seite zu verlieren
    simControls.scrollIntoView({ behavior: "smooth", block: "nearest" });
}


function buildTeamRow(teamName, crestUrl, teamId) {
    const row = make("div", "match-team-side");

    const url = crestUrl || (teamId ? `https://crests.football-data.org/${teamId}.png` : null);

    if (url) row.appendChild(crest(url, "team-logo-clean"));

    const nameDiv = make("div", "team-name-clean", teamName);
    row.appendChild(nameDiv);
    
    if (isFavoriteTeamId(teamId, "football-data")) {
        const star = make("span", "favorite-indicator", "★");
        star.style.color = "var(--accent-brand)";
        star.style.marginLeft = "4px";
        star.style.fontSize = "0.9rem";
        nameDiv.appendChild(star);
        row.classList.add("is-favorite-team");
    }
    
    return row;
}


/* ---------- 10. TABELLE ---------- */

document.querySelectorAll(".type-btn").forEach(button => {
    button.addEventListener("click", () => {
        clearActive(".type-btn");
        button.classList.add("active");

        state.tableType = button.dataset.type;

        if (state.competitionCode) loadStandings(state.competitionCode);
    });
});


/**
 * Gesamt/Heim/Auswaerts gibt es nur fuer die nationalen Ligen.
 * Die CL-Ligaphase kennt ausschliesslich die Gesamttabelle, deshalb wird
 * der Switcher dort ausgeblendet und der Zustand hart auf TOTAL gesetzt.
 */
function setTableTypeSwitchVisible(visible) {
    if (visible) {
        show(tableTypeSwitch);
        return;
    }

    hide(tableTypeSwitch);

    state.tableType = "TOTAL";
    clearActive(".type-btn");

    const totalBtn = document.querySelector('.type-btn[data-type="TOTAL"]');
    if (totalBtn) totalBtn.classList.add("active");
}


async function loadStandings(competitionCode) {
    tableContent.innerHTML = "";
    tableContent.appendChild(make("div", "loading-hint", t("table.loading")));

    // Sofort auf die aktuell gewaehlte Saison setzen, damit der Titel nie
    // eine vorherige (falsche) Saison stehen laesst, falls der Request
    // fehlschlaegt oder laenger dauert.
    if (state.competitionName) {
        tableTitle.textContent = `${state.competitionName} ${state.seasonLabel}`;
    }

    try {
        const url = `/api/standings?competition=${competitionCode}&type=${state.tableType}`;
        const data = await fetchJson(
            competitionCode === "cl" ? withExplicitSeason(url) : withSeason(url)
        );

        tableTitle.textContent = `${data.competition} ${data.season}/${String(data.season + 1).slice(2)}`;
        renderStandings(data.table);

    } catch (error) {
        tableContent.innerHTML = "";
        tableContent.appendChild(make("div", "loading-hint", t("table.unavailable", {
            error: error.message,
        })));
    }
}


function renderStandings(rows) {
    tableContent.innerHTML = "";

    if (!rows || !rows.length) {
        const message = state.competitionType === "cl"
            ? t("table.clUnavailable", { season: state.seasonLabel })
            : t("table.empty");
        tableContent.appendChild(make("div", "loading-hint", message));
        return;
    }

    const table = make("table", "standings-table");
    const thead = make("thead");
    const headRow = make("tr");

    [
        { label: "#",                      cls: "col-pos" },
        { label: t("table.column.team"),    cls: "col-team" },
        { label: t("table.column.played"),  cls: "" },
        { label: t("table.column.won"),     cls: "" },
        { label: t("table.column.drawn"),   cls: "" },
        { label: t("table.column.lost"),    cls: "" },
        { label: t("table.column.goals"),   cls: "" },
        { label: t("table.column.difference"), cls: "" },
        { label: t("table.column.points"),  cls: "col-points" },
    ].forEach(column => headRow.appendChild(make("th", column.cls, column.label)));

    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = make("tbody");
    const teamCount = rows.length;

    rows.forEach(row => {
        const tr = make("tr");

        const posCell = make("td", "col-pos");
        posCell.appendChild(make("span", `pos-marker ${positionClass(row.position, teamCount)}`));
        posCell.appendChild(document.createTextNode(String(row.position)));
        tr.appendChild(posCell);

        const teamCell = make("td", "col-team");
        const teamWrap = make("div", "team-cell");
        if (row.crest) teamWrap.appendChild(crest(row.crest));
        teamWrap.appendChild(make("span", null, row.team_name));
        teamCell.appendChild(teamWrap);
        tr.appendChild(teamCell);

        tr.appendChild(make("td", null, String(row.played)));
        tr.appendChild(make("td", null, String(row.won)));
        tr.appendChild(make("td", null, String(row.draw)));
        tr.appendChild(make("td", null, String(row.lost)));
        tr.appendChild(make("td", null, `${row.goals_for}:${row.goals_against}`));
        tr.appendChild(make("td", null, row.goal_difference > 0 ? `+${row.goal_difference}` : String(row.goal_difference)));
        tr.appendChild(make("td", "col-points", String(row.points)));

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    tableContent.appendChild(table);

    if (state.tableType === "TOTAL") tableContent.appendChild(buildLegend());
}


function positionClass(position, teamCount) {
    // CL-Ligaphase: feste Zonen nach UEFA-Format, unabhaengig von teamCount.
    // 1-8 direkt Achtelfinale, 9-24 K.-o.-Play-offs, ab 25 ausgeschieden.
    if (state.competitionType === "cl") {
        if (position <= 8) return "pos-cl";
        if (position <= 24) return "pos-el";
        return "pos-relegation";
    }

    if (position <= 4) return "pos-cl";
    if (position <= 6) return "pos-el";
    if (position > teamCount - 3) return "pos-relegation";
    return "";
}


function buildLegend() {
    const legend = make("div", "table-legend");

    const items = state.competitionType === "cl"
        ? [
            { cls: "pos-cl",         text: t("table.legend.clDirect") },
            { cls: "pos-el",         text: t("table.legend.clPlayoffs") },
            { cls: "pos-relegation", text: t("table.legend.eliminated") },
        ]
        : [
            { cls: "pos-cl",         text: t("table.legend.championsLeague") },
            { cls: "pos-el",         text: t("table.legend.europe") },
            { cls: "pos-relegation", text: t("table.legend.relegation") },
        ];

    items.forEach(item => {
        const wrap = make("div", "legend-item");
        wrap.appendChild(make("span", `legend-dot ${item.cls}`));
        wrap.appendChild(make("span", null, item.text));
        legend.appendChild(wrap);
    });

    return legend;
}


/* ---------- 11. TORJAEGER ---------- */

async function loadScorers(competitionCode) {
    scorersContent.innerHTML = "";
    scorersContent.appendChild(make("div", "loading-hint", t("scorers.loading")));

    try {
        const url = `/api/player-scorers?competition=${competitionCode}&limit=20`;
        const data = await fetchJson(
            competitionCode === "cl" ? withExplicitSeason(url) : withSeason(url)
        );

        scorersTitle.textContent = t("scorers.competitionTitle", { competition: data.competition });

        if (data.empty_state) {
            scorersContent.innerHTML = "";
            scorersContent.appendChild(
                make("div", "loading-hint", activeLocale === "de" && data.empty_state_message
                    ? data.empty_state_message
                    : t("scorers.empty"))
            );
            return;
        }

        renderScorers(data.scorers);

    } catch (error) {
        scorersContent.innerHTML = "";
        scorersContent.appendChild(
            make("div", "loading-hint", t("scorers.unavailable", { error: error.message }))
        );
    }
}


function renderScorers(scorers) {
    scorersContent.innerHTML = "";

    if (!scorers || !scorers.length) {
        scorersContent.appendChild(make("div", "loading-hint", t("scorers.noPlayers")));
        return;
    }

    scorers.forEach(scorer => {
        const row = make("div", "scorer-row");
        if (scorer.rank <= 3) row.classList.add("top-three");

        row.appendChild(make("div", "scorer-rank", String(scorer.rank)));

        // Spielerfoto (API-Sports) mit Initialen-Fallback (football-data).
        row.appendChild(playerAvatar(scorer));

        // Team-Logo heisst jetzt einheitlich team_logo (beide Quellen).
        if (scorer.team_logo) row.appendChild(crest(scorer.team_logo, "scorer-crest"));

        const info = make("div", "scorer-info");
        info.appendChild(make("div", "scorer-name", scorer.player_name));
        info.appendChild(make("div", "scorer-team",
            scorer.appearances
                ? t("scorers.appearances", {
                    team: scorer.team_name,
                    count: scorer.appearances,
                })
                : scorer.team_name
        ));
        row.appendChild(info);

        const stats = make("div", "scorer-stats");
        stats.appendChild(buildStat(scorer.goals, t("metric.goals")));

        if (scorer.assists !== null && scorer.assists !== undefined) {
            stats.appendChild(buildStat(scorer.assists, t("scorers.assists")));
        }

        row.appendChild(stats);
        scorersContent.appendChild(row);
    });
}


/**
 * Baut den Spieler-Avatar. Wenn ein Foto da ist (API-Sports), wird es
 * geladen; bei fehlendem oder kaputtem Bild fallen wir auf die Initialen
 * des Spielers zurueck. So sieht der Tab bei beiden Quellen sauber aus.
 */
function playerAvatar(scorer) {
    const wrap = make("div", "scorer-avatar");
    wrap.appendChild(make("span", "scorer-avatar-initials", initials(scorer.player_name)));

    if (scorer.player_photo) {
        const img = make("img", "scorer-avatar-img");
        img.src = scorer.player_photo;
        img.alt = "";
        img.loading = "lazy";
        // Bei Ladefehler bleibt nur die Initialen-Schicht sichtbar.
        img.onload = () => wrap.classList.add("has-photo");
        img.onerror = () => img.remove();
        wrap.appendChild(img);
    }

    return wrap;
}


/** Erste Buchstaben von Vor- und Nachname, z. B. "Harry Kane" -> "HK". */
function initials(name) {
    if (!name) return "?";
    const parts = name.trim().split(/\s+/);
    const first = parts[0]?.[0] || "";
    const last  = parts.length > 1 ? parts[parts.length - 1][0] : "";
    return (first + last).toUpperCase() || "?";
}


function buildStat(value, label) {
    const wrap = make("div", "scorer-stat");
    wrap.appendChild(make("strong", null, String(value)));
    wrap.appendChild(make("span", null, label));
    return wrap;
}


/* ---------- 12. SIMULATION ---------- */

simulateBtn.addEventListener("click", runSimulation);

/* Teilen-Knopf: GENAU EIN Listener, hier auf Modulebene registriert.
 *
 * Bewusst nicht in renderResult() - dort liefe die Registrierung bei
 * jeder Simulation erneut, und nach der dritten Simulation oeffneten
 * sich drei Share Sheets. Der Listener liest den jeweils aktuellen
 * Stand aus letztesTeilbaresErgebnis, statt Daten einzuschliessen. */
(function () {
    const knopf = document.getElementById("share-result-btn");
    if (!knopf) return;

    knopf.addEventListener("click", () => {
        if (!letztesTeilbaresErgebnis) return;
        nativeTeilen(letztesTeilbaresErgebnis);
    });
})();

backToFixtures.addEventListener("click", () => switchTab("fixtures"));


async function runSimulation() {
    if (!state.selectedMatch) {
        setStatus(t("simulation.selectMatch"), true);
        return;
    }

    const payload = {
        competition: state.competitionCode,
        simulations: parseInt(el("simulations").value, 10) || 5000,
        use_seed: el("use-seed").checked,
    };

    if (state.competitionType === "league" || state.competitionType === "cl") {
        // Ligen UND Champions League: Backend erwartet home_team, away_team,
        // home_id, away_id. Fuer CL wurde dieser Vertrag in B1 eingefuehrt,
        // der alte match_id/leg_mode-Pfad ist entfernt.
        payload.home_team = state.selectedMatch.home_team;
        payload.away_team = state.selectedMatch.away_team;
        payload.home_id = state.selectedMatch.home_id;
        payload.away_id = state.selectedMatch.away_id;
        if (state.season !== null) payload.season = state.season;
    } else {
        payload.match_id = state.selectedMatchId;
        payload.leg_mode = state.clLegMode || "first";
    }

    // Haptik genau hier: Der Nutzer hat eine bewusste Aktion ausgeloest,
    // die Nutzlast steht, und es folgt eine spuerbare Wartezeit. Frueher
    // (beim blossen Klick) waere es ein Signal ohne Aussage - der Aufruf
    // kann noch an fehlenden Teams scheitern und oben zurueckkehren.
    // Ausserhalb der iOS-Huelle passiert nichts.
    nativeHaptik("medium");

    // Teilen-Knopf sofort verbergen. Scheitert die Simulation, laeuft
    // renderResult() nicht - ohne diese Zeile bliebe der Knopf mit dem
    // ERGEBNIS DER VORIGEN Partie stehen und wuerde es unter dem neuen
    // Spiel teilen.
    aktualisiereTeilenKnopf(null);

    simulateBtn.disabled = true;
    simulateBtn.textContent = t("simulation.calculating");
    setStatus(t("simulation.running"));

    try {
        const data = await fetchJson("/api/simulate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        renderResult(data);

        // Direkt zum Ergebnis wechseln, damit niemand danach suchen muss
        switchTab("simulation");
        setStatus(t("simulation.complete"));

    } catch (error) {
        setStatus(error.message, true);
    } finally {
        simulateBtn.disabled = false;
        simulateBtn.textContent = t("fixtures.runSimulation");
    }
}


/* Zuletzt angezeigtes Ergebnis, aufbereitet fuer das Share Sheet.
 *
 * Wird ausschliesslich von renderResult() gesetzt - aus denselben
 * Werten, die auch auf dem Bildschirm stehen. Es findet KEINE zweite
 * Berechnung statt: Was geteilt wird, ist genau das Sichtbare.
 *
 * Bei einer fehlgeschlagenen Simulation laeuft renderResult() gar nicht;
 * der Wert bleibt dann auf null und der Knopf verborgen - es kann also
 * kein altes Ergebnis unter einem neuen Spiel geteilt werden. */
let letztesTeilbaresErgebnis = null;

/**
 * Baut den Teilen-Text aus dem angezeigten Ergebnis.
 *
 * Enthaelt Wettbewerb, Mannschaften und die sichtbare Verteilung.
 * Enthaelt AUSDRUECKLICH NICHT: Kontodaten, E-Mail, Tokens, interne IDs
 * oder Rohdaten der Antwort - die Felder werden einzeln entnommen, nicht
 * das Antwortobjekt durchgereicht.
 *
 * Der Zusatz ist bewusst neutral formuliert: eine Verteilung aus einer
 * Simulation, keine Vorhersage und kein Tipp.
 */
function baueTeilenNutzlast(data) {
    const wettbewerb = data.competition || state.competitionName || "FootSim";

    const zeilen = [
        `${wettbewerb}: ${data.home_team} - ${data.away_team}`,
        `${data.home_team} ${data.home_win_probability}% | `
            + `${t("simulation.draw")} ${data.draw_probability}% | `
            + `${data.away_team} ${data.away_win_probability}%`,
        t("simulation.shareNote"),
    ];

    return {
        titel: "FootSim",
        text: zeilen.join("\n"),
        // Eigene Herkunft statt fest verdrahtetem "https://footsim.de".
        // In Produktion ist das exakt dasselbe, aber es haelt sich an die
        // Origin-Regel der Bruecke - eine fremde Adresse wuerde dort
        // verworfen, und der Link fiele stumm aus der Nutzlast.
        url: window.location.origin,
    };
}

/** Blendet den Teilen-Knopf ein oder aus - nur in der iOS-Huelle. */
function aktualisiereTeilenKnopf(data) {
    const knopf = document.getElementById("share-result-btn");
    if (!knopf) return;

    // Drei Bedingungen, alle noetig:
    //   1. iOS-Huelle - im Browser gibt es die Systemfunktion schon
    //   2. Kanal wirklich registriert - sonst waere der Knopf tot
    //   3. ein Ergebnis liegt vor
    const nutzbar = istNativeHuelle() && nativerKanal("share") !== null && data !== null;

    letztesTeilbaresErgebnis = nutzbar ? baueTeilenNutzlast(data) : null;
    knopf.hidden = !nutzbar;
}

function renderResult(data) {
    hide(simEmpty);
    show(resultBox);

    el("match-title").textContent = t("fixtures.matchup", {
        home: data.home_team,
        away: data.away_team,
    });

    const outcomes = [
        { label: t("simulation.win", { team: data.home_team }), value: data.home_win_probability },
        { label: t("simulation.draw"),                          value: data.draw_probability },
        { label: t("simulation.win", { team: data.away_team }), value: data.away_win_probability },
    ];

    const top = outcomes.reduce((best, current) => current.value > best.value ? current : best);

    el("top-pick-name").textContent = top.label;
    el("top-pick-value").textContent = t("simulation.percent", { value: top.value });

    el("xg-home-team").textContent = data.home_team;
    el("xg-away-team").textContent = data.away_team;
    el("xg-home").textContent = data.expected_home_goals;
    el("xg-away").textContent = data.expected_away_goals;

    if (data.top_scores && data.top_scores.length) {
        el("best-score").textContent = data.top_scores[0].score;
        el("best-score-count").textContent = t("simulation.ofAllRuns", {
            count: data.top_scores[0].count,
        });
    }

    renderProbabilityBars(outcomes);
    renderTopScores(data.top_scores);

    if (data.is_two_legged_tie) {
        renderKnockout(data);
        show(knockoutSection);
    } else {
        hide(knockoutSection);
    }

    // Zuletzt, wenn alle Werte stehen: Der Teilen-Text wird aus genau
    // diesen Daten gebildet. Bei jeder weiteren Simulation laeuft das
    // erneut und ersetzt den alten Inhalt vollstaendig.
    aktualisiereTeilenKnopf(data);
}


function renderProbabilityBars(outcomes) {
    const container = el("probability-bars");
    container.innerHTML = "";

    outcomes.forEach(outcome => {
        const block = make("div", "bar-block");

        const header = make("div", "bar-header");
        header.appendChild(make("span", null, outcome.label));
        header.appendChild(make("span", null, t("simulation.percent", { value: outcome.value })));

        const track = make("div", "bar-track");
        const fill = make("div", "bar-fill");
        fill.style.width = `${outcome.value}%`;
        track.appendChild(fill);

        block.appendChild(header);
        block.appendChild(track);
        container.appendChild(block);
    });
}


function renderTopScores(scores) {
    const container = el("top-scores");
    container.innerHTML = "";

    if (!scores || !scores.length) {
        container.appendChild(make("div", "loading-hint", t("simulation.noResults")));
        return;
    }

    const total = scores.reduce((sum, entry) => sum + entry.count, 0);

    scores.forEach((entry, index) => {
        const row = make("div", "score-row");

        const left = make("div", "score-left");
        left.appendChild(make("div", "rank-badge", String(index + 1)));

        const textWrap = make("div");
        textWrap.appendChild(make("div", "score-name", entry.score));
        textWrap.appendChild(make("div", "score-sub",
            t("simulation.scoreShare", {
                percent: ((entry.count / total) * 100).toFixed(1),
            })));
        left.appendChild(textWrap);

        const right = make("div", "score-count");
        right.appendChild(make("div", null, String(entry.count)));
        right.appendChild(make("div", "score-count-label", t("simulation.runs")));

        row.appendChild(left);
        row.appendChild(right);
        container.appendChild(row);
    });
}


function renderKnockout(data) {
    knockoutContent.innerHTML = "";

    if (data.first_leg_score) {
        const info = make("div", "knockout-card");
        info.appendChild(make("p", null, t("simulation.firstLeg")));
        info.appendChild(make("div", "knockout-value", data.first_leg_score));
        knockoutContent.appendChild(info);
    }

    const grid = make("div", "knockout-columns");

    [
        {
            title: t("simulation.qualification"),
            rows: [
                [data.home_team, t("simulation.percent", { value: data.qualification_home_probability })],
                [data.away_team, t("simulation.percent", { value: data.qualification_away_probability })],
            ],
        },
        {
            title: t("simulation.extraTimeAndPenalties"),
            rows: [
                [t("simulation.extraTime"), t("simulation.percent", { value: data.extra_time_probability })],
                [t("simulation.penalties"), t("simulation.percent", { value: data.penalties_probability })],
            ],
        },
        {
            title: t("simulation.penaltyDecision"),
            rows: [
                [data.home_team, t("simulation.percent", { value: data.home_qualifies_on_penalties_probability })],
                [data.away_team, t("simulation.percent", { value: data.away_qualifies_on_penalties_probability })],
            ],
        },
    ].forEach(card => {
        const node = make("div", "knockout-card");
        node.appendChild(make("p", null, card.title));

        card.rows.forEach(([label, value]) => {
            const row = make("div", "knockout-row");
            row.appendChild(make("span", null, label));
            row.appendChild(make("strong", null, value));
            node.appendChild(row);
        });

        grid.appendChild(node);
    });

    knockoutContent.appendChild(grid);

    if (data.top_aggregate_scores && data.top_aggregate_scores.length) {
        const aggregate = make("div", "knockout-card aggregate-list");
        aggregate.appendChild(make("p", null, t("simulation.commonAggregateScores")));

        data.top_aggregate_scores.forEach(entry => {
            const row = make("div", "knockout-row");
            row.appendChild(make("span", null, entry.score));
            row.appendChild(make("strong", null, t("simulation.occurrences", { count: entry.count })));
            aggregate.appendChild(row);
        });

        knockoutContent.appendChild(aggregate);
    }
}


/* ---------- 13. LIGENVERGLEICH: UNTERMODUS UND AUSWAHL ---------- */

document.querySelectorAll(".compare-mode-btn").forEach(button => {
    button.addEventListener("click", () => {
        clearActive(".compare-mode-btn");
        button.classList.add("active");

        state.compareMode = button.dataset.cmode;

        compareResult.innerHTML = "";
        hide(compareResult);
        show(compareEmpty);

        // Klassische Liga-Auswahl ist in beiden Untermodi sichtbar.
        show(el("compare-league-head"));
        show(compareLeagueList);
        show(compareBtn);
        show(compareStatus);

        if (state.compareMode === "cup") {
            show(phaseSection);
            compareEyebrow.textContent = "Champions League";
            compareHeading.textContent = t("compare.cupHeading");
            compareHint.textContent = t("compare.cupHint");
        } else {
            hide(phaseSection);
            compareEyebrow.textContent = t("compare.leagueTitle");
            compareHeading.textContent = t("compare.heading");
            compareHint.textContent = t("compare.hint");
        }
    });
});


document.querySelectorAll(".phase-btn").forEach(button => {
    button.addEventListener("click", () => {
        clearActive(".phase-btn");
        button.classList.add("active");

        state.comparePhase = button.dataset.phase;
        const phaseHintKey = PHASE_TEXTS[state.comparePhase];
        phaseHint.textContent = phaseHintKey ? t(phaseHintKey) : "";

        // Ein Ergebnis gehoert immer zu genau einer Phase. Blieb es beim
        // Umschalten stehen, zeigte die Seite Zahlen der alten Phase
        // unter der Beschriftung der neuen - derselbe Fehlertyp wie bei
        // der Saison, nur eine Ebene tiefer.
        //
        // Die Ligaauswahl bleibt erhalten und es wird bewusst KEINE neue
        // Anfrage ausgeloest: der Nutzer entscheidet, wann gerechnet wird.
        compareResult.innerHTML = "";
        hide(compareResult);
        show(compareEmpty);

        const count = state.compareSelection.length;
        compareStatus.textContent = count < 2
            ? t("compare.minimumTwo")
            : t("compare.selectedCount", { count });
    });
});


function renderCompareLeagues(leagues) {
    compareLeagueList.innerHTML = "";

    leagues.forEach(league => {
        const button = make("button", "compare-league-option");
        button.dataset.code = league.code;

        button.appendChild(make("span", "compare-check", ""));
        button.appendChild(crest(league.emblem));

        const textWrap = make("div");
        textWrap.appendChild(make("div", "compare-league-name", league.name));
        textWrap.appendChild(make("div", "compare-league-country", league.country));
        button.appendChild(textWrap);

        button.addEventListener("click", () => toggleCompareLeague(league.code, button));

        compareLeagueList.appendChild(button);
    });

    // Auswahl nach dem Neuaufbau wiederherstellen
    state.compareSelection.forEach((code, index) => {
        const node = compareLeagueList.querySelector(`[data-code="${code}"]`);
        if (node) {
            node.classList.add("selected");
            node.querySelector(".compare-check").textContent = String(index + 1);
        }
    });
}


function toggleCompareLeague(code, button) {
    const index = state.compareSelection.indexOf(code);

    if (index >= 0) {
        state.compareSelection.splice(index, 1);
        button.classList.remove("selected");
        button.querySelector(".compare-check").textContent = "";
    } else {
        if (state.compareSelection.length >= 5) {
            compareStatus.textContent = t("compare.maximumFive");
            return;
        }
        state.compareSelection.push(code);
        button.classList.add("selected");
    }

    state.compareSelection.forEach((selectedCode, position) => {
        const node = compareLeagueList.querySelector(`[data-code="${selectedCode}"] .compare-check`);
        if (node) node.textContent = String(position + 1);
    });

    const count = state.compareSelection.length;
    compareBtn.disabled = count < 2;

    compareStatus.textContent = count < 2
        ? t("compare.minimumTwo")
        : t("compare.selectedCount", { count });
}


compareBtn.addEventListener("click", runComparison);


async function runComparison() {
    if (state.compareSelection.length < 2) return;

    compareBtn.disabled = true;
    compareBtn.textContent = t("compare.calculating");
    compareStatus.textContent = t("compare.evaluatingSeason");

    const leagues = state.compareSelection.join(",");

    // CL braucht die Saison IMMER explizit (withExplicitSeason).
    // withSeason() laesst den Parameter bei der laufenden Saison weg und
    // ueberlaesst die Wahl der Auto-Erkennung des Anbieters - und dessen
    // CL-Saison laeuft den nationalen Ligen hinterher. Genau dadurch
    // wurde unter der Auswahl 2026/27 die Saison 2025/26 ausgewertet.
    //
    // Der direkte Ligavergleich bleibt bewusst bei withSeason(): er
    // fragt ausschliesslich nationale Wettbewerbe ab, deren
    // Auto-Erkennung mit der Bezugsliga des Saison-Pickers
    // uebereinstimmt. Dort gibt es den Versatz nicht.
    const url = state.compareMode === "cup"
        ? withExplicitSeason(`/api/cup-compare?leagues=${leagues}&phase=${state.comparePhase}&cup=cl`)
        : withSeason(`/api/compare?leagues=${leagues}`);

    try {
        const data = await fetchJson(url);

        if (state.compareMode === "cup") {
            renderCupComparison(data);
        } else {
            renderComparison(data);
        }

        compareStatus.textContent = t("compare.ready");

    } catch (error) {
        const payload = error && error.data;

        if (payload && payload.code === COMPETITION_DATA_PENDING) {
            renderComparePending(payload);
        } else {
            compareStatus.textContent = error.message;
        }
    } finally {
        compareBtn.disabled = false;
        compareBtn.textContent = t("compare.run");
    }
}


//: Antwortcode fuer "die Datenquelle fuehrt diesen Wettbewerb fuer diese
//: Saison noch nicht". Muss zu COMPETITION_DATA_PENDING in app.py passen.
const COMPETITION_DATA_PENDING = "COMPETITION_DATA_PENDING";


/**
 * Ruhiger Leerzustand statt Fehlermeldung.
 *
 * Die Saison ist gueltig, FootSim laeuft, die Anfrage war richtig - die
 * Datenquelle fuehrt den Wettbewerb nur noch nicht. Frueher landete
 * genau das als HTTP 503 im Status und der Nutzer las "Request failed
 * (503)" bzw. den rohen deutschen Anbietertext.
 *
 * Gerendert wird in den ERGEBNISBEREICH, nicht in den Standard-
 * Leerzustand: dadurch raeumen alle bestehenden Reset-Pfade - Saison-,
 * Phasen- und Moduswechsel sowie ein spaeter erfolgreicher Vergleich -
 * diesen Zustand automatisch mit weg. Es braucht keinen zusaetzlichen
 * Aufraeumcode, der irgendwann vergessen wird.
 *
 * Wiederverwendet die vorhandene .empty-state-Klasse: gedaempfte Farbe,
 * gestrichelter Rahmen, mobil bereits angepasst. Kein neues CSS, keine
 * Warnfarbe, kein Modal.
 */
function renderComparePending(payload) {
    const params = payload.error_params || {};
    const title = t(payload.error_key || "compare.cupPendingTitle", params);
    const text = t(payload.error_text_key || "compare.cupPendingText", params);

    compareResult.innerHTML = "";

    const box = make("div", "empty-state");
    // Einzige Live-Region dieses Zustands. Die Statuszeile bekommt
    // bewusst keine - sonst kuendigen Screenreader zweimal an.
    box.setAttribute("role", "status");
    box.appendChild(make("h2", null, title));
    box.appendChild(make("p", null, text));
    compareResult.appendChild(box);

    hide(compareEmpty);
    show(compareResult);

    // Die Statuszeile faellt auf den neutralen Auswahlstand zurueck: der
    // Nutzer kann jederzeit erneut auf "Vergleichen" druecken, und
    // sobald Daten vorliegen, erscheint der normale Vergleich.
    const count = state.compareSelection.length;
    compareStatus.textContent = count < 2
        ? t("compare.minimumTwo")
        : t("compare.selectedCount", { count });
}


/**
 * Balkenbreite für eine Kennzahl bestimmen.
 * Bezugsgroesse ist der größte Betrag in der Zeile, damit die Balken
 * untereinander vergleichbar sind. Negative Werte, etwa eine negative
 * Tordifferenz, werden vorher nach oben verschoben.
 */
function barWidths(row, leagues) {
    const werte = {};

    leagues.forEach(l => {
        const v = row.values[l.code];
        if (v !== null && v !== undefined) werte[l.code] = Number(v);
    });

    const codes = Object.keys(werte);
    if (!codes.length) return {};

    const min = Math.min(...Object.values(werte));
    const shift = min < 0 ? -min : 0;

    const verschoben = {};
    codes.forEach(c => { verschoben[c] = werte[c] + shift; });

    const max = Math.max(...Object.values(verschoben));
    if (max <= 0) return Object.fromEntries(codes.map(c => [c, 6]));

    // Mindestbreite, damit auch kleine Werte sichtbar bleiben
    return Object.fromEntries(
        codes.map(c => [c, Math.max(6, Math.round(100 * verschoben[c] / max))])
    );
}


/**
 * Kartenansicht der Kennzahlen für schmale Bildschirme.
 * Statt einer Tabelle mit vielen Spalten bekommt jede Kennzahl eine
 * eigene Karte, in der die Ligen als Balken untereinander stehen.
 */
function buildMetricCards(section, leagues) {
    const wrap = make("div", "metric-cards");

    section.rows.forEach(row => {
        const card = make("div", "metric-card");

        const head = make("div", "metric-card-head");
        head.appendChild(make("span", "metric-card-title", compareMetricLabel(row)));
        card.appendChild(head);

        const breiten = barWidths(row, leagues);

        // Ligen nach Wert sortieren, beste zuerst.
        // Bei Kennzahlen, wo weniger besser ist, umgekehrt.
        const sortiert = [...leagues].sort((a, b) => {
            const va = row.values[a.code];
            const vb = row.values[b.code];
            if (va === null || va === undefined) return 1;
            if (vb === null || vb === undefined) return -1;
            return Number(vb) - Number(va);
        });

        sortiert.forEach(league => {
            const wert = row.values[league.code];
            const zeile = make("div", "metric-row");

            if (row.winner === league.code) zeile.classList.add("is-winner");

            const name = make("div", "metric-row-name", league.name);
            zeile.appendChild(name);

            const balkenBox = make("div", "metric-bar-box");
            const balken = make("div", "metric-bar");
            balken.style.width = `${breiten[league.code] || 0}%`;
            balkenBox.appendChild(balken);
            zeile.appendChild(balkenBox);

            const wertText = make("div", "metric-row-value",
                (wert === null || wert === undefined) ? "-" : `${wert}${row.unit || ""}`);
            zeile.appendChild(wertText);

            card.appendChild(zeile);
        });

        wrap.appendChild(card);
    });

    return wrap;
}


/**
 * Turnierverlauf als Karten: eine Karte je Liga mit den erreichten Runden.
 */
function buildReachedCards(reached) {
    const wrap = make("div", "metric-cards");

    reached.forEach(entry => {
        const card = make("div", "metric-card");

        const head = make("div", "metric-card-head");
        head.appendChild(make("span", "metric-card-title", entry.name));
        card.appendChild(head);

        const chips = make("div", "stage-chips");

        Object.entries(entry.stages || {}).forEach(([runde, anzahl]) => {
            const chip = make("div", "stage-chip");
            if (!anzahl) chip.classList.add("stage-chip-empty");

            chip.appendChild(make("span", "stage-chip-name", cupStageLabel(runde)));
            chip.appendChild(make("span", "stage-chip-count", anzahl ? String(anzahl) : "-"));

            chips.appendChild(chip);
        });

        card.appendChild(chips);
        wrap.appendChild(card);
    });

    return wrap;
}


/** Baut eine Kennzahlentabelle für breite Bildschirme. */
function buildMetricTable(section, leagues) {
    const table = make("table", "compare-table");

    const thead = make("thead");
    const headRow = make("tr");
    headRow.appendChild(make("th", null, t("compare.metric")));
    leagues.forEach(league => headRow.appendChild(make("th", null, league.name)));
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = make("tbody");

    section.rows.forEach(row => {
        const tr = make("tr");
        tr.appendChild(make("td", null, compareMetricLabel(row)));

        leagues.forEach(league => {
            const td = make("td");
            const value = row.values[league.code];

            let cls = "compare-value neutral";
            if (value === null || value === undefined) cls = "compare-value empty";
            else if (row.winner === league.code)       cls = "compare-value winner";

            td.appendChild(make("span", cls, formatValue(value, row.unit)));
            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    return table;
}


function renderComparison(data) {
    hide(compareEmpty);
    show(compareResult);
    compareResult.innerHTML = "";

    const header = make("div", "compare-header");

    data.leagues.forEach(league => {
        const card = make("div", "compare-header-card");

        if (league.emblem) card.appendChild(crest(league.emblem));

        card.appendChild(make("div", "compare-header-name", league.name));

        if (league.leader) {
            card.appendChild(make("div", "compare-header-leader", t("compare.leader", {
                team: league.leader.team_name,
                points: league.leader.points,
                played: league.leader.played,
            })));
        }

        header.appendChild(card);
    });

    compareResult.appendChild(header);

    data.sections.forEach(section => {
        if (!section.rows || !section.rows.length) return;

        const wrap = make("div", "compare-section");
        wrap.appendChild(make("h3", "compare-section-title", compareSectionLabel(section)));

        // Zwei Darstellungen, die per CSS gegeneinander getauscht werden.
        // Auf breiten Bildschirmen die Tabelle, auf schmalen die Karten.
        const tabelle = make("div", "view-wide");
        tabelle.appendChild(buildMetricTable(section, data.leagues));
        wrap.appendChild(tabelle);

        const karten = make("div", "view-narrow");
        karten.appendChild(buildMetricCards(section, data.leagues));
        wrap.appendChild(karten);

        compareResult.appendChild(wrap);
    });
}


/* ---------- 14. LIGENVERGLEICH IM POKAL ---------- */

function renderCupComparison(data) {
    hide(compareEmpty);
    show(compareResult);
    compareResult.innerHTML = "";

    // Kopfzeile mit Wettbewerb, Saison und Phase
    const intro = make("div", "cup-intro");
    intro.appendChild(make("p", "eyebrow", `${data.cup.name} ${data.season}/${String(data.season + 1).slice(2)}`));
    intro.appendChild(make("h2", null, cupComparisonPhaseLabel(data.phase, data.phase_label)));

    if (data.stages_played && data.stages_played.length) {
        intro.appendChild(make("p", "cup-intro-sub",
            t("compare.evaluatedStages", { stages: data.stages_played.map(cupStageLabel).join(", ") })));
    }

    if (data.notice) {
        intro.appendChild(make("p", "cup-notice", activeLocale === "de"
            ? data.notice
            : t("compare.cupNotice")));
    }

    compareResult.appendChild(intro);

    // Das Ranking zuerst, weil es die Kernaussage ist
    compareResult.appendChild(buildRanking(data.ranking));

    // Teilnehmerkarten
    const header = make("div", "compare-header");

    data.leagues.forEach(league => {
        const card = make("div", "compare-header-card");

        if (league.emblem) card.appendChild(crest(league.emblem));

        card.appendChild(make("div", "compare-header-name", league.name));
        card.appendChild(make("div", "compare-header-leader", t("compare.teamsParticipating", {
            count: league.teams,
        })));

        if (league.is_champion) {
            card.appendChild(make("div", "champion-badge", t("compare.champion")));
        }

        if (league.biggest_win) {
            card.appendChild(make("div", "compare-header-extra",
                t("compare.biggestWin", { result: league.biggest_win.label })));
        }

        header.appendChild(card);
    });

    compareResult.appendChild(header);

    // Kennzahlen
    data.sections.forEach(section => {
        if (!section.rows || !section.rows.length) return;

        const wrap = make("div", "compare-section");
        wrap.appendChild(make("h3", "compare-section-title", compareSectionLabel(section)));

        const tabelle = make("div", "view-wide");
        tabelle.appendChild(buildMetricTable(section, data.leagues));
        wrap.appendChild(tabelle);

        const karten = make("div", "view-narrow");
        karten.appendChild(buildMetricCards(section, data.leagues));
        wrap.appendChild(karten);

        compareResult.appendChild(wrap);
    });

    // Wie weit kam wer
    if (data.reached && data.reached.length) {
        const wrap = make("div", "compare-section");
        wrap.appendChild(make("h3", "compare-section-title", t("compare.reachedTitle")));

        const tabelle = make("div", "view-wide");
        tabelle.appendChild(buildReachedTable(data.reached));
        wrap.appendChild(tabelle);

        const karten = make("div", "view-narrow");
        karten.appendChild(buildReachedCards(data.reached));
        wrap.appendChild(karten);

        compareResult.appendChild(wrap);
    }
}


function buildRanking(ranking) {
    const wrap = make("div", "ranking-block");

    wrap.appendChild(make("h3", "compare-section-title", t("compare.overallRanking")));

    // Kurzer Hinweis direkt ueber der Liste – kein langer Satz unten
    const hint = make("p", "ranking-score-hint", t("compare.rankingHint"));
    wrap.appendChild(hint);

    const list = make("div", "ranking-list");

    ranking.entries.forEach(entry => {
        const row = make("div", "ranking-row");
        if (entry.position === 1) row.classList.add("ranking-first");

        row.appendChild(make("div", "ranking-position", String(entry.position)));

        if (entry.emblem) row.appendChild(crest(entry.emblem, "ranking-emblem"));

        const info = make("div", "ranking-info");
        const nameLine = make("div", "ranking-name", entry.name);
        info.appendChild(nameLine);

        const subParts = [t("compare.teams", { count: entry.teams })];
        if (entry.is_champion) subParts.push(t("compare.champion"));
        info.appendChild(make("div", "ranking-sub", subParts.join(" · ")));

        row.appendChild(info);

        const scoreWrap = make("div", "ranking-score");
        scoreWrap.appendChild(make("strong", null, String(entry.score)));
        scoreWrap.appendChild(make("span", null, t("compare.outOfHundred")));
        row.appendChild(scoreWrap);

        list.appendChild(row);

        // Aufschluesselung, damit das Ergebnis nachvollziehbar bleibt
        if (entry.breakdown && entry.breakdown.length) {
            const detail = make("div", "ranking-breakdown");

            entry.breakdown.forEach(item => {
                const chip = make("div", "breakdown-chip");
                chip.appendChild(make("span", "breakdown-label", t(`compare.metric.${item.key}`)));
                chip.appendChild(make("span", "breakdown-weight", `${item.weight_percent} %`));
                chip.appendChild(make("span", "breakdown-score", String(item.score)));
                detail.appendChild(chip);
            });

            list.appendChild(detail);
        }
    });

    wrap.appendChild(list);

    // Gewichtung offenlegen
    // Gewichtung kompakt – Basis (K.o. oder nur Liga) wird genannt
    const weights = make("p", "ranking-weights", t("compare.rankingWeights", {
        basis: activeLocale === "de" ? ranking.basis : t("compare.rankingBasis"),
        weights: ranking.weights.map(w => `${compareWeightLabel(w)} ${w.weight_percent} %`).join(", "),
    }));
    wrap.appendChild(weights);

    return wrap;
}


function buildReachedTable(reached) {
    const wrap = make("div");

    const stageNames = Object.keys(reached[0].stages || {});

    const table = make("table", "compare-table");

    const thead = make("thead");
    const headRow = make("tr");
    headRow.appendChild(make("th", null, t("compare.league")));
    stageNames.forEach(name => headRow.appendChild(make("th", null, cupStageLabel(name))));
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = make("tbody");

    reached.forEach(entry => {
        const tr = make("tr");
        tr.appendChild(make("td", null, entry.name));

        stageNames.forEach(name => {
            const td = make("td");
            const count = entry.stages[name];
            const cls = count > 0 ? "compare-value neutral" : "compare-value empty";
            td.appendChild(make("span", cls, count > 0 ? String(count) : "-"));
            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    wrap.appendChild(table);

    return wrap;
}



/* ---------- SAISONSIMULATION ---------- */

function initSeasonSim() {
    if (!state.competitionCode || state.competitionType !== "league") return;

    seasonSimLeagueLabel.textContent = state.competitionName;
    hide(seasonSimEmpty);
    show(seasonSimControls);
    hide(seasonSimResult);
}

seasonSimBtn.addEventListener("click", runSeasonSim);
seasonSimRerun.addEventListener("click", runSeasonSim);

async function runSeasonSim() {
    if (!state.competitionCode) return;

    const sims = parseInt(el("season-simulations").value, 10) || 10000;

    seasonSimBtn.disabled = true;
    seasonSimBtn.textContent = t("seasonSimulation.inProgress");
    hide(seasonSimResult);
    setStatus(t("seasonSimulation.running", { count: sims.toLocaleString(activeIntlLocale()) }));

    const url = withSeason(`/api/season-sim?competition=${state.competitionCode}&simulations=${sims}`);

    try {
        const data = await fetchJson(url);
        renderSeasonSim(data);
        switchTab("season");
        setStatus(t("seasonSimulation.ready"));
    } catch (error) {
        setStatus(error.message, true);
    } finally {
        seasonSimBtn.disabled = false;
        seasonSimBtn.textContent = t("seasonSimulation.run");
    }
}

function renderSeasonSim(data) {
    const season = data.season;
    const nextYear = season ? String(season + 1).slice(2) : "";
    const label = season ? `${season}/${nextYear}` : "";

    seasonSimTitle.textContent = `${data.competition} ${label}`;
    seasonSimEyebrow.textContent = t("seasonSimulation.heading");

    const favorite = data.entries && data.entries[0];
    if (favorite) {
        seasonSimFavorite.textContent = favorite.team_name;
        seasonSimFavPct.textContent = t("seasonSimulation.champion", { percent: favorite.champion_pct });
    }

    if (data.season_done) {
        seasonSimInfo.textContent = t("seasonSimulation.complete");
    } else {
        seasonSimInfo.textContent = t("seasonSimulation.info", {
            simulations: data.simulations.toLocaleString(activeIntlLocale()),
            remaining: data.games_remaining,
            played: data.played_matchdays,
            total: data.total_matchdays,
        });
    }

    renderSeasonQualityHint(data);
    renderSeasonTable(data);
    hide(seasonSimControls);
    show(seasonSimResult);
}

/**
 * Zeigt einen Hinweis zur Datengrundlage der Simulation.
 *
 * Der Text richtet sich nach dem tatsaechlichen Zustand:
 * zu Saisonbeginn stuetzt sich alles auf die Vorsaisons, spaeter
 * uebernimmt die laufende Saison. Fehlen einzelnen Teams die Daten,
 * wird das benannt statt verschwiegen.
 */
function renderSeasonQualityHint(data) {
    const old = el("season-quality-hint");
    if (old) old.remove();

    const q = data.data_quality;
    if (!q || data.season_done) return;

    const played = data.played_matchdays || 0;
    const parts = [];
    let tone = "info";

    if (played <= 1) {
        parts.push(t("seasonQuality.notStarted", { seasons: q.historical_seasons || 0 }));
    } else if (played <= 8) {
        parts.push(t("seasonQuality.early"));
    }

    if (q.teams_promoted > 0) {
        parts.push(q.teams_promoted === 1
            ? t("seasonQuality.promotedOne")
            : t("seasonQuality.promotedMany", { count: q.teams_promoted }));
    }

    // Vorsaison-Daten fehlen: Der Aufsteiger-Status ist dann nicht
    // feststellbar. Lieber ehrlich benennen als falsche Badges zeigen.
    if (q.previous_season_available === false && q.teams_without_history > 0) {
        parts.push(t("seasonQuality.noHistory", { count: q.teams_without_history }));
    }

    if (q.teams_neutral > 0) {
        tone = "warn";
        parts.push(t("seasonQuality.neutral", {
            neutral: q.teams_neutral,
            total: q.teams_total,
        }));
    }

    if (!parts.length) return;

    const hint = make("div", `season-quality-hint tone-${tone}`);
    hint.id = "season-quality-hint";
    hint.appendChild(make("span", "season-quality-icon", tone === "warn" ? "\u26A0" : "\u2139"));

    const body = make("div", "season-quality-body");
    parts.forEach(text => body.appendChild(make("div", "season-quality-text", text)));

    if (q.avg_confidence !== undefined) {
        const meta = make("div", "season-quality-meta");
        meta.textContent = t("seasonQuality.meta", {
            withHistory: q.teams_with_history,
            total: q.teams_total,
            confidence: Math.round((q.avg_confidence || 0) * 100),
        });
        body.appendChild(meta);
    }

    hint.appendChild(body);
    seasonSimTable.parentNode.insertBefore(hint, seasonSimTable);
}

/**
 * Kleines Kennzeichen fuer Teams, deren Prognose auf duenner Basis steht.
 *
 * Etablierte Teams mit Historie bekommen keins - dort ist die Datenlage
 * der Normalfall und braucht keinen Kommentar. Nur Abweichungen davon
 * werden markiert, mit erklaerendem Tooltip.
 */
function confidenceMarker(entry) {
    const level = entry.fallback_level;

    // Aufsteiger-Kennzeichen NUR bei belegtem Aufstieg (Abgleich mit der
    // Teilnehmerliste der Vorsaison). "Keine Historie gefunden" ist ein
    // eigenes Merkmal und heißt nicht automatisch Aufsteiger.
    if (entry.is_promoted === true) {
        const badge = make("span", "season-team-badge level-3", t("seasonConfidence.promoted"));
        badge.title = entry.has_historical_data
            ? t("seasonConfidence.promotedHistory")
            : t("seasonConfidence.promotedEstimated");
        return badge;
    }

    if (level === undefined || level <= 1) return null;

    let label, title;

    if (level === 2) {
        label = t("seasonConfidence.new");
        title = t("seasonConfidence.newTitle");
    } else {
        label = t("seasonConfidence.limited");
        title = t("seasonConfidence.limitedTitle");
    }

    const badge = make("span", `season-team-badge level-${level}`, label);
    badge.title = title;
    return badge;
}


function renderSeasonTable(data) {
    seasonSimTable.innerHTML = "";

    const zones = data.zones || {};
    const clSpots = zones.cl || 4;
    const elSpots = zones.el || 5;
    const relList = zones.relegation || [];
    const nTeams = data.entries.length;

    data.entries.forEach((entry, index) => {
        const row = make("div", "season-row");

        // Farbstreifen je Zone. WICHTIG: Wir nutzen den simulierten Rang
        // (entry.rank), nicht die alte API-Tabellenposition. So passen
        // Zone, angezeigte Nummer und Reihenfolge immer zusammen.
        let zoneClass = "";
        const pos = entry.rank;
        if (pos && pos <= clSpots) zoneClass = "zone-cl";
        else if (pos && pos <= elSpots) zoneClass = "zone-el";
        else if (relList.includes(pos)) zoneClass = "zone-rel";
        if (zoneClass) row.classList.add(zoneClass);

        // Linke Seite: Platz, Wappen, Name
        const left = make("div", "season-row-left");
        const posEl = make("div", "season-row-pos", String(entry.rank || index + 1));
        left.appendChild(posEl);

        if (entry.crest) {
            const img = make("img", "season-crest");
            img.src = entry.crest;
            img.alt = "";
            img.loading = "lazy";
            img.onerror = () => { img.style.visibility = "hidden"; };
            left.appendChild(img);
        }

        const nameWrap = make("div");

        const nameRow = make("div", "season-team-name-row");
        nameRow.appendChild(make("div", "season-team-name", entry.team_name));

        // Teams ohne belastbare Datengrundlage kennzeichnen. Ein Aufsteiger
        // oder ein Team auf Neutralwert soll nicht so aussehen, als waere
        // seine Platzierung genauso gut belegt wie die der anderen.
        const marker = confidenceMarker(entry);
        if (marker) nameRow.appendChild(marker);

        nameWrap.appendChild(nameRow);

        // Kernaussage der Prognosetabelle sind die ERWARTETEN Endpunkte.
        // Der aktuelle Stand wird nur gezeigt, wenn schon gespielt wurde -
        // "0 Pkt" vor dem ersten Spieltag ist zwar rechnerisch korrekt,
        // fuehrt aber in einer Abschlussprognose in die Irre.
        const sub = [];
        if (entry.expected_points !== undefined && entry.expected_points !== null) {
            sub.push(t("seasonTable.expectedPoints", { points: entry.expected_points }));
        }
        if (entry.current_played) {
            sub.push(t("seasonTable.currentPoints", {
                points: entry.current_points,
                played: entry.current_played,
            }));
        }
        if (entry.games_remaining) sub.push(t("seasonTable.gamesRemaining", { count: entry.games_remaining }));
        nameWrap.appendChild(make("div", "season-team-sub", sub.join(" · ")));

        left.appendChild(nameWrap);
        row.appendChild(left);

        // Rechte Seite: Wahrscheinlichkeiten
        const right = make("div", "season-row-right");

        const pcts = [
            { label: t("seasonTable.champion"), pct: entry.champion_pct, cls: "pct-champion" },
            { label: "CL",        pct: entry.cl_pct,          cls: "pct-cl" },
            { label: t("seasonTable.relegation"), pct: entry.relegation_pct, cls: "pct-rel" },
        ];

        pcts.forEach(({ label, pct, cls }) => {
            if (pct === null || pct === undefined) return;
            if (pct < 0.5 && label === t("seasonTable.champion") && entry.rank > 5) return;

            const chip = make("div", `pct-chip ${cls}`);
            chip.appendChild(make("span", "pct-chip-label", label));
            chip.appendChild(make("span", "pct-chip-value", `${pct} %`));
            right.appendChild(chip);
        });

        row.appendChild(right);
        seasonSimTable.appendChild(row);
    });
}


/* ---------- CHAMPIONS-LEAGUE-LIGASIMULATION ---------- */
/*
 * Bewusst eigene Funktionen und eigene DOM-IDs statt Mitbenutzung der
 * Domestic-Saisonsimulation: die Ligaphase hat eigene Zonen (1-8 / 9-24 /
 * ab 25) und ein eigenes Ergebnisformat. Die vorhandenen CSS-Klassen
 * (season-table, season-row, zone-*, pct-chip) werden dagegen
 * unveraendert wiederverwendet - kein neues Styling.
 */

function initClSeasonSim() {
    state.clSeasonSim = null;

    clSeasonSimLabel.textContent = `Champions League ${state.seasonLabel}`;
    clSeasonSimTable.innerHTML = "";

    hide(clSeasonSimEmpty);
    show(clSeasonSimControls);
    hide(clSeasonSimResult);
}


clSeasonSimBtn.addEventListener("click", runClSeasonSim);
clSeasonSimRerun.addEventListener("click", runClSeasonSim);


async function runClSeasonSim() {
    const sims = parseInt(el("cl-season-simulations").value, 10) || 10000;

    clSeasonSimBtn.disabled = true;
    clSeasonSimBtn.textContent = t("clSimulation.inProgress");
    hide(clSeasonSimResult);
    setStatus(t("clSimulation.running", { count: sims.toLocaleString(activeIntlLocale()) }));

    const url = withExplicitSeason(`/api/cl-season-sim?simulations=${sims}`);

    try {
        const data = await fetchJson(url);

        // Noch nicht ausgelost ist ein normaler Zustand, kein Fehler.
        if (data.empty_state) {
            state.clSeasonSim = null;
            hide(clSeasonSimControls);
            hide(clSeasonSimResult);
            clSeasonSimEmpty.querySelector("h2").textContent = t("clSimulation.emptyHeading");
            clSeasonSimEmpty.querySelector("p").textContent = activeLocale === "de" && data.empty_state_message
                ? data.empty_state_message
                : t("clSimulation.emptyHint");
            show(clSeasonSimEmpty);
            setStatus(t("clSimulation.emptyHeading"));
            return;
        }

        state.clSeasonSim = data;
        renderClSeasonSim(data);
        switchTab("cl-season");
        setStatus(t("clSimulation.ready"));

    } catch (error) {
        setStatus(error.message, true);
    } finally {
        clSeasonSimBtn.disabled = false;
        clSeasonSimBtn.textContent = t("clSimulation.run");
    }
}


function renderClSeasonSim(data) {
    const season = data.season;
    const label = season ? `${season}/${String(season + 1).slice(2)}` : "";

    clSeasonSimTitle.textContent = `${data.competition} ${label} · ${t("clSimulation.stage")}`;

    const favorite = data.entries && data.entries[0];
    if (favorite) {
        clSeasonSimFavorite.textContent = favorite.team_name;
        clSeasonSimFavPct.textContent = t("clSimulation.topSeed", { percent: favorite.top_seed_pct });
    }

    const parts = [t("clSimulation.infoRuns", { simulations: data.simulations.toLocaleString(activeIntlLocale()) })];

    if (data.mode === "full_resimulation") {
        parts.push(t("clSimulation.resimulatedFixtures", { count: data.fixtures_simulated }));
    } else {
        parts.push(t("clSimulation.remainingFixtures", { count: data.fixtures_simulated }));
        parts.push(t("clSimulation.fixedResults", { count: data.fixtures_fixed }));
    }

    parts.push(t("clSimulation.teams", { count: data.teams_total }));
    clSeasonSimInfo.textContent = parts.join(" · ");

    renderClSeasonTable(data);
    hide(clSeasonSimEmpty);
    hide(clSeasonSimControls);
    show(clSeasonSimResult);
}


function renderClSeasonTable(data) {
    clSeasonSimTable.innerHTML = "";

    const zones = data.zones || {};
    const directLast = zones.direct_last || 8;
    const playoffLast = zones.playoff_last || 24;

    data.entries.forEach((entry, index) => {
        const row = make("div", "season-row");

        // Dieselbe Zonensemantik wie in der CL-Tabelle: 1-8 direkt ins
        // Achtelfinale, 9-24 Play-offs, ab 25 ausgeschieden.
        const pos = entry.rank || index + 1;
        if (pos <= directLast)       row.classList.add("zone-cl");
        else if (pos <= playoffLast) row.classList.add("zone-el");
        else                         row.classList.add("zone-rel");

        const left = make("div", "season-row-left");
        left.appendChild(make("div", "season-row-pos", String(pos)));

        if (entry.crest) {
            const img = make("img", "season-crest");
            img.src = entry.crest;
            img.alt = "";
            img.loading = "lazy";
            img.onerror = () => { img.style.visibility = "hidden"; };
            left.appendChild(img);
        }

        const nameWrap = make("div");
        const nameRow = make("div", "season-team-name-row");
        nameRow.appendChild(make("div", "season-team-name", entry.team_name));

        const marker = clResolutionMarker(entry);
        if (marker) nameRow.appendChild(marker);

        nameWrap.appendChild(nameRow);

        const sub = [t("clSimulation.expectedPoints", { points: entry.expected_points })];
        if (entry.current_played) {
            sub.push(t("clSimulation.currentPoints", {
                points: entry.current_points,
                played: entry.current_played,
            }));
        }
        if (entry.games_remaining) {
            sub.push(t("clSimulation.gamesRemaining", { count: entry.games_remaining }));
        }
        nameWrap.appendChild(make("div", "season-team-sub", sub.join(" · ")));

        left.appendChild(nameWrap);
        row.appendChild(left);

        const right = make("div", "season-row-right");

        [
            { label: t("clSimulation.roundOf16"), pct: entry.direct_pct, cls: "pct-cl" },
            { label: t("clSimulation.playoffs"), pct: entry.playoff_pct, cls: "pct-champion" },
            { label: t("clSimulation.eliminated"), pct: entry.eliminated_pct, cls: "pct-rel" },
        ].forEach(({ label, pct, cls }) => {
            if (pct === null || pct === undefined) return;

            const chip = make("div", `pct-chip ${cls}`);
            chip.appendChild(make("span", "pct-chip-label", label));
            chip.appendChild(make("span", "pct-chip-value", `${pct} %`));
            right.appendChild(chip);
        });

        row.appendChild(right);
        clSeasonSimTable.appendChild(row);
    });
}


/**
 * Kennzeichnet Teams, deren Staerke nicht aus einer Top-5-Liga-Historie
 * stammt. Analog zu confidenceMarker() bei der Domestic-Simulation:
 * nur Abweichungen vom Normalfall werden markiert.
 */
function clResolutionMarker(entry) {
    if (entry.resolution === "cl_current_season") {
        const badge = make("span", "season-team-badge level-2", t("clSimulation.currentData"));
        badge.title = t("clSimulation.currentDataTitle");
        return badge;
    }

    if (entry.resolution === "neutral") {
        const badge = make("span", "season-team-badge level-4", t("clSimulation.limitedData"));
        badge.title = t("clSimulation.limitedDataTitle");
        return badge;
    }

    return null;
}


/* ---------- 14b. TRANSFER-VERGLEICH ---------- */
/*
 * Liga-zu-Liga-Transfervergleich:
 *     Quelliga A -> Zielliga   gegen   Quelliga B -> Zielliga
 *
 * Alle Funktionen und DOM-IDs tragen das Praefix "tc" bzw.
 * "transfer-compare-", damit nichts Bestehendes beruehrt wird.
 */

// Standard-Ligen beim ersten Oeffnen (Option A+: nur diese werden sofort geladen).
const TC_DEFAULT_LEAGUES = { a: "bl1", b: "pd", target: "pl" };

// Frontend-Caches (SC-Freiburg-Prinzip: einmal laden, immer wiederverwenden).
let tcLeaguesCache = null;          // Liste aller Transfer-Ligen (einmalig)
let tcLeaguesInflight = null;       // laufendes Promise waehrend des Ladens

const tcSeasonsCache = {};          // { ligaCode: [saisonJahre] }
const tcSeasonsInflight = {};       // { ligaCode: laufendes Promise }

// Schuetzt gegen Race Conditions: nur die zuletzt gestartete
// Saison-Berechnung darf das Dropdown noch aktualisieren.
let tcSeasonRequestVersion = 0;

// Sortierkriterium fuer die Spielerlisten (rein im Frontend, kein Request).
let tcSortCriterion = "rating";

// Zuletzt erfolgreich geladenes Ergebnis, damit ein Sortierwechsel
// ohne neuen Request nur neu gerendert werden kann.
let tcLastResult = null;

const TC_METRIC_LABELS = {
    minutes: () => t("transfer.metric.minutes"),
    goals: () => t("transfer.metric.goals"),
    assists: () => t("transfer.metric.assists"),
    scorer_points: () => t("transfer.metric.scorerPoints"),
    rating: () => t("transfer.metric.rating"),
};

let tcControlsReady = false;
let tcRunning = false;

function tcEl(id) { return document.getElementById(id); }

function tcSetStatus(text, isError = false) {
    const box = tcEl("transfer-compare-status");
    if (!box) return;
    box.textContent = text;
    box.classList.toggle("error", isError);
}

function tcFillSelect(select, options, selectedValue) {
    select.innerHTML = "";
    options.forEach(option => {
        const node = document.createElement("option");
        node.value = option.value;
        node.textContent = option.label;
        if (String(option.value) === String(selectedValue)) node.selected = true;
        select.appendChild(node);
    });
}

async function tcFetchLeagues() {
    // Cache-first: einmal geladen, nie wieder angefragt.
    if (tcLeaguesCache) return tcLeaguesCache;
    if (tcLeaguesInflight) return tcLeaguesInflight;

    tcLeaguesInflight = fetchJson("/api/transfer-leagues")
        .then(list => {
            tcLeaguesCache = list;
            return list;
        })
        .finally(() => {
            tcLeaguesInflight = null;
        });

    return tcLeaguesInflight;
}

async function tcFetchSeasonsForLeague(code) {
    // 1. Frontend-Cache
    if (tcSeasonsCache[code]) return tcSeasonsCache[code];

    // 2. Inflight-Deduplication: laeuft bereits ein Request fuer dieselbe Liga?
    if (tcSeasonsInflight[code]) return tcSeasonsInflight[code];

    // 3. Erst jetzt: Backend fragen (das seinerseits disk-cached vor API-Sports prueft)
    const promise = fetchJson(`/api/transfer-seasons?league=${encodeURIComponent(code)}`)
        .then(data => {
            const seasons = Array.isArray(data.seasons) ? data.seasons : [];
            tcSeasonsCache[code] = seasons;
            return seasons;
        })
        .finally(() => {
            delete tcSeasonsInflight[code];
        });

    tcSeasonsInflight[code] = promise;
    return promise;
}

function tcIntersectSeasons(listOfLists) {
    if (!listOfLists.length) return [];
    return listOfLists.reduce((acc, list) => {
        const set = new Set(list);
        return acc.filter(year => set.has(year));
    });
}

async function tcUpdateSeasonDropdown() {
    const fromA = tcEl("tc-from-a").value;
    const fromB = tcEl("tc-from-b").value;
    const target = tcEl("tc-target").value;
    const seasonSelect = tcEl("tc-season");

    // Race-Condition-Schutz: nur die zuletzt gestartete Anfrage darf das
    // Dropdown noch aktualisieren.
    const myVersion = ++tcSeasonRequestVersion;

    const previousValue = seasonSelect.value ? Number(seasonSelect.value) : null;

    // Ruhige UI: Dropdown kurz deaktivieren, dezenter Hinweis, kein Flackern.
    seasonSelect.disabled = true;
    tcSetStatus(t("transfer.seasonsLoading"));

    try {
        const [seasonsA, seasonsB, seasonsTarget] = await Promise.all([
            tcFetchSeasonsForLeague(fromA),
            tcFetchSeasonsForLeague(fromB),
            tcFetchSeasonsForLeague(target),
        ]);

        // Veraltete Antwort: waehrenddessen wurde die Auswahl schon wieder geaendert.
        if (myVersion !== tcSeasonRequestVersion) return;

        const common = tcIntersectSeasons([seasonsA, seasonsB, seasonsTarget]);

        if (!common.length) {
            seasonSelect.innerHTML = "";
            seasonSelect.disabled = true;
            tcSetStatus(t("transfer.noCommonSeason"), true);
            tcEl("transfer-compare-btn").disabled = true;
            return;
        }

        const options = common.map(year => ({
            value: year,
            label: `${year} \u2192 ${year + 1}`,
        }));

        // Bisherige Auswahl beibehalten, falls weiterhin gueltig.
        // Sonst die aktuellste verfuegbare Saison waehlen.
        const selected = (previousValue !== null && common.includes(previousValue))
            ? previousValue
            : common[0];

        tcFillSelect(seasonSelect, options, selected);
        seasonSelect.disabled = false;
        tcValidateSelection();
    } catch (error) {
        if (myVersion !== tcSeasonRequestVersion) return;
        tcSetStatus(t("transfer.seasonsUnavailable", { error: error.message || t("error.genericHeading") }), true);
        seasonSelect.disabled = false;
    }
}

async function tcInitControls() {
    if (tcControlsReady) return;
    tcControlsReady = true;

    tcSetStatus(t("transfer.leaguesLoading"));

    let leagues;
    try {
        leagues = await tcFetchLeagues();
    } catch (error) {
        tcSetStatus(t("transfer.leaguesUnavailable", { error: error.message || t("error.genericHeading") }), true);
        return;
    }

    const leagueOptions = leagues.map(l => ({ value: l.code, label: l.name }));

    tcFillSelect(tcEl("tc-from-a"), leagueOptions, TC_DEFAULT_LEAGUES.a);
    tcFillSelect(tcEl("tc-from-b"), leagueOptions, TC_DEFAULT_LEAGUES.b);
    tcFillSelect(tcEl("tc-target"), leagueOptions, TC_DEFAULT_LEAGUES.target);

    // Liga-Wechsel: Validierung sofort, Saison-Schnittmenge danach neu berechnen.
    ["tc-from-a", "tc-from-b", "tc-target"].forEach(id => {
        tcEl(id).addEventListener("change", () => {
            tcValidateSelection();
            tcUpdateSeasonDropdown();
        });
    });

    tcEl("tc-season").addEventListener("change", tcValidateSelection);
    tcEl("tc-sort").addEventListener("change", () => {
        tcSortCriterion = tcEl("tc-sort").value;
        // Sortierwechsel ist rein visuell: kein neuer Request, nur neu rendern.
        if (tcLastResult) tcRenderResult(tcLastResult);
    });

    tcEl("transfer-compare-btn").addEventListener("click", tcRunComparison);

    // Option A+: nur die Standard-Ligen sofort laden, alle anderen erst bei Auswahl.
    await tcUpdateSeasonDropdown();

    tcValidateSelection();
}

function tcValidateSelection() {
    const fromA = tcEl("tc-from-a").value;
    const fromB = tcEl("tc-from-b").value;
    const target = tcEl("tc-target").value;
    const button = tcEl("transfer-compare-btn");

    let problem = null;
    if (fromA === fromB) {
        problem = t("transfer.sourcesMustDiffer");
    } else if (target === fromA || target === fromB) {
        problem = t("transfer.targetMustDiffer");
    }

    button.disabled = Boolean(problem) || tcRunning;
    tcSetStatus(problem || t("status.ready"), Boolean(problem));
    return !problem;
}

async function tcRunComparison() {
    if (tcRunning || !tcValidateSelection()) return;

    const fromA = tcEl("tc-from-a").value;
    const fromB = tcEl("tc-from-b").value;
    const target = tcEl("tc-target").value;
    const season = tcEl("tc-season").value;

    const button = tcEl("transfer-compare-btn");
    tcRunning = true;
    button.disabled = true;
    button.textContent = t("transfer.analysisRunning");
    tcSetStatus(t("transfer.evaluating"));

    try {
        const url = `/api/transfer-compare?from_a=${fromA}&from_b=${fromB}&to=${target}&season=${season}`;
        const data = await fetchJson(url);
        tcLastResult = data;
        tcRenderResult(data);
        tcSetStatus(t("transfer.ready"));
    } catch (error) {
        const msg = error.message || t("error.genericRequestFailed");
        tcSetStatus("\u26a0 " + msg, true);
        tcLastResult = null;
        hide(el("transfer-compare-sort-row"));
        transferResult.innerHTML = "";
        hide(transferResult);
        show(transferEmpty);
        transferEmpty.innerHTML = `<h2>${t("transfer.unavailable")}</h2><p>${msg}</p>`;
    } finally {
        tcRunning = false;
        button.disabled = false;
        button.textContent = t("transfer.run");
        tcValidateSelection();
    }
}

function tcFormatValue(value, metric) {
    if (value === null || value === undefined) return "\u2013";
    if (metric === "rating") return Number(value).toFixed(2);
    return String(value);
}

function tcRenderResult(data) {
    hide(transferEmpty);

    // Sortier-Dropdown einblenden und mit dem aktuellen Kriterium synchron halten.
    const sortRow = el("transfer-compare-sort-row");
    show(sortRow);
    const sortSelect = tcEl("tc-sort");
    if (sortSelect.value !== tcSortCriterion) sortSelect.value = tcSortCriterion;
    transferResult.innerHTML = "";
    show(transferResult);

    const query = data.query || {};

    // Kopf: die Frage des Nutzers sichtbar wiederholen
    const head = make("div", "transfer-compare-result-head");
    head.appendChild(make("p", "eyebrow", t("transfer.yourAnalysis")));
    head.appendChild(make("h2", "transfer-compare-title",
        `${query.source_a_label} vs. ${query.source_b_label}`));
    head.appendChild(make("p", "transfer-compare-subtitle",
        t("transfer.resultSubtitle", { league: query.target_label })));
    head.appendChild(make("p", "transfer-compare-season",
        t("transfer.resultSeason", {
            season: query.season_label,
            minutes: query.minimum_minutes,
        })));
    transferResult.appendChild(head);

    // Neutrale Hinweise
    if (activeLocale === "de") {
        (data.warnings || []).forEach(text => {
            transferResult.appendChild(make("p", "transfer-compare-warning", text));
        });
    }

    // Zwei Gruppen-Karten mit VS-Trenner
    const duel = make("div", "transfer-compare-duel");
    duel.appendChild(tcBuildGroupCard(data.group_a, data.comparison, "a", query));
    duel.appendChild(make("div", "transfer-compare-vs", "VS"));
    duel.appendChild(tcBuildGroupCard(data.group_b, data.comparison, "b", query));
    transferResult.appendChild(duel);

    // Aufklappbare Spielerlisten
    transferResult.appendChild(tcBuildPlayerDetails(data.group_a, query));
    transferResult.appendChild(tcBuildPlayerDetails(data.group_b, query));
}

function tcBuildGroupCard(group, comparison, side, query) {
    const card = make("div", "transfer-compare-card");

    card.appendChild(make("h3", "transfer-compare-card-title", group.league_label));
    card.appendChild(make("p", "transfer-compare-card-target",
        `\u2192 ${query.target_label}`));

    const sample = group.sample;
    const sampleBox = make("div", "transfer-compare-sample");
    sampleBox.appendChild(make("div", null,
        t("transfer.transfersFound", { count: sample.transfers_total })));
    sampleBox.appendChild(make("div", null,
        t("transfer.qualifiedPlayers", {
            count: sample.qualified,
            minutes: query.minimum_minutes,
        })));
    sampleBox.appendChild(make("div", null,
        t("transfer.lowMinutesPlayers", {
            count: sample.low_minutes,
            minutes: query.minimum_minutes,
        })));
    if (sample.missing_data > 0) {
        sampleBox.appendChild(make("div", null,
            t("transfer.missingDataPlayers", { count: sample.missing_data })));
    }
    card.appendChild(sampleBox);

    const metrics = make("div", "transfer-compare-metrics");
    Object.keys(TC_METRIC_LABELS).forEach(metric => {
        const row = make("div", "transfer-compare-metric-row");
        if (comparison[metric] === side) row.classList.add("transfer-compare-better");

        row.appendChild(make("span", "transfer-compare-metric-label",
            TC_METRIC_LABELS[metric]()));
        row.appendChild(make("span", "transfer-compare-metric-value",
            tcFormatValue(group.averages[metric], metric)));
        metrics.appendChild(row);
    });
    card.appendChild(metrics);

    return card;
}

function tcBuildPlayerDetails(group, query) {
    const details = document.createElement("details");
    details.className = "transfer-compare-details";

    const summary = document.createElement("summary");
    summary.className = "transfer-compare-details-summary";
    summary.textContent = t("transfer.showLeaguePlayers", { league: group.league_label });
    details.appendChild(summary);

    const players = group.players || {};

    const addList = (title, list, extraClass) => {
        if (!list || !list.length) return;
        details.appendChild(make("h4", "transfer-compare-list-title", title));
        list.forEach(player => {
            details.appendChild(tcBuildPlayerRow(player, extraClass));
        });
    };

    addList(t("transfer.qualified"), tcSortPlayers(players.qualified, tcSortCriterion), "");
    addList(t("transfer.lowMinutes"), tcSortPlayers(players.low_minutes, tcSortCriterion), "transfer-compare-player-low");
    addList(t("transfer.missingData"), players.missing_data, "transfer-compare-player-missing");

    if (!(players.qualified || []).length &&
        !(players.low_minutes || []).length &&
        !(players.missing_data || []).length) {
        details.appendChild(make("p", "transfer-compare-list-title",
            t("transfer.noMatchingTransfers")));
    }

    return details;
}

/**
 * Robuster Parser fuer Ablösesummen-Rohtext von API-Sports.
 * Bekannte Formate: "€45M", "€45.5M", "€750K", "45M", "750K",
 *                    "Free", "Loan", "N/A", leer, null, unbekannt.
 * Rueckgabe: Zahl in Basiswaehrungseinheiten, oder null wenn nicht
 * interpretierbar (Free/Loan/N/A/unbekannt/leer/null).
 * Wirft niemals einen Fehler und liefert niemals NaN.
 */
function tcParseFee(rawText) {
    if (rawText === null || rawText === undefined) return null;
    const text = String(rawText).trim();
    if (!text) return null;

    const lower = text.toLowerCase();
    if (lower === "free" || lower === "loan" || lower === "n/a" || lower === "unbekannt") {
        return null;
    }

    // Waehrungszeichen entfernen, Komma als Dezimaltrennzeichen zulassen.
    const cleaned = text.replace(/[€£$]/g, "").replace(",", ".").trim();
    const match = cleaned.match(/^(-?\d+(?:\.\d+)?)\s*([MmKk]?)$/);
    if (!match) return null;

    const value = parseFloat(match[1]);
    if (!Number.isFinite(value)) return null;

    const unit = match[2].toLowerCase();
    if (unit === "m") return value * 1_000_000;
    if (unit === "k") return value * 1_000;
    return value;
}

/**
 * Liefert den Sortierwert eines Spielers fuer ein Kriterium.
 * null bedeutet "unbekannt" -> landet am Ende der Sortierung.
 */
function tcSortValue(player, criterion) {
    switch (criterion) {
        case "rating":
            return (player.rating === null || player.rating === undefined)
                ? null : Number(player.rating);
        case "fee":
            return tcParseFee(player.transfer_type);
        case "goals":
            return (player.goals === null || player.goals === undefined)
                ? null : Number(player.goals);
        case "assists":
            return (player.assists === null || player.assists === undefined)
                ? null : Number(player.assists);
        case "minutes":
            return (player.minutes === null || player.minutes === undefined)
                ? null : Number(player.minutes);
        case "name":
            return (player.player_name || "").toLowerCase();
        default:
            return null;
    }
}

/**
 * Sortiert eine Spielerliste nach Kriterium, ohne das Original zu mutieren.
 * Numerische Kriterien: absteigend, fehlende Werte immer am Ende.
 * Name: aufsteigend (A-Z), fehlende Namen am Ende.
 * Kein Spieler verschwindet - reine Umsortierung derselben Liste.
 */
function tcSortPlayers(players, criterion) {
    const list = (players || []).slice();
    const isName = criterion === "name";

    return list.sort((a, b) => {
        const va = tcSortValue(a, criterion);
        const vb = tcSortValue(b, criterion);

        const aMissing = (va === null || va === undefined || (typeof va === "number" && Number.isNaN(va)));
        const bMissing = (vb === null || vb === undefined || (typeof vb === "number" && Number.isNaN(vb)));

        if (aMissing && bMissing) return 0;
        if (aMissing) return 1;
        if (bMissing) return -1;

        if (isName) return va < vb ? -1 : (va > vb ? 1 : 0);
        return vb - va; // absteigend
    });
}

function tcBuildPlayerRow(player, extraClass) {
    const row = make("div", `transfer-compare-player ${extraClass || ""}`.trim());

    if (player.player_photo) {
        row.appendChild(crest(player.player_photo, "transfer-compare-player-photo"));
    } else {
        row.appendChild(make("span", "transfer-compare-player-photo"));
    }

    const info = make("div", "transfer-compare-player-info");
    info.appendChild(make("div", "transfer-compare-player-name", player.player_name || t("player.unknown")));

    const moveText = `${player.from_team_name || "?"} \u2192 ${player.to_team_name || "?"}`
        + ` \u00b7 ${player.transfer_type || t("player.unknown")}`
        + (player.position ? ` \u00b7 ${player.position}` : "");
    info.appendChild(make("div", "transfer-compare-player-move", moveText));
    row.appendChild(info);

    const stats = make("div", "transfer-compare-player-stats");
    if (player.data_available) {
        const parts = [
            t("player.minutesShort", { count: player.minutes ?? 0 }),
            t("transfer.goalsValue", { count: player.goals ?? 0 }),
            player.assists !== null && player.assists !== undefined
                ? t("transfer.assistsValue", { count: player.assists }) : t("transfer.assistsMissing"),
            player.rating !== null && player.rating !== undefined
                ? t("transfer.ratingValue", { value: Number(player.rating).toFixed(2) }) : t("transfer.ratingMissing"),
        ];
        stats.textContent = parts.join(" \u00b7 ");
    } else {
        stats.textContent = t("transfer.noData");
    }
    row.appendChild(stats);

    return row;
}


/* ---------- PWA ---------- */

if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
        navigator.serviceWorker
            .register("/sw.js")
            .catch(err => console.warn("SW Registrierung fehlgeschlagen:", err));
    });
}

/* ============================================================
   16. SPIELERVERGLEICH

   Aufbau:
     16a  Zustand und Konstanten
     16b  Suche mit Entprellung und Schutz vor veralteten Antworten
     16c  Trefferliste inklusive Tastaturbedienung
     16d  Auswahl und Spielerkarten
     16e  Vergleich anfordern
     16f  Radar (SVG)
     16g  Detailvergleich
     16h  Zusammenfassung
   ============================================================ */

/* ---------- 16a. Zustand ---------- */

const pcState = {
    seasons: [],
    minQueryLength: 3,
    ready: false,

    // Laufende Nummer JEDES Vergleichs.
    //
    // Die Suche hatte diesen Schutz schon (slotState.requestId), der
    // Vergleich nicht. Wer zweimal kurz hintereinander vergleicht oder
    // waehrend einer laufenden Anfrage die Saison wechselt, konnte die
    // aeltere Antwort als Ergebnis sehen - mit der Saison, die zum
    // Zeitpunkt des ALTEN Requests galt. Genau dieses Bild wurde
    // gemeldet: Auswahl 2025/26, Ergebnis 2026/27.
    comparisonId: 0,

    // Der laufende Vergleich, damit er abgebrochen werden kann.
    comparisonAbort: null,

    // Aktive Unteransicht innerhalb des Spielerbereichs: "radar" oder
    // "scatter". Steuert nur, welcher Container sichtbar ist - alle
    // anderen Felder unten gelten fuer BEIDE Ansichten gemeinsam.
    mode: "radar",

    // Aktuell gewaehlte Saison, geteilt zwischen Radar (Slot A als
    // fuehrend) und Plots. Wird beim Laden der Saisonliste gesetzt.
    season: null,

    // Gewaehlte Positionsgruppe. Leerer String = alle Positionen.
    // Wird von Radar UND Plots gemeinsam genutzt (Phase 3.2): ein Wechsel
    // in der einen Ansicht spiegelt sich sofort in der anderen.
    //
    // Standard ist bewusst "alle Positionen", nicht mehr "Mittelfeld" wie
    // noch in Phase 3.1. Grund: der Zustand ist jetzt geteilt, ein
    // einzelner Wert kann nicht gleichzeitig zwei verschiedene Standards
    // fuer Radar und Plots haben. Wer zuerst Plots oeffnet, soll dort
    // "Alle Positionen" sehen - das legt den gemeinsamen Standard fest.
    position: "",

    // Wettbewerbsumfang. Bestimmt, welche statistics-Bloecke der
    // API-Antwort zusammengefasst werden. Aendert NICHTS an der Suche,
    // deshalb bleibt die Spielerauswahl beim Wechsel erhalten.
    // Gilt nur fuer Radar; Plots hat kein Wettbewerbsumfang-Konzept,
    // weil der Pool ohnehin nur Ligadaten enthaelt (Stand Phase 3.2).
    scope: "club_all",

    // ---- Scatter-eigene Felder (Phase 3.2) ----
    scatter: {
        season: null,
        ready: false,
        axes: [],                 // Katalog aus der ersten Antwort, fuers Dropdown
        x: "goals_per90",
        y: "assists_per90",
        // Wettbewerbsumfang, eigene Auswahl je Ansicht. Bewusst NICHT mit
        // pcState.scope geteilt: im Radar vergleicht man zwei Spieler, im
        // Plot ordnet man eine ganze Liga ein - dort kann eine andere
        // Datenbasis sinnvoll sein, ohne den Radar umzustellen.
        scope: "club_all",
        leagues: ["bl1", "pl", "pd", "sa", "fl1"],
        minMinutes: 450,
        points: [],
        highlighted: new Set(),   // Spieler-IDs, die hervorgehoben sind
        searchTimer: null,
        requestId: 0,

        // hasPlot: wurde ueberhaupt schon einmal ein Plot erzeugt?
        // dirty:   wurden seitdem Filter geaendert, sodass die gezeigten
        //          Punkte nicht mehr zum Filterzustand passen?
        // Beides steuert Beschriftung und Zustand des Startbuttons.
        hasPlot: false,
        dirty: false,
        busy: false,
        openPointId: null,
    },

    // Je Slot: gewaehlter Spieler, laufende Suche, Trefferliste, Tastaturindex
    //
    // Bewusst weiterhin zwei benannte Slots statt einer Liste. Eine Umstellung
    // auf beliebig viele Spieler betrifft Farben, Legende, Radarflaechen,
    // Detailbalken und die Zusammenfassung gleichermassen und waere ein
    // eigener Umbau - siehe docs/player_comparison.md, Abschnitt 15.
    // PC_SLOTS existiert, damit neue Logik ueber die Slots iteriert statt
    // a und b hart zu adressieren.
    a: { player: null, season: null, results: [], activeIndex: -1, requestId: 0, timer: null },
    b: { player: null, season: null, results: [], activeIndex: -1, requestId: 0, timer: null },

    lastComparison: null,
};

const PC_SLOTS = ["a", "b"];

// Zwei feste Spielerfarben. Sie muessen sich klar unterscheiden und duerfen
// nicht mit den Zustandsfarben der App kollidieren.
const PC_COLOR_A = "#1eb7fb";   // Cyan, wie der App-Akzent
const PC_COLOR_B = "#f59e0b";   // Bernstein, deutlich davon getrennt

const PC_SEARCH_DELAY = 320;    // Millisekunden zwischen letztem Tastendruck und Request

/*
   Alle sichtbaren Texte des Spielervergleichs an einer Stelle.

   Alle Werte sind schlanke Adapter auf den gemeinsamen DE/EN-Katalog. Die
   bestehenden Aufrufer bleiben bewusst stabil, damit die Fachlogik des
   Vergleichs nicht mit der Präsentationsmigration vermischt wird.

   Der Fachbegriff "Perzentil" taucht bewusst nur in Erklaertexten auf,
   nie als Hauptbotschaft. Nutzer lesen "besser als 87 %", nicht "P87".
*/
const PC_TEXT = {
    positionHint: {
        Goalkeeper: () => t("player.positionHint.Goalkeeper"),
        Defender: () => t("player.positionHint.Defender"),
        Midfielder: () => t("player.positionHint.Midfielder"),
        Attacker: () => t("player.positionHint.Attacker"),
        free: () => t("player.positionHint.free"),
    },
    resetOnSwitch: () => t("player.resetOnSwitch"),

    // Wettbewerbsumfang. Die Texte spiegeln SCOPE_HINTS im Backend,
    // damit Oberflaeche und Dokumentation dasselbe sagen.
    scopeHint: {
        club_all: () => t("player.scopeHint.club_all"),
        league:   () => t("player.scopeHint.league"),
        cl:       () => t("player.scopeHint.cl"),
        euro:     () => t("player.scopeHint.euro"),
        world_cup: () => t("player.scopeHint.world_cup"),
        national: () => t("player.scopeHint.national"),
        all:      () => t("player.scopeHint.all"),
        big_games: () => t("player.scopeHint.big_games"),
    },
    // Fachlicher Normalzustand, kein Fehler: der Spieler hat in dieser
    // Saison schlicht nicht in diesem Wettbewerb gespielt.
    scopeNoData: (name, scopeLabel) =>
        t("player.scopeNoData", { name, scopeLabel }),
    scopeNoDataShort: () => t("player.scopeNoDataShort"),
    scopeNoDataBoth: (scopeLabel) =>
        t("player.scopeNoDataBoth", { scopeLabel }),
    scopeChanged: () => t("player.scopeChanged"),
    // Turnier fand im gewaehlten Saisonzyklus nicht statt. Ein normaler
    // fachlicher Zustand, deshalb nur ein Tooltip - keine Fehlermeldung.
    scopeUnavailable: () => t("player.scopeUnavailable"),

    // Plots
    scatterLoading: () => t("player.scatterLoading"),
    scatterError: () => t("player.scatterError"),
    scatterCreate: () => t("player.scatterCreate"),
    scatterUpdate: () => t("player.scatterUpdate"),
    scatterFiltersChanged: () => t("player.scatterFiltersChanged"),
    scatterReady: (count) => t("player.scatterReady", { count }),
    scatterManyPoints: (count) => t("player.scatterManyPoints", { count }),
    scatterNoMatch: (minutes) => t("player.scatterNoMatch", { minutes }),
    scatterPoolMissing: () => t("player.scatterPoolMissing"),
    scatterPoolPartial: (missing) => t("player.scatterPoolPartial", { missing }),
    scatterPoolOutdated: () => t("player.scatterPoolOutdated"),

    rankAvailable: (percentile) => t("player.rankAvailable", { percentile }),
    rankTop: (percentile) => t("player.rankTop", { percentile }),
    rankUnavailable: () => t("player.rankUnavailable"),
    rankShortMinutes: () => t("player.rankShortMinutes"),

    rawOnly: () => t("player.rawOnly"),

    rankExplain: (leagues, season, minutes) => t("player.rankExplain", { leagues, season, minutes }),
};

// Reihenfolge der Positionsnavigation. Leerer Wert = freier Vergleich.
const PC_POSITIONS = ["Midfielder", "Attacker", "Defender", "Goalkeeper", ""];

// Zwei Positionsnavigationen im DOM (Radar und Plots), beide muessen auf
// jeden Klick reagieren und synchron bleiben - siehe pcSetPosition().
const pcPositionNavs = Array.from(document.querySelectorAll(".pc-position-nav"));
const pcPositionNote = el("pc-position-note");
const pcScopeNav = document.querySelector(".pc-scope-nav");
const pcScopeNote = el("pc-scope-note");

const pcModeSelect = el("pc-mode-select");
const pcRadarView = el("pc-radar-view");
const pcScatterView = el("pc-scatter-view");

const pcSearchInputs = { a: el("pc-search-a"), b: el("pc-search-b") };
const pcResultBoxes  = { a: el("pc-results-a"), b: el("pc-results-b") };
const pcSelectedBoxes = { a: el("pc-selected-a"), b: el("pc-selected-b") };
const pcSeasonSelects = { a: el("pc-season-a"), b: el("pc-season-b") };
const pcCompareBtn = el("pc-compare-btn");
const pcSwapBtn = el("pc-swap-btn");
const pcStatus = el("pc-status");
const pcEmpty = el("pc-empty");
const pcResult = el("pc-result");


/* ---------- 16a2. Positionsnavigation ----------

   Die Positionsgruppe ist der erste Schritt des Ablaufs und ein echter
   Suchfilter. Sie legt fest:
     - welche Treffer in beiden Suchfeldern waehlbar sind
     - welches Radarprofil der spaetere Vergleich benutzt

   Gefiltert wird im Frontend, nicht ueber einen neuen API-Parameter.
   Begruendung: Die Suchantwort enthaelt die Position bereits je Treffer.
   Ein zusaetzlicher Parameter wuerde den Cache-Schluessel aufspalten und
   dieselbe Suche fuer jede Positionsgruppe erneut gegen API-Sports laufen
   lassen - fuenf Liga-Requests pro Gruppe statt einmal fuer alle.
   Das waere genau der Fehler, den das SC-Freiburg-Prinzip vermeiden soll.
------------------------------------------------------------------- */

/** Filtert eine Trefferliste auf die aktive Positionsgruppe. */
function pcFilterByPosition(results) {
    if (!pcState.position) return results || [];
    return (results || []).filter(p => p.position === pcState.position);
}

/** Setzt beide Slots und die Ergebnisansicht zurueck. */
function pcResetSelection() {
    PC_SLOTS.forEach(slot => {
        const slotState = pcState[slot];
        clearTimeout(slotState.timer);
        // Laufende Suchen entwerten, sonst poppt spaeter eine Liste der
        // alten Positionsgruppe auf.
        slotState.requestId++;
        pcClearSlot(slot);
    });

    pcState.lastComparison = null;
    pcResult.innerHTML = "";
    hide(pcResult);
    show(pcEmpty);
    pcUpdateReady();
}

/**
 * Wechselt die Positionsgruppe.
 *
 * Ein Wechsel verwirft eine bestehende Auswahl. Andernfalls koennte ein
 * Mittelfeld-Radar sichtbar bleiben, waehrend oben "Sturm" aktiv ist.
 */
function pcSetPosition(position, options) {
    const silent = options && options.silent;
    if (pcState.position === position && !silent) return;

    const hadSelection = PC_SLOTS.some(slot => pcState[slot].player);
    pcState.position = position;

    document.querySelectorAll(".pc-position-btn").forEach(button => {
        const active = button.dataset.position === position;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.tabIndex = active ? 0 : -1;
    });

    if (pcPositionNote) {
        const hint = PC_TEXT.positionHint[position] || PC_TEXT.positionHint.free;
        pcPositionNote.textContent = hint();
    }

    if (hadSelection && !silent) {
        pcResetSelection();
        pcStatus.textContent = PC_TEXT.resetOnSwitch();
    } else if (!silent) {
        pcResetSelection();
    }

    // Scatter ist von der Positionsauswahl genauso betroffen wie Radar.
    // Nur nachladen, wenn die Ansicht ueberhaupt schon initialisiert ist -
    // sonst laedt pcScatterInit() ohnehin gleich mit dem aktuellen Wert.
    if (!silent && pcState.scatter.ready) {
        pcScatterMarkDirty();
    }
}

// Beide Navigationen (Radar und Plots) bekommen dieselben Handler.
// pcSetPosition() aktualisiert ohnehin ALLE .pc-position-btn im DOM,
// unabhaengig davon, welche Navigation den Klick ausgeloest hat.
pcPositionNavs.forEach(nav => {
    nav.addEventListener("click", (event) => {
        const button = event.target.closest(".pc-position-btn");
        if (!button) return;
        pcSetPosition(button.dataset.position);
    });

    // Pfeiltasten innerhalb der Tablist, wie bei nativen Tabs erwartet.
    nav.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;

        const buttons = Array.from(nav.querySelectorAll(".pc-position-btn"));
        const current = buttons.findIndex(b => b.dataset.position === pcState.position);
        let next = current;

        if (event.key === "ArrowLeft")  next = (current - 1 + buttons.length) % buttons.length;
        if (event.key === "ArrowRight") next = (current + 1) % buttons.length;
        if (event.key === "Home")       next = 0;
        if (event.key === "End")        next = buttons.length - 1;

        event.preventDefault();
        pcSetPosition(buttons[next].dataset.position);
        buttons[next].focus();
    });
});


/* ---------- 16a3. Wettbewerbsumfang ----------

   Bestimmt, welche statistics-Bloecke der API-Antwort zusammengefasst
   werden: nur Liga, alle Vereinswettbewerbe, nur Nationalmannschaft
   oder alles.

   Wichtiger Unterschied zur Positionsauswahl: der Scope aendert NICHT,
   welche Spieler gefunden werden - nur wie ihre Zahlen berechnet werden.
   Deshalb bleibt eine bestehende Auswahl erhalten. Ein bereits sichtbares
   Ergebnis wird neu geladen, weil die Werte sich aendern.

   Kostet keinen zusaetzlichen API-Request: die Rohantwort mit allen
   Wettbewerben liegt bereits im Cache, sie wird nur anders aggregiert.
------------------------------------------------------------------- */

function pcSetScope(scope, options) {
    const silent = options && options.silent;
    if (pcState.scope === scope && !silent) return;

    // Ein laufender Vergleich gilt fuer den ALTEN Wettbewerbsumfang. Seine
    // Antwort darf nach dem Wechsel nicht mehr gezeichnet werden.
    if (!silent) pcInvalidateComparison();

    pcState.scope = scope;

    document.querySelectorAll(".pc-scope-btn").forEach(button => {
        const active = button.dataset.scope === scope;
        button.classList.toggle("active", active);
        button.setAttribute("aria-checked", active ? "true" : "false");
        button.tabIndex = active ? 0 : -1;
    });

    if (pcScopeNote) {
        const hint = PC_TEXT.scopeHint[scope];
        pcScopeNote.textContent = hint ? hint() : "";
    }

    // Der Zeitraumblock gehoert ausschliesslich zu Big Games (Block F1).
    bgSyncVisibility();

    // Die Bereitschaftsmeldung haengt seit F1.1 vom Modus ab (bei Big
    // Games entscheidet der gemeinsame Zeitraum, nicht die Slot-Saison).
    if (pcState.ready) pcUpdateReady();

    if (silent) return;

    // Beide Spieler bleiben gewaehlt. Nur ein bereits berechnetes Ergebnis
    // passt nicht mehr zur neuen Datenbasis und wird nachgezogen.
    if (pcState.lastComparison && pcState.a.player && pcState.b.player) {
        pcStatus.textContent = PC_TEXT.scopeChanged();
        pcRunComparison();
    }
}


/* ---------- 16d-bg. BIG GAMES (Block F1) ----------

   Big Games ist eine zusaetzliche DATENBASIS des Spielervergleichs, kein
   eigener Bereich und keine zweite Vergleichsoberflaeche. Wiederverwendet
   werden unveraendert: Spielerauswahl, Positionsfilter, Ergebnisrahmen,
   Statuszeile und der bestehende Vergleichsknopf.

   Zwei Dinge sind anders und nur deshalb existiert dieses Modul:

     1. ZEITRAUM statt einer Saison je Spieler. Intern ausschliesslich
        season_from/season_to - die Schnellauswahl rechnet nur darauf.

     2. EIGENE SUCHE. Die normale Suche durchsucht den lokal importierten
        Top-5-Pool. Fuer eine historische Auswertung ist das zu eng, weil
        ein Spieler laengst woanders spielen kann. Big Games sucht deshalb
        ueber /api/big-games-search direkt beim Anbieter.

        WICHTIG: Diese Suche befuellt KEINEN Pool. Die Perzentil- und
        Plot-Population bleibt exakt wie sie ist - ein hier gefundener
        Spieler taucht dadurch NICHT in den Top-5-Plots auf.

   Saemtliche Bewertung (Gegnerstaerke, Bedeutung, Zulassung, Score)
   passiert serverseitig. Dieses Modul rechnet bewusst NICHTS davon nach:
   es gibt hier keine Rangtabelle, keine Gewichtsformel und keinen
   Schwellenwert - nur Darstellung.
------------------------------------------------------------------- */

const bgPeriodBlock = el("bg-period-block");
const bgSeasonFrom  = el("bg-season-from");
const bgSeasonTo    = el("bg-season-to");
const bgPeriodNote  = el("bg-period-note");

const BG_SCOPE = "big_games";

const bgState = {
    // Vom Server gemeldete Saisons mit vorhandenen Vergleichsdaten.
    seasons: [],
    maxSpan: 5,
    loaded: false,
    from: null,
    to: null,
};

function bgIsActive() {
    return pcState.scope === BG_SCOPE;
}

/**
 * Schaltet zwischen den beiden Zeitmodellen um.
 *
 * Ausserhalb von Big Games waehlt jeder Spieler seine eigene Saison
 * (unveraendertes Verhalten). Bei Big Games gilt EIN gemeinsamer
 * Zeitraum fuer beide - die beiden Saisonfelder waeren dort nicht nur
 * ueberfluessig, sondern irrefuehrend: sie suggerieren eine Auswahl, die
 * der Vergleich gar nicht auswertet (bgRunComparison() schickt
 * ausschliesslich season_from/season_to).
 *
 * Die Felder werden nur versteckt, nie geleert oder umgebaut - beim
 * Verlassen von Big Games stehen sie unveraendert wieder da.
 */
function bgSyncVisibility() {
    const active = bgIsActive();

    if (bgPeriodBlock) {
        if (active) {
            show(bgPeriodBlock);
            bgEnsureLoaded();
        } else {
            hide(bgPeriodBlock);
        }
    }

    document.querySelectorAll(".pc-slot .pc-season-row").forEach(row => {
        if (active) hide(row);
        else show(row);
    });
}

/**
 * Holt einmalig, welche Saisons ueberhaupt auswertbar sind.
 *
 * Die Grenze kommt ausschliesslich vom Server (dort liegen die
 * historischen Vergleichsdaten). Das Frontend bietet dadurch gar nicht
 * erst Zeitraeume an, fuer die es keine Grundlage gibt, statt sie erst
 * nach dem Vergleich als leer zu melden.
 */
async function bgEnsureLoaded() {
    if (bgState.loaded) return;

    try {
        const response = await fetch("/api/big-games-seasons");
        const data = await response.json();

        if (!response.ok || !data.available || !(data.seasons || []).length) {
            bgState.loaded = true;
            if (bgPeriodNote) {
                bgPeriodNote.textContent = t("bigGames.noComparisonData");
            }
            return;
        }

        bgState.seasons = data.seasons;
        bgState.maxSpan = data.max_span || 5;
        bgState.loaded = true;

        const latest = data.latest_season;
        bgState.to = latest;
        bgState.from = latest;

        bgFillSelect(bgSeasonFrom, bgState.from);
        bgFillSelect(bgSeasonTo, bgState.to);
        bgUpdateNote();

    } catch (error) {
        bgState.loaded = true;
        if (bgPeriodNote) {
            bgPeriodNote.textContent = t("bigGames.periodUnavailable");
        }
    }
}

function bgFillSelect(select, selected) {
    if (!select) return;
    select.innerHTML = "";

    bgState.seasons.forEach(entry => {
        const option = make("option", "", entry.label);
        option.value = String(entry.season);
        if (entry.season === selected) option.selected = true;
        select.appendChild(option);
    });
}

/**
 * Haelt den Zeitraum gueltig: Von darf nicht hinter Bis liegen, und die
 * Spanne bleibt innerhalb der serverseitigen Obergrenze.
 */
function bgNormalizeRange(changed) {
    let from = Number(bgSeasonFrom && bgSeasonFrom.value);
    let to   = Number(bgSeasonTo && bgSeasonTo.value);

    if (!Number.isFinite(from) || !Number.isFinite(to)) return;

    if (from > to) {
        // Der gerade geaenderte Wert gewinnt, der andere zieht nach.
        if (changed === "from") to = from;
        else from = to;
    }

    if ((to - from + 1) > bgState.maxSpan) {
        if (changed === "from") to = from + bgState.maxSpan - 1;
        else from = to - bgState.maxSpan + 1;
    }

    bgState.from = from;
    bgState.to = to;

    if (bgSeasonFrom) bgSeasonFrom.value = String(from);
    if (bgSeasonTo) bgSeasonTo.value = String(to);

    bgUpdateNote();
}

function bgUpdateNote() {
    if (!bgPeriodNote) return;

    const span = (bgState.to - bgState.from) + 1;
    const provisional = bgState.seasons.some(
        s => s.provisional && s.season >= bgState.from && s.season <= bgState.to
    );

    let text = span === 1
        ? t("bigGames.period.oneSeason")
        : t("bigGames.period.multipleSeasons", { count: span });

    if (provisional) {
        text += ` ${t("bigGames.period.provisional")}`;
    }

    bgPeriodNote.textContent = text;
}

if (bgSeasonFrom) {
    bgSeasonFrom.addEventListener("change", () => bgNormalizeRange("from"));
}
if (bgSeasonTo) {
    bgSeasonTo.addEventListener("change", () => bgNormalizeRange("to"));
}


/* ---------- Big Games: Vergleich anfordern ---------- */

async function bgRunComparison() {
    const a = pcState.a.player;
    const b = pcState.b.player;
    if (!a) return;

    await bgEnsureLoaded();

    if (bgState.from === null || bgState.to === null) {
        pcStatus.textContent = t("bigGames.noComparisonData");
        return;
    }

    pcCompareBtn.disabled = true;
    pcStatus.textContent = t("bigGames.evaluating");

    try {
        const params = new URLSearchParams({
            a: String(a.player_id),
            season_from: String(bgState.from),
            season_to: String(bgState.to),
        });
        if (b) params.set("b", String(b.player_id));

        const response = await fetch(`/api/big-games-compare?${params.toString()}`);
        const data = await response.json();

        if (!response.ok) {
            pcStatus.textContent = visibleApiError(data, "error.genericRequestFailed");
            return;
        }

        pcState.lastComparison = null;   // anderes Ergebnismodell als der Normalvergleich
        bgRenderComparison(data);
        pcStatus.textContent = t("bigGames.evaluated");

    } catch (error) {
        pcStatus.textContent = t("bigGames.unavailable");
    } finally {
        pcCompareBtn.disabled = false;
    }
}


/* ---------- Big Games: Ergebnis aufbauen ----------

   Strikte Trennung, die sich durch die gesamte Darstellung zieht:

     ROHWERTE     tatsaechlich erzielt, unveraendert. Vier Tore sind vier
                  Tore - hier wird nie multipliziert.
     KONTEXT      wie stark waren Gegner und Anlaesse?
     BEWERTUNG    kontextgewichtet, IMMER als solche beschriftet.

   Deshalb steht der Big Game Score nie neben "Tore", sondern in einem
   eigenen, benannten Block.
------------------------------------------------------------------- */

function bgFormatNumber(value, digits) {
    if (value === null || value === undefined) return "–";
    return Number(value).toFixed(digits === undefined ? 0 : digits);
}

/** Eine Kachel mit grosser Zahl und Beschriftung - dieselbe Optik wie pd-core-tile. */
function bgBuildTile(value, label, extraClass) {
    const tile = make("div", "pd-core-tile" + (extraClass ? " " + extraClass : ""));
    tile.appendChild(make("div", "pd-core-value", value));
    tile.appendChild(make("div", "pd-core-label", label));
    return tile;
}

function bgBuildPlayerHeader(player) {
    const head = make("div", "bg-player-head");

    const avatar = make("div", "mc-pp-avatar bg-player-avatar");
    avatar.appendChild(make("span", "mc-pp-initials", mcInitials(player.name)));
    if (player.photo) {
        const photo = make("img", "mc-pp-photo");
        photo.src = player.photo;
        photo.alt = "";
        photo.loading = "lazy";
        photo.onerror = () => { photo.remove(); };
        avatar.appendChild(photo);
    }
    head.appendChild(avatar);

    const identity = make("div", "bg-player-identity");
    identity.appendChild(make("div", "bg-player-name", player.name || t("player.unknown")));

    const meta = [];
    if (player.position) {
        meta.push(translatedPosition(player.position, player.position));
    }
    meta.push(t("bigGames.matchCount", { count: player.match_count }));
    identity.appendChild(make("div", "bg-player-meta", meta.join(" · ")));

    head.appendChild(identity);
    return head;
}

/** Rohwerte - ausdruecklich unveraendert und ungewichtet. */
function bgBuildRawBlock(player) {
    const box = make("div", "bg-block");
    box.appendChild(make("p", "mc-lineup-label", t("bigGames.raw.title")));

    const grid = make("div", "pd-core-grid");
    grid.appendChild(bgBuildTile(String(player.summary.raw.matches), t("bigGames.raw.matches")));
    grid.appendChild(bgBuildTile(String(player.summary.raw.minutes), t("bigGames.raw.minutes")));

    // G+A ist eine eigene, transparente Produktionsdimension: Tore und
    // Vorlagen bleiben in den positionsgerechten Kacheln getrennt sichtbar,
    // waehrend diese Summe beide mit exakt derselben Einheit zaehlt.
    const goalAssists = player.summary.raw.goal_assists;
    if (goalAssists !== null && goalAssists !== undefined) {
        // Die katalogisierte Bezeichnung bleibt die rohe Dimension "G+A".
        grid.appendChild(bgBuildTile(String(goalAssists), t("bigGames.raw.goalAssists")));
    }

    (player.metrics || []).forEach(metric => {
        if (metric.key === "minutes" || metric.key === "matches") return;
        grid.appendChild(bgBuildTile(
            metric.value === null || metric.value === undefined ? "–" : String(metric.value),
            localizedBigGamesMetricLabel(metric)
        ));
    });

    box.appendChild(grid);
    return box;
}

/** Kontext und kontextgewichtete Bewertung - klar getrennt von den Rohwerten. */
function bgBuildContextBlock(player) {
    const summary = player.summary;
    const box = make("div", "bg-block");
    box.appendChild(make("p", "mc-lineup-label", t("bigGames.context.title")));

    const weightedProduction = summary.weighted_goal_assists_per90
        ?? summary.weighted_involvement_per90;

    if (!summary.sufficient_sample) {
        // Produktion bleibt sichtbar, auch wenn die Stichprobe noch nicht
        // fuer den ratingbasierten Big Game Score reicht.
        if (weightedProduction !== null && weightedProduction !== undefined) {
            const grid = make("div", "pd-core-grid");
            // Die katalogisierte Bezeichnung bleibt "G+A/90 (gew.)".
            grid.appendChild(bgBuildTile(
                bgFormatNumber(weightedProduction, 2), t("bigGames.context.weightedGoalAssistsPer90")));
            box.appendChild(grid);
        }
        box.appendChild(mcBuildNote(t("bigGames.context.insufficientSample", {
            matches: summary.min_matches,
            minutes: summary.min_minutes,
        })));
        return box;
    }

    const grid = make("div", "pd-core-grid");
    grid.appendChild(bgBuildTile(
        bgFormatNumber(summary.big_game_score, 2), t("bigGames.context.score"), "bg-tile-score"));
    grid.appendChild(bgBuildTile(
        bgFormatNumber(summary.avg_rating, 2), t("bigGames.context.averageRatingRaw")));
    grid.appendChild(bgBuildTile(
        bgFormatNumber(summary.avg_opponent_strength, 2), t("bigGames.context.averageOpponentStrength")));
    if (weightedProduction !== null && weightedProduction !== undefined) {
        grid.appendChild(bgBuildTile(
            bgFormatNumber(weightedProduction, 2), t("bigGames.context.weightedGoalAssistsPer90")));
    }
    box.appendChild(grid);

    box.appendChild(make("p", "bg-explain", t("bigGames.context.scoreExplanation")));

    return box;
}

/** Die ausgewerteten Spiele - macht die Bewertung nachvollziehbar. */
function bgBuildMatchList(player) {
    if (!player.matches.length) return null;

    const box = make("div", "bg-block");
    box.appendChild(make("p", "mc-lineup-label", t("bigGames.matches.title")));

    const list = make("div", "bg-match-list");

    player.matches.forEach(match => {
        const row = make("div", "bg-match");

        row.appendChild(make("span", "bg-match-date",
            match.date ? match.date.slice(0, 10) : ""));

        const body = make("div", "bg-match-body");
        const opponent = make("div", "bg-match-opponent");
        if (match.opponent_logo) opponent.appendChild(crest(match.opponent_logo, "bg-match-crest"));
        opponent.appendChild(document.createTextNode(` ${match.is_home ? "" : "@ "}${match.opponent_name || t("player.unknown")}`));
        body.appendChild(opponent);

        const meta = [];
        if (match.opponent_rank) {
            const rankingSource = match.ranking_source === "fifa" ? "FIFA" : "UEFA";
            meta.push(`${rankingSource} #${match.opponent_rank}`);
        }
        if (match.league_name) meta.push(match.league_name);
        body.appendChild(make("div", "bg-match-meta", meta.join(" · ")));
        row.appendChild(body);

        const stats = make("div", "bg-match-stats");
        // Torbeteiligung dieses einen Spiels - reine Rohwerte aus den
        // bereits geladenen Einzelspielerwerten (build_big_games_profile()),
        // kein zusaetzlicher Request und keine Herleitung.
        if (match.goals) stats.appendChild(make("span", "bg-match-goals", `${match.goals}⚽`));
        if (match.assists) stats.appendChild(make("span", "bg-match-goals", `${match.assists}👟`));
        if (match.rating !== null && match.rating !== undefined) {
            stats.appendChild(make("span", "bg-match-rating", Number(match.rating).toFixed(1)));
        }
        row.appendChild(stats);

        list.appendChild(row);
    });

    box.appendChild(list);
    return box;
}

function bgBuildPlayerColumn(player) {
    const column = make("div", "bg-player");
    column.appendChild(bgBuildPlayerHeader(player));

    if (!player.match_count) {
        column.appendChild(mcBuildNote(t("bigGames.matches.emptyPeriod")));
        return column;
    }

    column.appendChild(bgBuildRawBlock(player));
    column.appendChild(bgBuildContextBlock(player));

    const matches = bgBuildMatchList(player);
    if (matches) column.appendChild(matches);

    return column;
}

function bgBuildMobileSummary(data) {
    if (!data.a) return null;

    const summary = make("div", "bg-mobile-summary");
    const title = make("h3", "pc-metrics-title", t("playerCompare.metrics.title"));
    title.textContent = "Kompaktübersicht"; // fallback if translation is empty
    summary.appendChild(title);

    const playerA = data.a;
    const playerB = data.b;

    const metricsToRender = [
        { key: "matches", label: "Spiele", extractor: (p) => p.summary.raw.matches },
        { key: "goals", label: "Tore", extractor: (p) => p.summary.raw.goals },
        { key: "assists", label: "Vorlagen", extractor: (p) => p.summary.raw.assists },
        { key: "goal_assists", label: "G+A", extractor: (p) => p.summary.raw.goal_assists },
        { key: "avg_rating", label: "Ø Bewertung", extractor: (p) => p.summary.avg_rating },
        { key: "big_game_score", label: "Big Game Score", extractor: (p) => p.summary.big_game_score }
    ];

    metricsToRender.forEach(m => {
        const valA = m.extractor(playerA);
        const valB = playerB ? m.extractor(playerB) : null;

        if ((valA === null || valA === undefined) && (!playerB || (valB === null || valB === undefined))) {
            return;
        }

        const row = make("div", "pc-metric-row");
        const head = make("div", "pc-metric-head");
        head.appendChild(make("span", "pc-metric-label", m.label));
        row.appendChild(head);

        const bars = make("div", "pc-bars");
        const players = [["a", valA, PC_COLOR_A, playerA]];
        if (playerB) players.push(["b", valB, PC_COLOR_B, playerB]);

        let maxVal = 0;
        players.forEach(([slot, val]) => {
            const num = parseFloat(val);
            if (!isNaN(num) && num > maxVal) maxVal = num;
        });

        players.forEach(([slot, value, color, player]) => {
            const bar = make("div", "pc-bar-row");
            const name = make("span", "pc-bar-name", player.name || slot.toUpperCase());
            bar.appendChild(name);

            const track = make("div", "pc-bar-track");
            const fill = make("div", "pc-bar-fill");
            const numVal = parseFloat(value);
            const pct = (maxVal > 0 && !isNaN(numVal)) ? (numVal / maxVal) * 100 : 0;
            fill.style.width = `${pct}%`;
            fill.style.background = color;
            track.appendChild(fill);
            bar.appendChild(track);

            const numbers = make("span", "pc-bar-numbers");
            numbers.appendChild(make("span", "pc-bar-value", value !== null && value !== undefined ? value : "-"));
            bar.appendChild(numbers);
            bars.appendChild(bar);
        });

        row.appendChild(bars);
        summary.appendChild(row);
    });

    return summary;
}

function bgRenderComparison(data) {
    hide(pcEmpty);
    pcResult.innerHTML = "";
    show(pcResult);

    const wrap = make("div", "bg-result");

    // Fehlende Saisons ehrlich benennen, statt sie stillschweigend
    // wegzulassen - sonst wirkt ein unvollstaendiger Zeitraum vollstaendig.
    const players = [data.a, data.b].filter(Boolean);
    const unavailable = [];
    players.forEach(player => {
        (player.seasons || []).forEach(season => {
            if (!season.available && !unavailable.includes(season.season_label)) {
                unavailable.push(season.season_label);
            }
        });
    });

    if (unavailable.length) {
        wrap.appendChild(mcBuildNote(t("bigGames.opponentStrengthUnavailable", {
            seasons: unavailable.join(", "),
        })));
    }

    const columns = make("div", "bg-columns" + (players.length > 1 ? "" : " is-single"));
    players.forEach(player => columns.appendChild(bgBuildPlayerColumn(player)));
    
    if (players.length > 1) {
        const mobileSummary = bgBuildMobileSummary(data);
        if (mobileSummary) wrap.appendChild(mobileSummary);
    }
    
    wrap.appendChild(columns);

    pcResult.appendChild(wrap);
}

/* ---------- Turnierverfuegbarkeit je Saison ----------

   EM und WM gibt es - anders als Liga und Champions League - nicht in
   jedem Saisonzyklus. Welche Turniere eine Saison hat, liefert das
   Backend je Saison in tournaments_available mit; hier wird daraus nur
   noch die Schaltflaeche deaktiviert.

   Bewusst getrennt von "der Spieler hat dort keine Daten": das eine ist
   ein Eigenschaft der Saison (Scope nicht waehlbar), das andere eine des
   Spielers (neutraler data_available-Hinweis im Ergebnis).
------------------------------------------------------------------- */

/** tournaments_available einer Saison aus der geladenen Saisonliste. */
function pcTournamentsFor(season) {
    const entry = (pcState.seasons || []).find(s => s.season === season);
    return (entry && entry.tournaments_available) || {};
}

/**
 * Deaktiviert Turnier-Scopes, deren Turnier in keiner der uebergebenen
 * Saisons stattfand.
 *
 * seasons: eine oder mehrere Saisons. Im Radar duerfen beide Slots
 * unterschiedliche Saisons haben - dann genuegt es, wenn das Turnier in
 * EINER davon stattfand: der andere Spieler landet regulaer im neutralen
 * "keine Daten"-Zustand, was fachlich korrekt ist.
 *
 * Rueckgabe: true, wenn der aktive Scope weiterhin waehlbar ist.
 */
function pcApplyScopeAvailability(nav, seasons, activeScope) {
    if (!nav) return true;

    const maps = (seasons || []).map(pcTournamentsFor);
    let activeUsable = true;

    nav.querySelectorAll(".pc-scope-btn").forEach(button => {
        const scope = button.dataset.scope;

        const known = maps.some(m => Object.prototype.hasOwnProperty.call(m, scope));
        const usable = !known || maps.some(m => m[scope]);

        button.disabled = !usable;
        if (!usable) {
            button.classList.remove("active");
            button.setAttribute("aria-checked", "false");
            button.tabIndex = -1;
        }
        
        button.setAttribute("aria-disabled", usable ? "false" : "true");
        button.title = usable ? "" : PC_TEXT.scopeUnavailable();

        if (scope === activeScope) activeUsable = usable;
    });

    return activeUsable;
}

/** Beide Navigationen an die aktuell gewaehlten Saisons anpassen. */
function pcRefreshScopeAvailability() {
    const radarSeasons = [pcState.a.season, pcState.b.season].filter(s => s);
    if (!pcApplyScopeAvailability(pcScopeNav, radarSeasons, pcState.scope)) {
        // Gewaehlter Scope existiert in der neuen Saison nicht mehr:
        // still auf den Standard zurueck, statt einen toten Zustand zu
        // hinterlassen. silent, damit kein Vergleich nachgeladen wird -
        // die Slots werden beim Saisonwechsel ohnehin geleert.
        pcSetScope("club_all", { silent: true });
    }

    const scatterSeason = [pcState.scatter.season].filter(s => s);
    if (!pcApplyScopeAvailability(pcScatterScopeNav, scatterSeason,
                                  pcState.scatter.scope)) {
        pcScatterSetScope("club_all");
    }
}


if (pcScopeNav) {
    pcScopeNav.addEventListener("click", (event) => {
        const button = event.target.closest(".pc-scope-btn");
        if (!button || button.disabled) return;
        pcSetScope(button.dataset.scope);
    });

    pcScopeNav.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;

        // Deaktivierte Scopes (Turnier gab es in dieser Saison nicht)
        // ueberspringt die Pfeilnavigation, sonst landet der Fokus auf
        // einer nicht waehlbaren Schaltflaeche.
        const buttons = Array.from(pcScopeNav.querySelectorAll(".pc-scope-btn"))
            .filter(b => !b.disabled);
        if (!buttons.length) return;

        const current = buttons.findIndex(b => b.dataset.scope === pcState.scope);
        let next = current < 0 ? 0 : current;

        if (event.key === "ArrowLeft")  next = (next - 1 + buttons.length) % buttons.length;
        if (event.key === "ArrowRight") next = (next + 1) % buttons.length;
        if (event.key === "Home")       next = 0;
        if (event.key === "End")        next = buttons.length - 1;

        event.preventDefault();
        pcSetScope(buttons[next].dataset.scope);
        buttons[next].focus();
    });
}


/* ---------- 16a4. Moduswahl: Radar oder Plots ----------

   Zwei Container innerhalb desselben Bereichs, keine neue Route. Beide
   teilen sich pcState.position, pcState.scope (nur Radar-relevant) und
   die gewaehlten Spieler - ein Wechsel verliert nichts.

   Scatter wird erst beim ersten Aufruf initialisiert (Achsen-Dropdowns
   fuellen, erste Punktliste laden), damit ein Nutzer, der nur den Radar
   benutzt, keinen unnoetigen Request ausloest.
------------------------------------------------------------------- */

function pcSetMode(mode) {
    if (pcState.mode === mode) return;
    pcState.mode = mode;

    document.querySelectorAll(".pc-mode-card").forEach(card => {
        const active = card.dataset.mode === mode;
        card.classList.toggle("active", active);
        card.setAttribute("aria-checked", active ? "true" : "false");
    });

    if (pcRadarView)   pcRadarView.classList.toggle("hidden", mode !== "radar");
    if (pcScatterView) pcScatterView.classList.toggle("hidden", mode !== "scatter");

    if (mode === "scatter" && !pcState.scatter.ready) {
        pcScatterInit();
    }
}

if (pcModeSelect) {
    pcModeSelect.addEventListener("click", (event) => {
        const card = event.target.closest(".pc-mode-card");
        if (!card) return;
        pcSetMode(card.dataset.mode);
    });
}


/* ---------- 16b. Einmalige Initialisierung ---------- */

let pcControlsReady = false;

async function pcInitControls() {
    // Genau wie beim Transfervergleich: nur beim ersten Oeffnen des Bereichs.
    if (pcControlsReady) return;
    pcControlsReady = true;

    try {
        const data = await fetchJson("/api/player-seasons");

        pcState.seasons = data.seasons || [];
        pcState.minQueryLength = data.min_query_length || 3;

        for (const slot of ["a", "b"]) {
            const select = pcSeasonSelects[slot];
            if (!select) continue;

            select.innerHTML = "";
            pcState.seasons.forEach(season => {
                const option = document.createElement("option");
                option.value = season.season;
                // "nur Rohwerte" nur dann, wenn wirklich KEINE nutzbare
                // Vergleichsgrundlage existiert.
                //
                // Frueher stand das an jeder Saison ohne eigenen Pool -
                // auch an 2026/27, obwohl der Vergleich dort laengst ueber
                // die Referenz aus 2025/26 laeuft. Der Datenstand gehoert
                // an den einzelnen Spieler, nicht pauschal an die Saison.
                const hatVergleich = season.percentiles_available
                    || season.reference_season != null;
                option.textContent = hatVergleich
                    ? season.label
                    : t("player.season.rawValuesOnly", { season: season.label });
                select.appendChild(option);
            });

            const current = pcState.seasons.find(s => s.is_current);
            if (current) select.value = current.season;
            pcState[slot].season = parseInt(select.value, 10);
            if (slot === "a") pcState.season = pcState.a.season;

            select.addEventListener("change", () => {
                pcState[slot].season = parseInt(select.value, 10);
                // Saisonwechsel macht die bisherige Auswahl ungueltig:
                // der Spieler hat je Saison einen anderen Datensatz.
                //
                // Ein laufender Vergleich wird zusaetzlich abgebrochen und
                // seine Generation verworfen. Sonst koennte seine Antwort
                // nach dem Wechsel eintreffen und ein Ergebnis mit der
                // ALTEN Saison zeichnen, waehrend die Auswahl bereits die
                // neue zeigt.
                pcInvalidateComparison();
                pcClearSlot(slot);
                pcUpdateReady();

                // Slot A fuehrt die geteilte Saison fuer Plots.
                if (slot === "a") {
                    pcState.season = pcState.a.season;
                }

                // EM/WM gibt es nicht in jeder Saison - Auswahl nachziehen.
                pcRefreshScopeAvailability();
            });
        }

        if (pcScatterSeasonSelect) {
            pcScatterSeasonSelect.innerHTML = "";
            pcState.seasons.forEach(season => {
                const option = document.createElement("option");
                option.value = season.season;
                option.textContent = season.label;
                pcScatterSeasonSelect.appendChild(option);
            });
            const current = pcState.seasons.find(s => s.is_current);
            if (current) pcScatterSeasonSelect.value = current.season;
            pcState.scatter.season = parseInt(pcScatterSeasonSelect.value, 10);

            pcScatterSeasonSelect.addEventListener("change", () => {
                pcState.scatter.season = parseInt(pcScatterSeasonSelect.value, 10);
                if (pcState.scatter.ready) pcScatterMarkDirty();
                pcRefreshScopeAvailability();
            });
        }

        pcState.ready = true;
        pcRefreshScopeAvailability();
        pcUpdateReady();

    } catch (error) {
        pcStatus.textContent = t("player.seasonsLoadFailed");
        pcControlsReady = false;   // naechster Versuch darf erneut laden
    }
}


/* ---------- 16c. Suche ---------- */

async function pcSearch(slot, query) {
    const slotState = pcState[slot];

    // Jede Suche bekommt eine laufende Nummer. Trifft eine aeltere Antwort
    // nach einer neueren ein, wird sie verworfen. Ohne das ueberschreibt
    // "Ka" gelegentlich das Ergebnis von "Kane".
    const requestId = ++slotState.requestId;

    pcRenderResults(slot, null, "loading");

    // Der Zeitraum muss stehen, bevor mit ihm gesucht wird - sonst ginge
    // beim ersten Tastendruck nach dem Umschalten "null" an den Server.
    if (bgIsActive()) await bgEnsureLoaded();

    try {
        // Bei Big Games sucht eine eigene Route ueber die historischen
        // Wettbewerbe, damit auch Spieler gefunden werden, die heute
        // ausserhalb der fuenf Vergleichsligen spielen. Sie befuellt
        // ausdruecklich keinen Pool - siehe Abschnitt 16d-bg.
        //
        // Gesucht wird ueber den GESAMTEN Zeitraum, nicht nur ueber dessen
        // letzte Saison: wer nur in der ersten Saison in einem unserer
        // Wettbewerbe stand und danach wechselte, muss auffindbar bleiben.
        const url = bgIsActive()
            ? `/api/big-games-search?q=${encodeURIComponent(query)}`
              + `&season_from=${bgState.from}&season_to=${bgState.to}`
            : `/api/player-search?q=${encodeURIComponent(query)}`
              + `&season=${slotState.season}`;
        const response = await fetch(url);
        const data = await response.json();

        if (requestId !== slotState.requestId) return;   // veraltete Antwort

        if (!response.ok) {
            pcRenderResults(slot, null, "error", visibleApiError(data, "error.genericRequestFailed"));
            return;
        }

        // Die API-Antwort wird ungefiltert gecacht (Backend), erst hier
        // auf die aktive Positionsgruppe reduziert. Ein Wechsel der Gruppe
        // kostet dadurch keinen einzigen zusaetzlichen API-Request.
        slotState.results = pcFilterByPosition((data.results || []).map(localizedPlayer));
        slotState.activeIndex = -1;
        pcRenderResults(slot, slotState.results, "ok");

    } catch (error) {
        if (requestId !== slotState.requestId) return;
        pcRenderResults(slot, null, "error", t("player.searchUnreachable"));
    }
}

function pcHandleInput(slot) {
    const slotState = pcState[slot];
    const value = pcSearchInputs[slot].value.trim();

    clearTimeout(slotState.timer);

    if (value.length < pcState.minQueryLength) {
        // Laufende Antworten entwerten, sonst poppt die Liste nachtraeglich auf.
        slotState.requestId++;
        pcRenderResults(slot, null, "hidden");
        return;
    }

    // Saisonwahl muss vor der Suche initialisiert sein. Falls pcInitControls()
    // noch laeuft oder fehlgeschlagen ist, wird kurz gewartet und erneut versucht.
    if (!pcState.ready || !slotState.season) {
        slotState.timer = setTimeout(() => pcHandleInput(slot), 150);
        return;
    }

    // Entprellung: erst wenn kurz nichts mehr getippt wurde.
    slotState.timer = setTimeout(() => pcSearch(slot, value), PC_SEARCH_DELAY);
}

function pcRenderResults(slot, results, mode, message) {
    const box = pcResultBoxes[slot];
    const input = pcSearchInputs[slot];
    box.innerHTML = "";

    if (mode === "hidden") {
        hide(box);
        input.setAttribute("aria-expanded", "false");
        return;
    }

    show(box);
    input.setAttribute("aria-expanded", "true");

    if (mode === "loading") {
        box.appendChild(make("div", "pc-result-note", t("player.searchLoading")));
        return;
    }

    if (mode === "error") {
        box.appendChild(make("div", "pc-result-note pc-result-error",
                             message || t("player.searchFailed")));
        return;
    }

    if (!results || results.length === 0) {
        box.appendChild(make("div", "pc-result-note", t("player.noPlayers")));
        return;
    }

    // Seit der Positionsnavigation sind alle Treffer bereits gefiltert:
    // im Positionsmodus gehoeren sie ohnehin zur gewaehlten Gruppe, im
    // freien Modus ist jede Gruppe zulaessig. Eine Hervorhebung einzelner
    // Treffer waere hier nur noch Rauschen.
    results.forEach((player, index) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "pc-result-row";
        row.setAttribute("role", "option");
        row.setAttribute("aria-selected", "false");
        row.dataset.index = index;

        if (!player.comparable) {
            // Spieler ausserhalb der fuenf Vergleichsligen bleiben sichtbar,
            // aber nicht waehlbar. Sie wegzulassen wuerde verwirren.
            row.classList.add("pc-result-disabled");
            row.disabled = true;
        }

        if (player.photo) {
            const img = document.createElement("img");
            img.src = player.photo;
            img.alt = "";
            img.className = "pc-result-photo";
            img.loading = "lazy";
            row.appendChild(img);
        }

        const text = make("div", "pc-result-text");
        text.appendChild(make("span", "pc-result-name", player.name || t("player.unknown")));

        const metaParts = [];
        if (player.team_name) metaParts.push(player.team_name);
        if (player.league_label) metaParts.push(player.league_label);
        if (player.position_label) metaParts.push(player.position_label);
        if (player.age) metaParts.push(t("player.age", { count: player.age }));

        text.appendChild(make("span", "pc-result-meta", metaParts.join(" · ")));

        if (!player.comparable) {
            text.appendChild(make("span", "pc-result-warning",
                                  t("player.noTopFiveData")));
        }

        row.appendChild(text);
        row.addEventListener("click", () => pcSelectPlayer(slot, player));
        box.appendChild(row);
    });
}


/* ---------- Tastaturbedienung der Trefferliste ---------- */

function pcHandleKeydown(slot, event) {
    const slotState = pcState[slot];
    const rows = Array.from(pcResultBoxes[slot].querySelectorAll(".pc-result-row:not([disabled])"));

    if (event.key === "Escape") {
        pcRenderResults(slot, null, "hidden");
        return;
    }

    if (rows.length === 0) return;

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const direction = event.key === "ArrowDown" ? 1 : -1;
        slotState.activeIndex = (slotState.activeIndex + direction + rows.length) % rows.length;
        rows.forEach((row, i) => {
            const active = i === slotState.activeIndex;
            row.classList.toggle("pc-result-active", active);
            row.setAttribute("aria-selected", active ? "true" : "false");
            if (active) row.scrollIntoView({ block: "nearest" });
        });
        return;
    }

    if (event.key === "Enter" && slotState.activeIndex >= 0) {
        event.preventDefault();
        rows[slotState.activeIndex].click();
    }
}


/* ---------- 16d. Auswahl ---------- */

function pcSelectPlayer(slot, player) {
    pcState[slot].player = player;
    pcSearchInputs[slot].value = player.name || "";
    pcRenderResults(slot, null, "hidden");
    pcRenderSelected(slot);
    pcUpdateReady();
}

/**
 * Bricht einen laufenden Vergleich ab und entwertet seine Antwort.
 *
 * Wird bei jedem Zustandswechsel aufgerufen, der das Ergebnis ungueltig
 * macht: Saison, Spielerauswahl, Wettbewerbsumfang.
 */
function pcInvalidateComparison() {
    if (pcState.comparisonAbort) {
        pcState.comparisonAbort.abort();
        pcState.comparisonAbort = null;
    }
    // Generation weiterzaehlen: Eine noch unterwegs befindliche Antwort
    // erkennt daran, dass sie nicht mehr gebraucht wird.
    pcState.comparisonId += 1;
    pcState.lastComparison = null;
}


function pcClearSlot(slot) {
    pcState[slot].player = null;
    pcState[slot].results = [];
    pcState[slot].activeIndex = -1;
    pcSearchInputs[slot].value = "";
    pcRenderResults(slot, null, "hidden");
    hide(pcSelectedBoxes[slot]);
    pcSelectedBoxes[slot].innerHTML = "";
}

/**
 * Vertauscht Spieler A und B inklusive Saisonwahl.
 *
 * Rein im Frontend: es werden nur die beiden Slot-Zustaende getauscht und
 * neu gezeichnet. Kein API-Request, weil sich an den Daten nichts aendert -
 * nur an ihrer Zuordnung zu Farbe und Reihenfolge.
 *
 * Ein bereits sichtbares Ergebnis wird verworfen, weil es sonst zur neuen
 * Reihenfolge nicht mehr passen wuerde.
 */
function pcSwapPlayers() {
    const a = pcState.a;
    const b = pcState.b;

    if (!a.player && !b.player) return;

    const tmpPlayer = a.player;
    const tmpSeason = a.season;

    a.player = b.player;
    a.season = b.season;
    b.player = tmpPlayer;
    b.season = tmpSeason;

    ["a", "b"].forEach(slot => {
        const slotState = pcState[slot];

        // Laufende Suchanfragen entwerten, sonst ueberschreibt eine spaet
        // eintreffende Antwort den gerade getauschten Zustand.
        clearTimeout(slotState.timer);
        slotState.requestId++;
        slotState.results = [];
        slotState.activeIndex = -1;

        pcSearchInputs[slot].value = slotState.player ? (slotState.player.name || "") : "";
        if (pcSeasonSelects[slot] && slotState.season) {
            pcSeasonSelects[slot].value = String(slotState.season);
        }

        pcRenderResults(slot, null, "hidden");
        pcRenderSelected(slot);
    });

    // Das alte Ergebnis passt nicht mehr zur neuen Reihenfolge.
    pcResult.innerHTML = "";
    hide(pcResult);
    show(pcEmpty);

    pcState.season = pcState.a.season;
    pcRefreshScopeAvailability();
    pcUpdateReady();
}

function pcRenderSelected(slot) {
    const player = pcState[slot].player;
    const box = pcSelectedBoxes[slot];
    box.innerHTML = "";

    if (!player) {
        hide(box);
        return;
    }

    const card = make("div", `pc-player-card pc-card-${slot}`);

    if (player.photo) {
        const img = document.createElement("img");
        img.src = player.photo;
        img.alt = "";
        img.className = "pc-player-photo";
        card.appendChild(img);
    }

    const info = make("div", "pc-player-info");
    info.appendChild(make("span", "pc-player-name", player.name || t("player.unknown")));

    const meta = [];
    if (player.team_name) meta.push(player.team_name);
    if (player.position_label) meta.push(player.position_label);
    info.appendChild(make("span", "pc-player-meta", meta.join(" · ")));

    const minutes = player.minutes
        ? t("player.minutes", { count: player.minutes.toLocaleString(activeIntlLocale()) })
        : t("player.noMinutes");
    info.appendChild(make("span", "pc-player-minutes", minutes));

    card.appendChild(info);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "pc-remove-btn";
    remove.setAttribute("aria-label", t("player.remove", { name: player.name || t("player.unknown") }));
    remove.textContent = "×";
    remove.addEventListener("click", () => {
        pcClearSlot(slot);
        pcUpdateReady();
    });
    card.appendChild(remove);

    box.appendChild(card);
    show(box);
}

function pcUpdateReady() {
    const a = pcState.a.player;
    const b = pcState.b.player;

    let message = t("players.chooseTwo");
    let enabled = false;

    if (a && b) {
        // Bei Big Games gilt EIN gemeinsamer Zeitraum fuer beide Spieler.
        // Die Saisonfelder der Slots sind dort ausgeblendet und werden vom
        // Vergleich nicht ausgewertet - sie duerfen deshalb auch nicht
        // darueber entscheiden, ob verglichen werden darf. Derselbe
        // Spieler gegen sich selbst ergibt im selben Zeitraum nie einen
        // Vergleich.
        const sameSeason = bgIsActive()
            ? true
            : pcState.a.season === pcState.b.season;

        if (a.player_id === b.player_id && sameSeason) {
            // Derselbe Spieler in derselben Saison ergibt keinen Vergleich,
            // in zwei verschiedenen Saisons dagegen schon.
            message = bgIsActive()
                ? t("player.chooseDifferentPlayers")
                : t("player.chooseDifferentPlayersOrSeasons");
        } else {
            message = t("player.ready");
            enabled = true;
        }
    } else if (a || b) {
        message = t("player.chooseSecond");
    }

    pcStatus.textContent = message;
    pcCompareBtn.disabled = !enabled;

    // Tauschen ergibt nur Sinn, wenn ueberhaupt jemand gewaehlt ist.
    if (pcSwapBtn) pcSwapBtn.disabled = !(a || b);
}


/* ---------- 16e. Vergleich anfordern ---------- */

async function pcRunComparison() {
    const a = pcState.a.player;
    const b = pcState.b.player;
    if (!a || !b) return;

    // Big Games hat eine eigene Route und ein eigenes Ergebnismodell.
    if (bgIsActive()) {
        await bgRunComparison();
        return;
    }

    pcCompareBtn.disabled = true;
    pcStatus.textContent = t("player.comparisonLoading");

    // Laufenden Vergleich abbrechen, damit seine Antwort nicht mehr
    // eintrifft, und eine neue Generation eroeffnen.
    if (pcState.comparisonAbort) pcState.comparisonAbort.abort();
    const abort = new AbortController();
    pcState.comparisonAbort = abort;
    const comparisonId = ++pcState.comparisonId;

    // Der Zustand, mit dem dieser Request losgeschickt wird. Die Antwort
    // wird spaeter dagegen geprueft - nicht gegen den dann aktuellen
    // Zustand, denn der kann sich inzwischen geaendert haben.
    const gesendet = {
        a: a.player_id, b: b.player_id,
        seasonA: pcState.a.season, seasonB: pcState.b.season,
        scope: pcState.scope,
    };

    try {
        // Im freien Modus wird das General-Radar erzwungen, damit die
        // Darstellung nicht davon abhaengt, ob zufaellig zwei Spieler
        // derselben Position gewaehlt wurden.
        const modeParam = pcState.position ? "" : "&mode=general";
        const url = `/api/player-compare?a=${gesendet.a}&b=${gesendet.b}`
                  + `&season_a=${gesendet.seasonA}&season_b=${gesendet.seasonB}`
                  + `&scope=${gesendet.scope}`
                  + modeParam;
        const response = await fetch(url, { signal: abort.signal });
        const data = await response.json();

        // Veraltete Antwort: inzwischen wurde erneut verglichen.
        if (comparisonId !== pcState.comparisonId) return;

        // Der Zustand hat sich waehrend der Anfrage geaendert (Saison,
        // Spieler oder Wettbewerbsumfang). Ein Ergebnis, das nicht mehr zur
        // sichtbaren Auswahl passt, darf nicht gezeichnet werden - lieber
        // gar keins als ein falsch beschriftetes.
        if (!pcState.a.player || !pcState.b.player
            || pcState.a.player.player_id !== gesendet.a
            || pcState.b.player.player_id !== gesendet.b
            || pcState.a.season !== gesendet.seasonA
            || pcState.b.season !== gesendet.seasonB
            || pcState.scope !== gesendet.scope) {
            pcStatus.textContent = "";
            pcCompareBtn.disabled = false;
            return;
        }

        if (!response.ok) {
            pcStatus.textContent = visibleApiError(data, "error.genericRequestFailed");
            pcCompareBtn.disabled = false;
            return;
        }

        const localizedData = localizedComparisonPayload(data);
        pcState.lastComparison = localizedData;
        pcRenderComparison(localizedData);
        pcStatus.textContent = t("player.comparisonReady");

    } catch (error) {
        // Ein absichtlicher Abbruch ist kein Fehler: Er passiert genau
        // dann, wenn der Nutzer schon etwas Neueres angestossen hat.
        // Eine Fehlermeldung dafuer waere schlicht falsch.
        if (error && error.name === "AbortError") return;
        if (comparisonId !== pcState.comparisonId) return;
        pcStatus.textContent = t("player.comparisonUnavailable");
    } finally {
        if (comparisonId === pcState.comparisonId) {
            pcCompareBtn.disabled = false;
        }
    }
}


/* ---------- Ergebnis aufbauen ---------- */

function pcRenderComparison(data) {
    hide(pcEmpty);
    pcResult.innerHTML = "";
    show(pcResult);

    const comparison = data.comparison || {};

    pcResult.appendChild(pcBuildHeader(data.player_a, data.player_b));

    // Datenstand je Spieler direkt unter den Karten: "noch ohne Einsatz"
    // oder "vorlaeufig". Erscheint nur, wenn es etwas zu erklaeren gibt.
    const statusZeilen = pcBuildDataStatusNote(comparison, data);
    if (statusZeilen) pcResult.appendChild(statusZeilen);

    // Fehlende Daten in der gewaehlten Datenbasis sind ein fachlicher
    // Normalzustand, kein Fehler - deshalb ein neutraler Hinweis direkt
    // unter den Spielerkarten statt einer Fehlermeldung.
    const scopeNote = pcBuildScopeDataNote(data);
    if (scopeNote) pcResult.appendChild(scopeNote);

    // Radar nur wenn beide dieselbe Positionsgruppe haben. Ein gemeinsames
    // Radar ueber Torwart und Stuermer waere fachlich irrefuehrend.
    if (comparison.radar_enabled) {
        pcResult.appendChild(pcBuildRadar(comparison, data.player_a, data.player_b));
    } else {
        pcResult.appendChild(pcBuildModeNote(comparison));
    }

    pcResult.appendChild(pcBuildPoolNote(comparison, data.min_minutes));
    pcResult.appendChild(pcBuildMetricList(comparison, data.player_a, data.player_b));
    pcResult.appendChild(pcBuildSummary(comparison, data.player_a, data.player_b));
}

function pcBuildHeader(playerA, playerB) {
    const head = make("div", "pc-head");

    [[playerA, "a"], [playerB, "b"]].forEach(([player, slot]) => {
        const card = make("div", `pc-head-card pc-card-${slot}`);

        if (player.photo) {
            const img = document.createElement("img");
            img.src = player.photo;
            img.alt = "";
            img.className = "pc-head-photo";
            card.appendChild(img);
        }

        const info = make("div", "pc-head-info");
        info.appendChild(make("span", "pc-head-name", player.name || t("player.unknown")));

        const meta = [];
        if (player.team_name) meta.push(player.team_name);
        if (player.league_label) meta.push(player.league_label);
        info.appendChild(make("span", "pc-head-meta", meta.join(" · ")));

        const detail = [];
        if (player.position_label) detail.push(player.position_label);
        if (player.season_label) detail.push(player.season_label);
        // Ohne Einsaetze in der gewaehlten Datenbasis waere "0 Min" oder
        // eine leere Zeile irrefuehrend - der Zustand wird benannt.
        if (player.data_available === false) {
            detail.push(PC_TEXT.scopeNoDataShort());
        } else if (player.minutes) {
            detail.push(t("player.minutesShort", { count: player.minutes.toLocaleString(activeIntlLocale()) }));
        }
        info.appendChild(make("span", "pc-head-detail", detail.join(" · ")));

        card.appendChild(info);
        head.appendChild(card);
    });

    return head;
}

/** Beschriftung der gerade aktiven Datenbasis, direkt aus der Navigation. */
function pcActiveScopeLabel() {
    const button = pcScopeNav && pcScopeNav.querySelector(".pc-scope-btn.active");
    return (button && button.textContent.trim()) || "";
}


/**
 * Hinweis, wenn einem oder beiden Spielern in der gewaehlten Datenbasis
 * die Einsaetze fehlen.
 *
 * Das ist ein fachlicher Normalzustand - ein Spieler ohne
 * Champions-League-Teilnahme hat dort schlicht keine Werte. Deshalb
 * bewusst dieselbe neutrale pc-note wie beim Modushinweis: kein
 * Fehlerzustand, keine eigene Farbe, kein rotes Element.
 *
 * Gibt null zurueck, wenn beide Spieler Daten haben.
 */
function pcBuildScopeDataNote(data) {
    const playerA = data.player_a || {};
    const playerB = data.player_b || {};

    const missingA = playerA.data_available === false;
    const missingB = playerB.data_available === false;

    if (!missingA && !missingB) return null;

    const scopeLabel = pcActiveScopeLabel();
    const box = make("div", "pc-note");
    box.appendChild(make("strong", "", t("playerCompare.scopeDataMissingTitle")));

    if (missingA && missingB) {
        box.appendChild(make("p", "", PC_TEXT.scopeNoDataBoth(scopeLabel)));
    } else {
        const missing = missingA ? playerA : playerB;
        box.appendChild(make("p", "", PC_TEXT.scopeNoData(
            missing.name || t("playerCompare.thisPlayer"), scopeLabel
        )));
    }

    return box;
}


function pcBuildModeNote(comparison) {
    const box = make("div", "pc-note");

    // Kein Radar wegen fehlender Daten ist etwas ANDERES als kein Radar
    // wegen unterschiedlicher Positionen. Frueher stand hier in beiden
    // Faellen derselbe Text ueber Positionsgruppen - bei einem Spieler
    // ohne Einsaetze war das schlicht die falsche Erklaerung.
    const fehlt = [];
    if (comparison.data_available_a === false) fehlt.push("a");
    if (comparison.data_available_b === false) fehlt.push("b");

    if (fehlt.length) {
        box.appendChild(make("strong", "", t("playerCompare.noRadarTitle")));
        box.appendChild(make("p", "", t(
            fehlt.length === 2
                ? "playerCompare.noRadarBoth"
                : "playerCompare.noRadarOne"
        )));
        return box;
    }

    box.appendChild(make("strong", "", t("playerCompare.generalComparison")));

    const positions = [comparison.position_a, comparison.position_b]
        .filter(Boolean).length === 2;

    box.appendChild(make("p", "",
        positions
            ? t("playerCompare.generalComparisonDifferentPositions")
            : t("playerCompare.generalComparisonMissingPosition")
    ));

    return box;
}

/**
 * Container fuer die Datenstandshinweise beider Spieler.
 *
 * Nutzt dieselbe dezente Hinweisoptik wie der vorhandene Pool-Hinweis
 * (.pc-pool-hint) - kein neues Design, keine Warnfarbe. Der Name des
 * Spielers steht davor, damit bei zwei Hinweisen klar ist, wer gemeint
 * ist.
 */
function pcBuildDataStatusNote(comparison, data) {
    const zeilen = [];

    [["a", data.player_a], ["b", data.player_b]].forEach(([slot, spieler]) => {
        const text = pcPlayerDataStatus(comparison, slot);
        if (!text) return;
        const name = (spieler || {}).name;
        zeilen.push(name ? `${name}: ${text}` : text);
    });

    if (!zeilen.length) return null;

    const box = make("div", "pc-pool-note pc-pool-hint");
    zeilen.forEach(zeile => {
        box.appendChild(make("p", "pc-pool-hint-text", zeile));
    });
    return box;
}


function pcBuildPoolNote(comparison, minMinutes) {
    const box = make("div", "pc-pool-note");

    if (!comparison.percentiles_available) {
        // Kein Warnbox-Design - nur ein dezenter Hinweis unter dem Radar
        box.classList.add("pc-pool-hint");
        box.appendChild(make("span", "pc-pool-hint-text", PC_TEXT.rawOnly()));
        return box;
    }

    const pool = comparison.pool_a || comparison.pool_b;
    if (!pool) return box;

    const leagueText = comparison.percentile_pool_complete
        ? t("playerCompare.pool.topFiveLeagues")
        : t("playerCompare.pool.ofLeagues", { count: (pool.leagues || []).length });

    box.appendChild(make("strong", "", t("playerCompare.pool.title")));
    box.appendChild(make("p", "",
        t("playerCompare.pool.explanation")
        + PC_TEXT.rankExplain(leagueText, pool.season_label, pool.min_minutes)
    ));

    if (!comparison.percentile_pool_complete) {
        box.classList.add("pc-pool-partial");
        box.appendChild(make("p", "pc-pool-warning",
            t("playerCompare.pool.partial")
        ));
    }

    return box;
}


/**
 * Saison als "2026/27". Die Jahreszahl kommt IMMER aus der Antwort -
 * nie hartcodiert, sonst waere sie naechstes Jahr falsch.
 */
function pcSeasonLabel(season) {
    if (season == null) return null;
    const jahr = parseInt(season, 10);
    if (Number.isNaN(jahr)) return null;
    return `${jahr}/${String(jahr + 1).slice(2)}`;
}


/**
 * Kurze Statuszeile zum Datenstand eines Spielers.
 *
 * Beantwortet die Frage, die ein Nutzer zu Saisonbeginn zwangslaeufig
 * hat: "Warum steht da ueberall 0 - und woher kommt dann die Bewertung?"
 *
 * Bewusst eine Zeile im vorhandenen Hinweisstil, keine Warnbox: Es ist
 * kein Fehler, sondern der normale Zustand im August.
 *
 * Gibt null zurueck, wenn es nichts zu erklaeren gibt - ein Spieler mit
 * belastbaren Werten bekommt keinen Hinweis.
 */
function pcPlayerDataStatus(comparison, slot) {
    if (!comparison) return null;

    // VIER GETRENNTE BEGRIFFE - sie wurden frueher vermischt, und daraus
    // entstand der Widerspruch "Noch ohne Einsatz 2026/27 · Bewertung
    // basiert auf 2026/27": Dieselbe Saison stand einmal als Datenstand
    // und einmal als Referenz, obwohl beides Verschiedenes bedeutet.
    //
    //   statsSaison   aus welcher Saison die Rohwerte stammen
    //   referenz      welcher Perzentilpool sie einordnet
    //   minuten       wie viel tatsaechlich gespielt wurde
    //   status        wie belastbar das ist
    const status = comparison[`availability_status_${slot}`];
    const statsSaison = pcSeasonLabel(comparison[`data_season_${slot}`]);
    const referenz = pcSeasonLabel(comparison[`reference_season_${slot}`]);
    const minuten = comparison[`minutes_${slot}`];

    if (status === "no_current_appearance") {
        if (!referenz) return t("playerCompare.status.noReference");
        return t("playerCompare.status.noAppearance", {
            season: statsSaison || "",
            reference: referenz,
        });
    }

    if (status === "provisional") {
        // Referenz und Datenstand ausdruecklich getrennt benennen. Sind
        // sie gleich, waere der Zusatz "Einordnung anhand ..." sinnlos -
        // dann genuegt die Minutenangabe.
        if (referenz && statsSaison && referenz !== statsSaison) {
            return t("playerCompare.provisionalMinutes", {
                minutes: minuten,
                season: statsSaison,
                reference: referenz,
            });
        }
        if (!referenz) return null;
        return t("playerCompare.status.provisional", {
            minutes: minuten,
            reference: referenz,
        });
    }

    if (status === "unavailable" && comparison[`data_available_${slot}`] === false) {
        return t("playerCompare.noAppearanceScope");
    }

    // "current" ist der Normalfall und braucht keinen Zusatz.
    return null;

}


/* ---------- 16f. Radar ---------- */

function pcBuildRadar(comparison, playerA, playerB) {
    const metrics = (comparison.metrics || [])
        // Alle Metriken werden angezeigt. Ohne Pool werden Rohwerte
        // relativ zueinander normiert, damit das Radar eine Form ergibt.
        .filter(m => m.value_a !== null || m.value_b !== null);

    const wrap = make("div", "pc-radar-wrap");

    // Ueberschrift: der Nutzer muss sofort erkennen, WELCHE Achsen er sieht.
    // Bei ungleichen Positionen sind es andere Kennzahlen - das darf nicht
    // stillschweigend passieren.
    const isGeneral = comparison.mode === "general";
    const caption = make("div", "pc-radar-caption");

    if (isGeneral) {
        caption.classList.add("pc-radar-caption-general");
        caption.appendChild(make("span", "pc-radar-caption-title",
                                 t("playerCompare.radar.generalTitle")));
        caption.appendChild(make("span", "pc-radar-caption-sub",
            t("playerCompare.radar.generalSubtitle", {
                first: playerA.position_label || "?",
                second: playerB.position_label || "?",
            })));
    } else {
        caption.appendChild(make("span", "pc-radar-caption-title",
            t("playerCompare.radar.positionTitle", {
                position: comparison.radar_profile_label || "",
            })));
        caption.appendChild(make("span", "pc-radar-caption-sub",
            t("playerCompare.radar.positionSubtitle")));
    }
    wrap.appendChild(caption);

    if (metrics.length < 3) {
        // Unter drei Achsen ist ein Radar keine Form mehr, sondern eine Linie.
        wrap.appendChild(make("p", "pc-radar-fallback",
            t("playerCompare.radar.tooFewMetrics")));
        return wrap;
    }

    const size = 320;
    const center = size / 2;
    const radius = center - 54;
    const count = metrics.length;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    svg.setAttribute("class", "pc-radar");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", t("playerCompare.radar.aria", {
        first: playerA.name || t("player.unknown"),
        second: playerB.name || t("player.unknown"),
    }));

    const ns = "http://www.w3.org/2000/svg";
    const angleFor = i => (Math.PI * 2 * i / count) - Math.PI / 2;
    const pointAt = (i, ratio) => [
        center + Math.cos(angleFor(i)) * radius * ratio,
        center + Math.sin(angleFor(i)) * radius * ratio,
    ];

    // Ringe als Orientierung: 25, 50, 75, 100
    [0.25, 0.5, 0.75, 1].forEach(ratio => {
        const ring = document.createElementNS(ns, "polygon");
        const points = [];
        for (let i = 0; i < count; i++) {
            const [x, y] = pointAt(i, ratio);
            points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
        }
        ring.setAttribute("points", points.join(" "));
        ring.setAttribute("class", ratio === 1 ? "pc-radar-ring pc-radar-ring-outer"
                                               : "pc-radar-ring");
        svg.appendChild(ring);
    });

    // Speichen
    for (let i = 0; i < count; i++) {
        const [x, y] = pointAt(i, 1);
        const spoke = document.createElementNS(ns, "line");
        spoke.setAttribute("x1", center);
        spoke.setAttribute("y1", center);
        spoke.setAttribute("x2", x.toFixed(1));
        spoke.setAttribute("y2", y.toFixed(1));
        spoke.setAttribute("class", "pc-radar-spoke");
        svg.appendChild(spoke);
    }

    // Wenn Perzentile vorhanden: direkt auf 0-100 Skala.
    // Wenn nicht: Rohwerte beider Spieler je Metrik relativ normieren.
    // Niedrig-ist-besser Metriken werden dabei invertiert.
    const hasPercentiles = comparison.percentiles_available;

    const radarRatios = metrics.map(m => {
        const va = m.percentile_a !== null ? m.percentile_a : null;
        const vb = m.percentile_b !== null ? m.percentile_b : null;
        return { a: va, b: vb };
    });

    // Flaechen beider Spieler
    const drawArea = (slotKey, color, className) => {
        const points = [];
        let hasAny = false;
        for (let i = 0; i < count; i++) {
            const value = radarRatios[i][slotKey];
            // Fehlender Wert wird als Mittelpunkt gezeichnet, aber der
            // zugehoerige Punkt bleibt weg, damit nichts vorgetaeuscht wird.
            const ratio = value === null ? 0 : value / 100;
            if (value !== null) hasAny = true;
            const [x, y] = pointAt(i, ratio);
            points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
        }
        if (!hasAny) return;

        const area = document.createElementNS(ns, "polygon");
        area.setAttribute("points", points.join(" "));
        area.setAttribute("class", className);
        area.setAttribute("fill", color);
        area.setAttribute("stroke", color);
        svg.appendChild(area);

        for (let i = 0; i < count; i++) {
            if (radarRatios[i][slotKey] === null) continue;
            const [x, y] = pointAt(i, radarRatios[i][slotKey] / 100);
            const dot = document.createElementNS(ns, "circle");
            dot.setAttribute("cx", x.toFixed(1));
            dot.setAttribute("cy", y.toFixed(1));
            dot.setAttribute("r", "3.5");
            dot.setAttribute("fill", color);
            svg.appendChild(dot);
        }
    };

    drawArea("a", PC_COLOR_A, "pc-radar-area pc-radar-area-a");
    drawArea("b", PC_COLOR_B, "pc-radar-area pc-radar-area-b");

    // Achsenbeschriftung
    metrics.forEach((metric, i) => {
        const [x, y] = pointAt(i, 1.16);
        const label = document.createElementNS(ns, "text");
        label.setAttribute("x", x.toFixed(1));
        label.setAttribute("y", y.toFixed(1));
        label.setAttribute("class", "pc-radar-label");
        label.setAttribute("text-anchor",
            x < center - 12 ? "end" : (x > center + 12 ? "start" : "middle"));
        label.setAttribute("dominant-baseline", "middle");
        label.textContent = pcShortLabel(metric.label);
        svg.appendChild(label);
    });

    wrap.appendChild(svg);

    // Legende
    const legend = make("div", "pc-legend");
    [[playerA, PC_COLOR_A], [playerB, PC_COLOR_B]].forEach(([player, color]) => {
        const item = make("div", "pc-legend-item");
        const swatch = make("span", "pc-legend-swatch");
        swatch.style.background = color;
        item.appendChild(swatch);
        item.appendChild(make("span", "", player.name || ""));
        legend.appendChild(item);
    });
    wrap.appendChild(legend);

    wrap.appendChild(make("p", "pc-radar-hint", t("playerCompare.radar.hint")));

    return wrap;
}

function pcShortLabel(label) {
    // Achsenbeschriftungen muessen auf dem Smartphone lesbar bleiben.
    return (label || "").replace(/\s+(?:pro|per)\s+90$/, "/90");
}


/* ---------- 16g. Detailvergleich ---------- */

function pcBuildMetricList(comparison, playerA, playerB) {
    const list = make("div", "pc-metrics");

    list.appendChild(make("h3", "pc-metrics-title", t("playerCompare.metrics.title")));

    (comparison.metrics || []).forEach(metric => {
        const row = make("div", "pc-metric-row");

        const head = make("div", "pc-metric-head");
        head.appendChild(make("span", "pc-metric-label", metric.label));

        const kindLabel = {
            per90: t("playerCompare.metrics.kindPer90"),
            rate: t("playerCompare.metrics.kindRate"),
            total: t("playerCompare.metrics.kindSeasonValue"),
            value: t("playerCompare.metrics.kindAverage"),
        }[metric.kind] || "";

        const badge = make("span", "pc-metric-kind", kindLabel);
        if (metric.direction === "lower_better") {
            badge.textContent = t("playerCompare.metrics.lowerBetter", { kind: kindLabel });
            badge.classList.add("pc-metric-inverted");
        }
        head.appendChild(badge);

        const info = document.createElement("button");
        info.type = "button";
        info.className = "pc-metric-info";
        info.setAttribute("aria-label", t("playerCompare.metrics.infoAria", { metric: metric.label }));
        info.textContent = "i";
        info.addEventListener("click", () => {
            const open = row.classList.toggle("pc-metric-open");
            info.setAttribute("aria-expanded", open ? "true" : "false");
        });
        head.appendChild(info);

        row.appendChild(head);
        row.appendChild(make("p", "pc-metric-description", metric.description || ""));

        // Zwei Balken, jeweils Rohwert und Perzentil.
        const bars = make("div", "pc-bars");
        [["a", metric.value_a, metric.percentile_a, PC_COLOR_A, playerA],
         ["b", metric.value_b, metric.percentile_b, PC_COLOR_B, playerB]]
        .forEach(([slot, value, percentile, color, player]) => {
            const bar = make("div", "pc-bar-row");

            const name = make("span", "pc-bar-name", player.name || slot.toUpperCase());
            bar.appendChild(name);

            const track = make("div", "pc-bar-track");
            const fill = make("div", "pc-bar-fill");
            // Ohne Perzentil bleibt der Balken leer statt bei 0 zu suggerieren,
            // der Spieler sei der schlechteste.
            fill.style.width = percentile === null ? "0%" : `${percentile}%`;
            fill.style.background = color;
            track.appendChild(fill);
            bar.appendChild(track);

            const numbers = make("span", "pc-bar-numbers");
            numbers.appendChild(make("span", "pc-bar-value", pcFormatValue(value, metric.kind)));
            // Kein "P87" mehr. Der Nutzer liest einen Rang, kein Fachkuerzel.
            const rank = make("span", "pc-bar-percentile",
                percentile === null ? "–" : `${percentile}/100`);
            rank.title = percentile === null
                ? PC_TEXT.rankUnavailable()
                : PC_TEXT.rankAvailable(percentile);
            numbers.appendChild(rank);
            bar.appendChild(numbers);

            bars.appendChild(bar);
        });

        row.appendChild(bars);
        list.appendChild(row);
    });

    return list;
}

function pcFormatValue(value, kind) {
    if (value === null || value === undefined) return "–";
    if (kind === "rate") return `${value} %`;
    if (kind === "total") return value.toLocaleString(activeIntlLocale());
    return String(value);
}


/* ---------- 16h. Zusammenfassung ---------- */

function pcBuildSummary(comparison, playerA, playerB) {
    const box = make("div", "pc-summary");
    box.appendChild(make("h3", "pc-summary-title", t("player.summary")));

    const metrics = (comparison.metrics || [])
        .filter(m => m.percentile_a !== null && m.percentile_b !== null);

    if (metrics.length === 0) {
        box.appendChild(make("p", "", t("playerCompare.summary.noReliableLead")));
        return box;
    }

    // Rein deterministisch aus den angezeigten Zahlen. Kein Modell, keine KI.
    const AHEAD = 10;   // ab 10 Perzentilpunkten sprechen wir von einem Vorsprung

    const aheadA = [];
    const aheadB = [];
    const similar = [];

    metrics.forEach(metric => {
        const diff = metric.percentile_a - metric.percentile_b;
        if (diff >= AHEAD) aheadA.push(metric);
        else if (diff <= -AHEAD) aheadB.push(metric);
        else similar.push(metric);
    });

    const nameA = playerA.name || t("playerCompare.summary.playerA");
    const nameB = playerB.name || t("playerCompare.summary.playerB");

    const line = (player, list) => {
        if (list.length === 0) return null;
        const sorted = list
            .slice()
            .sort((x, y) => Math.abs(y.percentile_a - y.percentile_b)
                          - Math.abs(x.percentile_a - x.percentile_b))
            .slice(0, 3)
            .map(m => m.label);
        return t("playerCompare.summary.ahead", {
            player,
            metrics: sorted.join(", "),
        });
    };

    const textA = line(nameA, aheadA);
    const textB = line(nameB, aheadB);

    if (textA) box.appendChild(make("p", "pc-summary-a", textA));
    if (textB) box.appendChild(make("p", "pc-summary-b", textB));

    if (similar.length > 0) {
        box.appendChild(make("p", "pc-summary-similar",
            t("playerCompare.summary.similar", {
                metrics: similar.slice(0, 4).map(m => m.label).join(", "),
            })));
    }

    if (!textA && !textB) {
        box.appendChild(make("p", "", t("playerCompare.summary.close")));
    }

    box.appendChild(make("p", "pc-summary-note", t("playerCompare.summary.note", {
        points: AHEAD,
    })));

    return box;
}


/* ---------- Verdrahtung ---------- */

["a", "b"].forEach(slot => {
    const input = pcSearchInputs[slot];
    if (!input) return;

    input.addEventListener("input", () => pcHandleInput(slot));
    input.addEventListener("keydown", (event) => pcHandleKeydown(slot, event));

    // Klick ausserhalb schliesst die Trefferliste.
    document.addEventListener("click", (event) => {
        const wrap = input.closest(".pc-search-wrap");
        if (wrap && !wrap.contains(event.target)) {
            pcRenderResults(slot, null, "hidden");
        }
    });
});

if (pcCompareBtn) {
    pcCompareBtn.addEventListener("click", pcRunComparison);
    if (pcSwapBtn) pcSwapBtn.addEventListener("click", pcSwapPlayers);
}

/**
 * Setzt den Startzustand der Positions- und Umfangsnavigation.
 *
 * WARUM DAS NICHT MEHR AUF MODULEBENE STEHT
 * -----------------------------------------
 * Genau hier entstanden die sichtbaren Rohschluessel. Die beiden Aufrufe
 * standen frueher direkt im Modulrumpf und liefen damit BEIM PARSEN von
 * script.js - lange bevor init() das await auf initI18n() erreicht hat.
 *
 * pcSetScope() schreibt den Hinweistext per textContent:
 *
 *     pcScopeNote.textContent = PC_TEXT.scopeHint[scope]();
 *
 * Zu diesem Zeitpunkt war activeTranslations noch ein leeres Objekt, t()
 * fiel auf den Schluessel zurueck, und im DOM stand woertlich
 * "player.scopeHint.club_all". applyTranslations() konnte das spaeter
 * nicht heilen: Es uebersetzt nur Elemente mit data-i18n-Attribut, und
 * dieser Text wurde imperativ gesetzt.
 *
 * Das erklaert auch, warum ausgerechnet nur diese beiden Schluessel
 * sichtbar waren - sie sind die einzigen, die so frueh imperativ
 * geschrieben werden.
 */
function pcRetranslateDynamicText() {
    if (!pcCompareBtn) return;
    // silent: es gibt noch keine Auswahl, also auch keine
    // Ruecksetzmeldung.
    pcSetPosition(pcState.position, { silent: true });
    pcSetScope(pcState.scope, { silent: true });
}


/* ---------- 16i. Plots (Scatter) ----------

   Ein Punkt = ein Spieler. Liest ausschliesslich /api/player-scatter, das
   wiederum ausschliesslich den Player Pool liest - kein Live-API-Request
   entsteht durch das Oeffnen oder Filtern dieser Ansicht.

   Bereits im Radar gewaehlte Spieler (pcState.a.player / pcState.b.player)
   werden automatisch hervorgehoben: derselbe pcState, keine Extra-Logik
   fuer den Abgleich noetig ausser dem Markieren beim Rendern.
------------------------------------------------------------------- */

const pcScatterSeasonSelect = el("pc-scatter-season");
const pcScatterXSelect = el("pc-scatter-x");
const pcScatterYSelect = el("pc-scatter-y");
const pcScatterLeaguesBox = document.querySelector(".pc-scatter-leagues");
const pcScatterMinMinutesInput = el("pc-scatter-min-minutes");
const pcScatterSearchInput = el("pc-scatter-search");
const pcScatterStatus = el("pc-scatter-status");
const pcScatterEmpty = el("pc-scatter-empty");
const pcScatterChartWrap = el("pc-scatter-chart-wrap");
const pcScatterChart = el("pc-scatter-chart");
const pcScatterLegend = el("pc-scatter-legend");
const pcScatterDetail = el("pc-scatter-detail");
const pcScatterScopeNav = document.querySelector(".pc-scatter-scope-nav");
const pcScatterScopeNote = el("pc-scatter-scope-note");
const pcScatterRunBtn = el("pc-scatter-run");

// Zuletzt geladene Metadaten. Die Detailkarte braucht sie, um Achsennamen
// und Wettbewerbsumfang anzuzeigen, ohne dafuer erneut zu laden.
let pcScatterLastScopeLabel = "";

// Liga-Farben. Eigenstaendige FootSim-Palette, keine DataMB-Uebernahme.
// Bewusst keine Gruen/Rot-Paarung (Farbfehlsichtigkeit).
const PC_LEAGUE_COLORS = {
    bl1: "#e63946",
    pl:  "#457b9d",
    pd:  "#f4a261",
    sa:  "#2a9d8f",
    fl1: "#9b5de5",
};

const PC_SCATTER_WARN_THRESHOLD = 800;

// Anzeigenamen fuer Liga-Codes im Scatter-Frontend.
const COMPARE_LEAGUE_LABELS_FRONTEND = {
    bl1: "Bundesliga", pl: "Premier League", pd: "LaLiga",
    sa: "Serie A", fl1: "Ligue 1",
};

// Zwischenspeicher der zuletzt geladenen Achsen-Metadaten, damit die
// Suchhervorhebung ohne einen zweiten Netzwerk-Request neu zeichnen kann.
let pcScatterLastXMeta = null;
let pcScatterLastYMeta = null;

/**
 * Einmalige Initialisierung der Plot-Ansicht.
 *
 * Laedt NUR den Achsenkatalog, KEINE Punkte. Der Plot selbst entsteht erst
 * durch den Startbutton - so ist fuer den Nutzer eindeutig, wann geladen
 * wurde. Der Achsenkatalog kommt aus derselben Route, kostet aber keinen
 * API-Request (der Endpunkt liest nur den Pool).
 */
async function pcScatterInit() {
    pcState.scatter.ready = true;

    pcScatterSetScope(pcState.scatter.scope, { silent: true });
    pcScatterUpdateButton();

    try {
        const data = await pcScatterFetch();
        pcState.scatter.axes = data.axes || [];
        pcScatterFillAxisSelect(pcScatterXSelect, pcState.scatter.x);
        pcScatterFillAxisSelect(pcScatterYSelect, pcState.scatter.y);

        // Nur die Datenlage melden, noch nichts zeichnen.
        pcScatterReportPoolState(data);
    } catch (error) {
        pcScatterStatus.textContent = PC_TEXT.scatterError();
    }
}

/**
 * Beschriftung und Zustand des Startbuttons.
 *
 *   noch kein Plot        -> "Plot erstellen"
 *   Plot da, Filter gleich -> "Plot aktualisieren", deaktiviert
 *   Plot da, Filter neu    -> "Plot aktualisieren", aktiv + Hinweis
 *   laedt gerade           -> deaktiviert, Ladebeschriftung
 */
function pcScatterUpdateButton() {
    if (!pcScatterRunBtn) return;

    const { hasPlot, dirty, busy } = pcState.scatter;

    if (busy) {
        pcScatterRunBtn.textContent = PC_TEXT.scatterLoading();
        pcScatterRunBtn.disabled = true;
        pcScatterRunBtn.setAttribute("aria-busy", "true");
        return;
    }

    pcScatterRunBtn.removeAttribute("aria-busy");
    pcScatterRunBtn.textContent = hasPlot ? PC_TEXT.scatterUpdate() : PC_TEXT.scatterCreate();
    // Ohne Aenderung gaebe ein erneuter Klick exakt dasselbe Bild.
    pcScatterRunBtn.disabled = hasPlot && !dirty;
    pcScatterRunBtn.classList.toggle("pc-scatter-run-dirty", hasPlot && dirty);
}

/**
 * Markiert die aktuelle Punktwolke als veraltet.
 *
 * Wird von jedem Filter aufgerufen. Vor dem ersten Plot passiert nichts
 * Sichtbares - dort steht ohnehin "Plot erstellen".
 */
function pcScatterMarkDirty() {
    if (!pcState.scatter.ready) return;
    pcState.scatter.dirty = true;
    if (pcState.scatter.hasPlot) {
        pcScatterStatus.textContent = PC_TEXT.scatterFiltersChanged();
        if (pcScatterChartWrap) pcScatterChartWrap.classList.add("pc-scatter-stale");
    }
    pcScatterUpdateButton();
}

/** Meldet die Datenlage, ohne zu zeichnen (Initialisierung). */
function pcScatterReportPoolState(data) {
    if (!data.used_leagues || data.used_leagues.length === 0) {
        pcScatterStatus.textContent = PC_TEXT.scatterPoolMissing();
    } else if (!data.pool_complete) {
        const missing = (data.missing_leagues || [])
            .map(code => COMPARE_LEAGUE_LABELS_FRONTEND[code] || code).join(", ");
        pcScatterStatus.textContent = PC_TEXT.scatterPoolPartial(missing);
    } else {
        pcScatterStatus.textContent = "";
    }
}

function pcScatterFillAxisSelect(select, selectedKey) {
    if (!select) return;
    select.innerHTML = "";
    pcState.scatter.axes.forEach(axis => {
        const option = document.createElement("option");
        option.value = axis.key;
        option.textContent = axis.label;
        if (axis.key === selectedKey) option.selected = true;
        select.appendChild(option);
    });
}

/**
 * Wettbewerbsumfang im Plot setzen.
 *
 * Aendert nur, aus welchem Wettbewerbsumfang die Achsenwerte stammen -
 * dieselbe Logik wie im Radar, aber mit eigener Auswahl je Ansicht.
 * Loest keinen zusaetzlichen API-Request aus: der Pool haelt je Scope
 * bereits eine eigene Kennzahlenmenge bereit.
 */
function pcScatterSetScope(scope, options) {
    const silent = options && options.silent;
    if (pcState.scatter.scope === scope && !silent) return;

    pcState.scatter.scope = scope;

    if (pcScatterScopeNav) {
        pcScatterScopeNav.querySelectorAll(".pc-scope-btn").forEach(button => {
            const active = button.dataset.scope === scope;
            button.classList.toggle("active", active);
            button.setAttribute("aria-checked", active ? "true" : "false");
            button.tabIndex = active ? 0 : -1;
        });
    }

    if (pcScatterScopeNote) {
        const hint = PC_TEXT.scopeHint[scope];
        pcScatterScopeNote.textContent = hint ? hint() : "";
    }

    if (!silent) pcScatterMarkDirty();
}

if (pcScatterScopeNav) {
    pcScatterScopeNav.addEventListener("click", (event) => {
        const button = event.target.closest(".pc-scope-btn");
        if (!button || button.disabled) return;
        pcScatterSetScope(button.dataset.scope);
    });

    pcScatterScopeNav.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;

        // Deaktivierte Scopes ueberspringen - siehe Radar-Navigation.
        const buttons = Array.from(pcScatterScopeNav.querySelectorAll(".pc-scope-btn"))
            .filter(b => !b.disabled);
        if (!buttons.length) return;

        const current = buttons.findIndex(b => b.dataset.scope === pcState.scatter.scope);
        let next = current < 0 ? 0 : current;

        if (event.key === "ArrowLeft")  next = (next - 1 + buttons.length) % buttons.length;
        if (event.key === "ArrowRight") next = (next + 1) % buttons.length;
        if (event.key === "Home")       next = 0;
        if (event.key === "End")        next = buttons.length - 1;

        event.preventDefault();
        pcScatterSetScope(buttons[next].dataset.scope);
        buttons[next].focus();
    });
}


/**
 * Dezenter Ladezustand.
 *
 * Ohne sichtbares Feedback wirkt die automatische Aktualisierung wie
 * "es passiert nichts" - genau der Eindruck, der einen ueberfluessigen
 * "Plot erstellen"-Button noetig erscheinen liesse. Das Chart bleibt
 * sichtbar und wird nur abgeblendet, damit der Nutzer den Bezug behaelt.
 */
function pcScatterSetBusy(busy) {
    if (pcScatterChartWrap) {
        pcScatterChartWrap.classList.toggle("pc-scatter-busy", busy);
    }
    if (pcScatterStatus) {
        pcScatterStatus.classList.toggle("pc-scatter-status-busy", busy);
    }
}


/** Baut die Query-Parameter aus dem aktuellen (geteilten) Zustand. */
function pcScatterBuildUrl() {
    const params = new URLSearchParams({
        x: pcState.scatter.x,
        y: pcState.scatter.y,
        season: pcState.scatter.season || "",
        min_minutes: pcState.scatter.minMinutes,
        leagues: pcState.scatter.leagues.join(","),
        scope: pcState.scatter.scope,
    });
    if (pcState.position) params.set("position", pcState.position);
    return `/api/player-scatter?${params.toString()}`;
}

async function pcScatterFetch() {
    const data = await fetchJson(pcScatterBuildUrl());
    return {
        ...data,
        axes: (data.axes || []).map(localizedMetric),
        x: localizedMetric(data.x),
        y: localizedMetric(data.y),
        position_label: translatedPosition(data.position, data.position_label || ""),
        scope_label: translatedScope(data.scope, data.scope_label || ""),
        scopes: (data.scopes || []).map((scope) => ({
            ...scope,
            label: translatedScope(scope.key, scope.label || ""),
            hint: activeLocale === "en" ? "" : (scope.hint || ""),
        })),
        positions: (data.positions || []).map((position) => ({
            ...position,
            label: translatedPosition(position.key, position.label || ""),
        })),
    };
}

/**
 * Laedt die Punktwolke. Wird ausschliesslich vom Startbutton ausgeloest.
 *
 * Doppelklickschutz ueber pcState.scatter.busy: ein zweiter Klick waehrend
 * eines laufenden Requests wird verworfen, statt einen zweiten Request zu
 * starten. Zusaetzlich entwertet ein Request-Zaehler veraltete Antworten.
 */
async function pcScatterLoad() {
    if (!pcState.scatter.ready) return;
    if (pcState.scatter.busy) return;

    const requestId = ++pcState.scatter.requestId;

    pcState.scatter.busy = true;
    pcScatterSetBusy(true);
    pcScatterUpdateButton();
    pcScatterStatus.textContent = PC_TEXT.scatterLoading();

    try {
        const data = await pcScatterFetch();
        if (requestId !== pcState.scatter.requestId) return;

        pcScatterRenderResult(data);
        pcState.scatter.hasPlot = (data.points || []).length > 0;
        pcState.scatter.dirty = false;
        if (pcScatterChartWrap) pcScatterChartWrap.classList.remove("pc-scatter-stale");
    } catch (error) {
        if (requestId !== pcState.scatter.requestId) return;
        pcScatterStatus.textContent = PC_TEXT.scatterError();
    } finally {
        if (requestId === pcState.scatter.requestId) {
            pcState.scatter.busy = false;
            pcScatterSetBusy(false);
            pcScatterUpdateButton();
        }
    }
}

/**
 * Stellt das Ergebnis dar und unterscheidet dabei klar zwischen den
 * moeglichen Datenlagen. Eine pauschale Meldung wie "keine Daten" wuerde
 * verschweigen, ob der Pool fehlt, unvollstaendig ist oder schlicht kein
 * Spieler die Filter erfuellt - drei voellig verschiedene Ursachen mit
 * drei verschiedenen Loesungen.
 */
function pcScatterRenderResult(data) {
    const points = data.points || [];
    pcState.scatter.points = points;
    pcScatterLastXMeta = data.x;
    pcScatterLastYMeta = data.y;
    pcScatterLastScopeLabel = data.scope_label || "";

    const poolMissing = !data.used_leagues || data.used_leagues.length === 0;

    if (points.length === 0) {
        hide(pcScatterChartWrap);
        show(pcScatterEmpty);
        hide(pcScatterDetail);

        if (poolMissing) {
            pcScatterStatus.textContent = PC_TEXT.scatterPoolMissing();
            pcScatterSetEmptyText(PC_TEXT.scatterPoolMissing());
        } else {
            const text = PC_TEXT.scatterNoMatch(data.min_minutes);
            pcScatterStatus.textContent = text;
            pcScatterSetEmptyText(text);
        }
        return;
    }

    hide(pcScatterEmpty);
    show(pcScatterChartWrap);

    if (!data.pool_complete) {
        const missing = (data.missing_leagues || [])
            .map(code => COMPARE_LEAGUE_LABELS_FRONTEND[code] || code).join(", ");
        pcScatterStatus.textContent = PC_TEXT.scatterPoolPartial(missing);
    } else if (points.length > PC_SCATTER_WARN_THRESHOLD) {
        pcScatterStatus.textContent = PC_TEXT.scatterManyPoints(points.length);
    } else {
        pcScatterStatus.textContent = PC_TEXT.scatterReady(points.length);
    }

    // Eine offene Karte gehoert zu den alten Punkten und waere nach dem
    // Neuzeichnen inhaltlich falsch.
    pcScatterHideDetail();

    renderScatterPoints(pcScatterChart, points, data.x, data.y);
    pcScatterRenderLegend(points);
}

/** Text im Leerzustand austauschen, ohne die Struktur neu zu bauen. */
function pcScatterSetEmptyText(text) {
    if (!pcScatterEmpty) return;
    const paragraph = pcScatterEmpty.querySelector("p");
    if (paragraph) paragraph.textContent = text;
}

function pcScatterRenderLegend(points) {
    pcScatterLegend.innerHTML = "";
    const usedLeagues = Array.from(new Set(points.map(p => p.league)));
    usedLeagues.forEach(code => {
        const item = make("span", "pc-scatter-legend-item");
        const dot = make("span", "pc-scatter-legend-dot");
        dot.style.background = PC_LEAGUE_COLORS[code] || "#888";
        item.appendChild(dot);
        item.appendChild(make("span", "", COMPARE_LEAGUE_LABELS_FRONTEND[code] || code));
        pcScatterLegend.appendChild(item);
    });
}

/**
 * Zeichnet die Punktwolke als SVG.
 *
 * Eigene, austauschbare Funktion: ein spaeterer Wechsel auf Canvas
 * (bei sehr grossen Punktzahlen) betrifft nur diese eine Funktion, nicht
 * Filterlogik, Endpunkt oder Zustand.
 */
function renderScatterPoints(container, points, xMeta, yMeta) {
    container.innerHTML = "";

    const size = 460;
    const padLeft = 52, padRight = 20, padTop = 20, padBottom = 52;
    const ns = "http://www.w3.org/2000/svg";

    const xs = points.map(p => p.x);
    const ys = points.map(p => p.y);

    // Etwas Luft an den Raendern, damit Punkte nicht auf der Achse kleben.
    const rawXMin = Math.min(...xs), rawXMax = Math.max(...xs);
    const rawYMin = Math.min(...ys), rawYMax = Math.max(...ys);
    const xPad = (rawXMax - rawXMin) * 0.06 || 0.5;
    const yPad = (rawYMax - rawYMin) * 0.06 || 0.5;
    const xMin = rawXMin - xPad, xMax = rawXMax + xPad;
    const yMin = rawYMin - yPad, yMax = rawYMax + yPad;
    const xSpan = (xMax - xMin) || 1;
    const ySpan = (yMax - yMin) || 1;

    const plotW = size - padLeft - padRight;
    const plotH = size - padTop - padBottom;
    const toX = v => padLeft + ((v - xMin) / xSpan) * plotW;
    const toY = v => size - padBottom - ((v - yMin) / ySpan) * plotH;

    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    svg.setAttribute("class", "pc-scatter-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", t("plots.scatterAria", {
        x: xMeta.label,
        y: yMeta.label,
        count: points.length,
    }));

    const add = (tag, attrs, cls) => {
        const node = document.createElementNS(ns, tag);
        Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
        if (cls) node.setAttribute("class", cls);
        svg.appendChild(node);
        return node;
    };

    // Zahl kompakt beschriften: Quoten ohne Nachkommastellen, kleine
    // Per-90-Werte mit zwei - sonst stehen dort unlesbare Ziffernketten.
    const tickLabel = (value, meta) => {
        if (meta && meta.kind === "rate") return `${Math.round(value)}`;
        if (Math.abs(value) >= 100) return String(Math.round(value));
        if (Math.abs(value) >= 10) return value.toFixed(1);
        return value.toFixed(2);
    };

    // --- Raster und Skalen (5 Schritte je Achse) ---
    const TICKS = 5;
    for (let i = 0; i <= TICKS; i++) {
        const ratio = i / TICKS;

        const gx = padLeft + ratio * plotW;
        add("line", { x1: gx, x2: gx, y1: padTop, y2: size - padBottom }, "pc-scatter-grid");
        const xt = add("text", {
            x: gx, y: size - padBottom + 16, "text-anchor": "middle",
        }, "pc-scatter-tick");
        xt.textContent = tickLabel(xMin + ratio * xSpan, xMeta);

        const gy = size - padBottom - ratio * plotH;
        add("line", { x1: padLeft, x2: size - padRight, y1: gy, y2: gy }, "pc-scatter-grid");
        const yt = add("text", {
            x: padLeft - 8, y: gy + 3.5, "text-anchor": "end",
        }, "pc-scatter-tick");
        yt.textContent = tickLabel(yMin + ratio * ySpan, yMeta);
    }

    // --- Achsenlinien ---
    add("line", { x1: padLeft, x2: size - padRight, y1: size - padBottom, y2: size - padBottom },
        "pc-scatter-axis-line");
    add("line", { x1: padLeft, x2: padLeft, y1: padTop, y2: size - padBottom },
        "pc-scatter-axis-line");

    // --- Orientierungslinie (lineare Regression) ---
    // Nur ab 8 Punkten: darunter ist eine Trendlinie statistisch bedeutungslos
    // und wuerde einen Zusammenhang suggerieren, den die Daten nicht hergeben.
    if (points.length >= 8) {
        const n = points.length;
        const sumX = xs.reduce((a, b) => a + b, 0);
        const sumY = ys.reduce((a, b) => a + b, 0);
        const meanX = sumX / n, meanY = sumY / n;
        let num = 0, den = 0;
        for (let i = 0; i < n; i++) {
            num += (xs[i] - meanX) * (ys[i] - meanY);
            den += (xs[i] - meanX) ** 2;
        }
        if (den > 0) {
            const slope = num / den;
            const intercept = meanY - slope * meanX;
            const y1 = slope * xMin + intercept;
            const y2 = slope * xMax + intercept;
            // Nur zeichnen, wenn die Linie im sichtbaren Bereich verlaeuft.
            if (Number.isFinite(y1) && Number.isFinite(y2)) {
                add("line", {
                    x1: toX(xMin), y1: Math.max(padTop, Math.min(size - padBottom, toY(y1))),
                    x2: toX(xMax), y2: Math.max(padTop, Math.min(size - padBottom, toY(y2))),
                }, "pc-scatter-trend");
            }
        }
    }

    // --- Hervorhebungen aus dem Radar und aus der optionalen Suche ---
    const slotAId = pcState.a.player ? String(pcState.a.player.player_id) : null;
    const slotBId = pcState.b.player ? String(pcState.b.player.player_id) : null;
    const searchHits = pcState.scatter.highlighted;

    // Markierte Punkte zuletzt zeichnen, damit sie nicht verdeckt werden.
    const ordered = points.slice().sort((p, q) => {
        const rank = pt => {
            const id = String(pt.id);
            if (id === slotAId || id === slotBId) return 2;
            if (searchHits.has(id)) return 1;
            return 0;
        };
        return rank(p) - rank(q);
    });

    const labelled = [];

    ordered.forEach(point => {
        const id = String(point.id);
        const cx = toX(point.x);
        const cy = toY(point.y);

        const isA = id === slotAId;
        const isB = id === slotBId;
        const isSearch = searchHits.has(id);

        let radius = 4.5;
        let fill = PC_LEAGUE_COLORS[point.league] || "#8a8a8a";
        let extraClass = "";

        if (isA)          { fill = PC_COLOR_A; radius = 7.5; extraClass = " pc-scatter-point-highlight"; }
        else if (isB)     { fill = PC_COLOR_B; radius = 7.5; extraClass = " pc-scatter-point-highlight"; }
        else if (isSearch){ radius = 6.5; extraClass = " pc-scatter-point-search"; }

        const circle = add("circle", {
            cx: cx.toFixed(1), cy: cy.toFixed(1), r: radius, fill,
            tabindex: "0", role: "button",
            "aria-label": t("plots.pointAria", {
                name: point.name || t("player.unknown"),
                team: point.team || "",
                xLabel: xMeta.label,
                x: point.x,
                yLabel: yMeta.label,
                y: point.y,
            }),
        }, "pc-scatter-point" + extraClass);
        circle.dataset.pointId = id;

        const open = (event) => {
            if (event) event.stopPropagation();
            pcScatterShowDetail(point, xMeta, yMeta);
        };
        circle.addEventListener("click", open);
        circle.addEventListener("touchstart", (e) => { e.preventDefault(); open(e); },
                                { passive: false });
        circle.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(e); }
        });

        if (isA || isB || isSearch) labelled.push({ point, cx, cy });
    });

    // --- Namen an markierten Punkten ---
    // Nur bei wenigen Markierungen, sonst ueberlagern sich die Beschriftungen.
    if (labelled.length > 0 && labelled.length <= 6) {
        labelled.forEach(({ point, cx, cy }) => {
            const rightSide = cx < size * 0.62;
            const text = add("text", {
                x: rightSide ? cx + 11 : cx - 11,
                y: cy + 4,
                "text-anchor": rightSide ? "start" : "end",
            }, "pc-scatter-point-label");
            text.textContent = point.name;
        });
    }

    // --- Achsenbeschriftung ---
    const xLabel = add("text", {
        x: padLeft + plotW / 2, y: size - 8, "text-anchor": "middle",
    }, "pc-scatter-axis-label");
    xLabel.textContent = xMeta.label;

    const yLabel = add("text", {
        x: 14, y: padTop + plotH / 2, "text-anchor": "middle",
        transform: `rotate(-90 14 ${padTop + plotH / 2})`,
    }, "pc-scatter-axis-label");
    yLabel.textContent = yMeta.label;

    // Klick auf freie Flaeche schliesst die Detailkarte.
    svg.addEventListener("click", () => hide(pcScatterDetail));

    container.appendChild(svg);
}

/**
 * Detailkarte eines Spielerpunktes.
 *
 * Bleibt offen, bis der Nutzer sie schliesst, ausserhalb klickt oder Escape
 * drueckt - kein automatisches Verschwinden. Auf Mobil wird sie per CSS zum
 * festen Sheet ueber der Bottom-Navigation, damit der Finger sie nicht
 * verdeckt.
 */
function pcScatterShowDetail(point, xMeta, yMeta) {
    if (!pcScatterDetail) return;

    pcScatterDetail.innerHTML = "";
    pcState.scatter.openPointId = String(point.id);

    // Farbakzent oben: dieselbe Ligafarbe wie der Punkt, damit der Bezug
    // zwischen Karte und Punktwolke sofort erkennbar ist.
    const accent = make("span", "pc-scatter-detail-accent");
    accent.style.background = PC_LEAGUE_COLORS[point.league] || "#8a8a8a";
    pcScatterDetail.appendChild(accent);

    const close = make("button", "pc-scatter-detail-close", "\u00d7");
    close.type = "button";
    close.setAttribute("aria-label", t("plots.closeDetail"));
    close.addEventListener("click", (event) => {
        event.stopPropagation();
        pcScatterHideDetail();
    });
    pcScatterDetail.appendChild(close);

    pcScatterDetail.appendChild(make("h3", "pc-scatter-detail-name", point.name));

    const clubLine = [
        point.team,
        COMPARE_LEAGUE_LABELS_FRONTEND[point.league] || point.league,
    ].filter(Boolean).join(" \u00b7 ");
    pcScatterDetail.appendChild(make("p", "pc-scatter-detail-meta", clubLine));

    const personLine = [
        translatedPosition(point.position, point.position),
        point.age ? t("plots.age", { count: point.age }) : null,
    ].filter(Boolean).join(" \u00b7 ");
    if (personLine) {
        pcScatterDetail.appendChild(make("p", "pc-scatter-detail-meta", personLine));
    }

    // Die beiden Achsenwerte als eigene, klar gelesene Zeilen.
    const values = make("div", "pc-scatter-detail-values");
    [[xMeta, point.x], [yMeta, point.y]].forEach(([meta, value]) => {
        const row = make("div", "pc-scatter-detail-value-row");
        row.appendChild(make("span", "pc-scatter-detail-value-label", meta.label));
        row.appendChild(make("span", "pc-scatter-detail-value-number", pcFormatNumber(value)));
        values.appendChild(row);
    });
    pcScatterDetail.appendChild(values);

    const footer = make("div", "pc-scatter-detail-footer");
    footer.appendChild(make("span", "",
        t("plots.minutes", { count: Number(point.minutes).toLocaleString(activeIntlLocale()) })));
    if (pcScatterLastScopeLabel) {
        footer.appendChild(make("span", "pc-scatter-detail-scope", pcScatterLastScopeLabel));
    }
    pcScatterDetail.appendChild(footer);

    show(pcScatterDetail);
    pcScatterDetail.setAttribute("aria-hidden", "false");
    close.focus();
}

function pcScatterHideDetail() {
    if (!pcScatterDetail) return;
    hide(pcScatterDetail);
    pcScatterDetail.setAttribute("aria-hidden", "true");
    pcState.scatter.openPointId = null;
}

/** Zahlen einheitlich und lesbar formatieren. */
function pcFormatNumber(value) {
    if (value === null || value === undefined) return "\u2013";
    if (Number.isInteger(value)) return String(value);
    return Number(value).toLocaleString(activeIntlLocale(), {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
}

// Escape schliesst die Detailkarte, wie bei jedem Dialog erwartet.
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && pcScatterDetail
        && !pcScatterDetail.classList.contains("hidden")) {
        pcScatterHideDetail();
    }
});

// Klick ausserhalb schliesst ebenfalls. Der Klick auf einen Punkt stoppt
// die Weitergabe, sonst wuerde die Karte sofort wieder zugehen.
document.addEventListener("click", (event) => {
    if (!pcScatterDetail || pcScatterDetail.classList.contains("hidden")) return;
    if (pcScatterDetail.contains(event.target)) return;
    pcScatterHideDetail();
});

if (pcScatterXSelect) {
    pcScatterXSelect.addEventListener("change", () => {
        if (pcScatterXSelect.value === pcState.scatter.y) {
            // X und Y duerfen nie identisch sein: die andere Achse weicht aus.
            const fallback = pcState.scatter.axes.find(a => a.key !== pcScatterXSelect.value);
            if (fallback) {
                pcState.scatter.y = fallback.key;
                pcScatterFillAxisSelect(pcScatterYSelect, pcState.scatter.y);
            }
        }
        pcState.scatter.x = pcScatterXSelect.value;
        pcScatterMarkDirty();
    });
}

if (pcScatterYSelect) {
    pcScatterYSelect.addEventListener("change", () => {
        if (pcScatterYSelect.value === pcState.scatter.x) {
            const fallback = pcState.scatter.axes.find(a => a.key !== pcScatterYSelect.value);
            if (fallback) {
                pcState.scatter.x = fallback.key;
                pcScatterFillAxisSelect(pcScatterXSelect, pcState.scatter.x);
            }
        }
        pcState.scatter.y = pcScatterYSelect.value;
        pcScatterMarkDirty();
    });
}

if (pcScatterLeaguesBox) {
    pcScatterLeaguesBox.addEventListener("click", (event) => {
        const chip = event.target.closest(".pc-scatter-league-chip");
        if (!chip) return;

        const code = chip.dataset.league;
        const active = pcState.scatter.leagues.includes(code);

        if (active) {
            // Mindestens eine Liga muss aktiv bleiben.
            if (pcState.scatter.leagues.length === 1) return;
            pcState.scatter.leagues = pcState.scatter.leagues.filter(c => c !== code);
        } else {
            pcState.scatter.leagues.push(code);
        }
        chip.classList.toggle("active", !active);
        chip.setAttribute("aria-pressed", String(!active));
        pcScatterMarkDirty();
    });
}

if (pcScatterMinMinutesInput) {
    // Kein Request waehrend des Tippens: der Wert wird erst beim Klick auf
    // den Startbutton angewendet. Negative oder unsinnige Eingaben werden
    // hier bereits auf einen gueltigen Wert gezogen.
    pcScatterMinMinutesInput.addEventListener("input", () => {
        const value = parseInt(pcScatterMinMinutesInput.value, 10);
        pcState.scatter.minMinutes = Number.isFinite(value) && value >= 0 ? value : 0;
        pcScatterMarkDirty();
    });

    pcScatterMinMinutesInput.addEventListener("blur", () => {
        // Leeres oder ungueltiges Feld sichtbar auf den tatsaechlich
        // verwendeten Wert zuruecksetzen, damit Anzeige und Zustand
        // nicht auseinanderlaufen.
        pcScatterMinMinutesInput.value = String(pcState.scatter.minMinutes);
    });
}

// Der Startbutton ist der einzige Ausloeser fuer das Laden der Punktwolke.
if (pcScatterRunBtn) {
    pcScatterRunBtn.addEventListener("click", () => {
        if (pcState.scatter.busy) return;
        pcScatterLoad();
    });
}

// Optionale Spielersuche: markiert nur bereits geladene Punkte neu.
// Erzeugt selbst KEINEN Plot und loest keinen Request aus.
if (pcScatterSearchInput) {
    pcScatterSearchInput.addEventListener("input", () => {
        clearTimeout(pcState.scatter.searchTimer);
        const query = pcScatterSearchInput.value.trim().toLowerCase();

        pcState.scatter.searchTimer = setTimeout(() => {
            pcState.scatter.highlighted = new Set(
                query.length < 2
                    ? []
                    : pcState.scatter.points
                          .filter(p => (p.name || "").toLowerCase().includes(query))
                          .map(p => String(p.id))
            );

            // Nur neu zeichnen, kein Netzwerkzugriff.
            if (pcState.scatter.points.length && pcScatterLastXMeta && pcScatterLastYMeta) {
                renderScatterPoints(
                    pcScatterChart, pcState.scatter.points,
                    pcScatterLastXMeta, pcScatterLastYMeta,
                );
            }
        }, 250);
    });
}


/* ---------- 16c. LIVE (Block LIVE A + A-Politur) ----------

   Tagesuebersicht echter Spiele, nach Wettbewerb gruppiert. Holt alles
   von /api/live-matches; dieses Modul kennt weder API-Football noch
   irgendeinen Schluessel.

   Datumsnavigation:
     - liveState.selectedDate ist die einzige Quelle der Wahrheit fuer
       den gewaehlten Tag (absolutes Datum, nicht "Versatz zu heute").
     - Der Tageschip-Streifen (.live-date-strip) ist ein natives,
       horizontal scrollbares Element mit CSS scroll-snap. Ein Swipe
       darueber ist deshalb einfach Browser-Scrolling, kein eigener
       Touch-Gesten-Code - genau deshalb kann er die vertikale
       Seiten-Navigation nicht stoeren. liveHandleStripSettle() erkennt
       nur, WELCHER Chip nach dem Scrollen in der Mitte steht.
     - Der Kalender ist ein natives <input type="date">, nur visuell
       versteckt und ueber einen Knopf ausgeloest (showPicker()/click()).

   Auto-Refresh:
     - liveScheduleAutoRefresh() ist die einzige Stelle, die den Timer
       startet oder stoppt, und raeumt vorher IMMER den alten auf. Es
       kann also nie zwei parallele Timer geben.
     - Voraussetzung ist in jedem Moment: Bereich ist "live", gewaehlter
       Tag ist heute, mindestens ein Spiel laeuft, Tab ist sichtbar. Faellt
       eine Bedingung weg, wird sofort gestoppt (setActiveArea() beim
       Verlassen, liveSetSelectedDate() bei Tageswechsel, das
       visibilitychange-Handling weiter unten, oder die naechste
       Bedingungspruefung nach einem Ladevorgang).

   Der Tag wird bewusst clientseitig in Europe/Berlin berechnet und als
   fertiges Datum an die Route geschickt. Wuerde jeder Client sein
   lokales Datum schicken, haetten Nutzer ausserhalb Deutschlands einen
   anderen Cache-Key fuer denselben Spieltag - der serverseitige Cache
   waere fuer sie wirkungslos.
------------------------------------------------------------------- */

const liveHeading      = el("live-heading");
const liveDateLabel    = el("live-date-label");
const liveStatus       = el("live-status");
const liveGroups       = el("live-groups");
const liveEmpty        = el("live-empty");
const liveDateStrip    = el("live-date-strip");
const livePrevDayBtn   = el("live-prev-day");
const liveNextDayBtn   = el("live-next-day");
const liveCalendarBtn  = el("live-calendar-btn");
const liveCalendarInput = el("live-calendar-input");

// Zwischen 45 und 60 Sekunden gefordert; deckt sich mit der kurzen
// Server-TTL fuer laufende Spiele (TTL_LIVE_MATCHES_INPLAY, 45s) - ein
// kuerzeres Intervall wuerde ueberwiegend denselben Cache-Eintrag erneut
// abrufen, ein deutlich laengeres liesse den Spielstand sichtbar hinken.
const LIVE_REFRESH_INTERVAL_MS = 50000;

// Chips vor und nach dem gewaehlten Tag im Streifen. 3 ergibt 7 Chips -
// genug zum Swipen, ohne dass die Zeile auf schmalen Geraeten ueberladen wirkt.
const LIVE_STRIP_RADIUS_DAYS = 3;

// Wartezeit nach dem letzten Scroll-Event, bevor der Streifen als
// "zur Ruhe gekommen" gilt. Kein scrollend-Event noetig (Browsersupport
// dafuer ist nicht durchgehend gegeben) - ein debounce reicht.
const LIVE_STRIP_SETTLE_DELAY_MS = 150;

/** Heutiges Datum in Europe/Berlin als YYYY-MM-DD ("en-CA" liefert genau dieses Format). */
function liveBerlinToday() {
    return new Intl.DateTimeFormat("en-CA", {
        timeZone: "Europe/Berlin",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).format(new Date());
}

/**
 * Datum, das gegenueber einem gegebenen Tag um eine Zahl Tage verschoben ist.
 *
 * Der Umweg ueber Date.UTC ist Absicht: ein direkter new Date(y, m, d)
 * wuerde in der lokalen Zone rechnen und an Zeitumstellungstagen um
 * einen Tag danebenliegen.
 */
function liveShiftDate(isoDate, days) {
    const [year, month, day] = isoDate.split("-").map(Number);
    const shifted = new Date(Date.UTC(year, month - 1, day + days));
    return shifted.toISOString().slice(0, 10);
}

/** Ganzzahliger Tagesabstand von isoDate zum heutigen Tag in Europe/Berlin. */
function liveDaysFromToday(isoDate) {
    const msPerDay = 24 * 60 * 60 * 1000;
    const today = new Date(`${liveBerlinToday()}T00:00:00Z`);
    const target = new Date(`${isoDate}T00:00:00Z`);
    return Math.round((target - today) / msPerDay);
}

/** Datum als "Mo, 11.08.2026" fuer die Zeile unter der Datumsnavigation. */
function liveFormatDateLabel(isoDate) {
    const [year, month, day] = isoDate.split("-").map(Number);
    const value = new Date(Date.UTC(year, month - 1, day));
    return new Intl.DateTimeFormat(activeIntlLocale(), {
        timeZone: "UTC",
        weekday: "short",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
    }).format(value);
}

/** Kurzer Wochentag fuer einen Chip, z. B. "Mo". */
function liveWeekdayShort(isoDate) {
    const [year, month, day] = isoDate.split("-").map(Number);
    const value = new Date(Date.UTC(year, month - 1, day));
    return new Intl.DateTimeFormat(activeIntlLocale(), { timeZone: "UTC", weekday: "short" }).format(value);
}

/** Tag und Monat fuer einen Chip, z. B. "11. Aug". */
function liveChipDayLabel(isoDate) {
    const [year, month, day] = isoDate.split("-").map(Number);
    const value = new Date(Date.UTC(year, month - 1, day));
    return new Intl.DateTimeFormat(activeIntlLocale(), { timeZone: "UTC", day: "numeric", month: "short" }).format(value);
}

/** Ueberschrift passend zum gewaehlten Tag - relativ nah an heute, sonst mit Datum. */
function liveHeadingText(isoDate) {
    const diff = liveDaysFromToday(isoDate);
    if (diff === 0) return t("live.today");
    if (diff === -1) return t("live.yesterday");
    if (diff === 1) return t("live.tomorrow");
    return t("live.onDate", { date: liveFormatDateLabel(isoDate) });
}

function liveSetStatus(text) {
    if (liveStatus) liveStatus.textContent = text;
}

/** Spielminute inklusive Nachspielzeit: 90+3'. */
function liveMinuteText(match) {
    if (match.elapsed === null || match.elapsed === undefined) return null;
    if (match.elapsed_extra) return `${match.elapsed}+${match.elapsed_extra}'`;
    return `${match.elapsed}'`;
}

function liveBuildTeamRow(name, logo, score) {
    const row = make("div", "live-team");

    if (logo) row.appendChild(crest(logo, "live-team-logo"));

    row.appendChild(make("span", "live-team-name", name || t("player.unknown")));

    // Vor dem Anpfiff und bei abgesagten Spielen gibt es keinen Stand.
    const hasScore = score !== null && score !== undefined;
    row.appendChild(make("span", "live-team-score", hasScore ? String(score) : "–"));

    return row;
}

/**
 * Rechte Spalte der Karte: je nach Phase Anstosszeit, Live-Minute oder
 * Status. Laufende Spiele bekommen zusaetzlich ein deutliches Abzeichen.
 */
function liveBuildMeta(match) {
    const meta = make("div", "live-match-meta");

    if (match.phase === "live") {
        meta.appendChild(make("span", "live-badge", t("matchCenter.live")));

        const minute = liveMinuteText(match);
        if (minute) meta.appendChild(make("span", "live-minute", minute));
        else meta.appendChild(make("span", "live-meta-note", localizedLiveStatus(match)));

        return meta;
    }

    if (match.phase === "paused") {
        meta.appendChild(make("span", "live-badge", t("matchCenter.live")));
        meta.appendChild(make("span", "live-meta-note", localizedLiveStatus(match)));
        return meta;
    }

    if (match.phase === "scheduled") {
        meta.appendChild(make("span", "live-kickoff", match.kickoff_time || localizedLiveStatus(match)));
        return meta;
    }

    if (match.phase === "cancelled" || match.phase === "unknown") {
        meta.appendChild(make("span", "live-meta-note live-meta-warn", localizedLiveStatus(match)));
        return meta;
    }

    // finished
    meta.appendChild(make("span", "live-meta-note", localizedLiveStatus(match)));
    return meta;
}

/**
 * Eine Match-Karte.
 *
 * Seit LIVE B ein <button>: der Klick oeffnet das Match Center. Die
 * data-Attribute (API-Football fixture id und Team-IDs) waren schon in
 * LIVE A dafuer vorgesehen und bleiben unveraendert erhalten.
 */
function liveBuildMatchCard(match) {
    const card = make("button", "live-match");
    card.type = "button";

    card.dataset.fixtureId = match.fixture_id;
    if (match.home_id !== null && match.home_id !== undefined) card.dataset.homeId = match.home_id;
    if (match.away_id !== null && match.away_id !== undefined) card.dataset.awayId = match.away_id;
    card.dataset.phase = match.phase;

    if (match.is_live) card.classList.add("is-live");

    const teams = make("div", "live-match-teams");
    teams.appendChild(liveBuildTeamRow(match.home_name, match.home_logo, match.home_goals));
    teams.appendChild(liveBuildTeamRow(match.away_name, match.away_logo, match.away_goals));

    card.appendChild(teams);
    card.appendChild(liveBuildMeta(match));

    card.addEventListener("click", () => mcOpen(match.fixture_id));

    return card;
}

function liveBuildGroup(group) {
    const section = make("section", "live-group");

    const head = make("div", "live-group-head");
    if (group.league_logo) head.appendChild(crest(group.league_logo, "live-group-logo"));
    head.appendChild(make("h3", "live-group-name", group.league_name || t("competition.unknown")));
    if (group.league_country) {
        head.appendChild(make("span", "live-group-country", group.league_country));
    }
    section.appendChild(head);

    const list = make("div", "live-match-list");
    
    // Sort matches to prioritize favorite team.
    // LIVE liefert API-Football-IDs. Solange die Auswahl ihre IDs aus
    // /api/standings (football-data.org) bezieht, greift die
    // Sortierung hier bewusst nicht, statt zufaellig danebenzutreffen.
    if (window.favoriteTeamId && group.matches) {
        group.matches.sort((a, b) => {
            const aIsFav = isFavoriteTeamId(a.home_id, "apisports")
                || isFavoriteTeamId(a.away_id, "apisports");
            const bIsFav = isFavoriteTeamId(b.home_id, "apisports")
                || isFavoriteTeamId(b.away_id, "apisports");
            return (bIsFav ? 1 : 0) - (aIsFav ? 1 : 0);
        });
    }
    
    group.matches.forEach(match => list.appendChild(liveBuildMatchCard(match)));
    section.appendChild(list);

    return section;
}

/**
 * Enthaelt diese Gruppe ein Spiel des Lieblingsteams?
 *
 * Prueft ausschliesslich Team-IDs, nie den Status - damit gilt die
 * Regel unveraendert fuer laufende, kommende und verschobene Spiele.
 * Der Wettbewerb spielt bewusst keine Rolle: Superpokal, Freundschafts-
 * spiel oder Liga werden gleich behandelt.
 */
function liveGroupHasFavorite(group) {
    if (!group || !Array.isArray(group.matches)) return false;
    return group.matches.some((match) => (
        isFavoriteTeamId(match.home_id, "apisports")
        || isFavoriteTeamId(match.away_id, "apisports")
    ));
}

/**
 * Sortiert Gruppen mit einem Spiel des Lieblingsteams nach vorn.
 *
 * Die uebrigen Gruppen behalten ihre bestehende Reihenfolge
 * (Array.prototype.sort ist stabil, zusaetzlich sichert der
 * Index-Tiebreak das ab) - die serverseitige Wettbewerbsreihenfolge
 * bleibt also unter der Personalisierung vollstaendig erhalten.
 *
 * Es werden ausschliesslich Gruppen umsortiert. Keine Spieldaten,
 * keine Anstosszeiten, keine Wettbewerbsidentitaet, keine Duplikate.
 */
function liveOrderGroupsForFavorite(groups) {
    if (!window.favoriteTeamId || !Array.isArray(groups)) return groups;

    return groups
        .map((group, index) => ({ group, index, favorite: liveGroupHasFavorite(group) }))
        .sort((a, b) => (Number(b.favorite) - Number(a.favorite)) || (a.index - b.index))
        .map((entry) => entry.group);
}

/**
 * Wendet eine zuvor festgehaltene Reihenfolge erneut an.
 *
 * Hintergrund-Ticks sollen Ergebnisse aktualisieren, aber die Seite
 * nicht unter dem Finger neu sortieren. Deshalb wird die beim ersten
 * Rendern eines Tages ermittelte Reihenfolge gemerkt und danach
 * wiederverwendet; Gruppen, die es damals noch nicht gab, haengen in
 * Serverreihenfolge hinten an, statt zu verschwinden.
 */
function liveApplyRememberedOrder(groups, leagueOrder) {
    const position = new Map(leagueOrder.map((leagueId, index) => [String(leagueId), index]));
    return groups
        .map((group, index) => ({
            group,
            index,
            known: position.has(String(group.league_id)),
            rank: position.get(String(group.league_id)),
        }))
        .sort((a, b) => {
            if (a.known && b.known) return a.rank - b.rank;
            if (a.known !== b.known) return a.known ? -1 : 1;
            return a.index - b.index;
        })
        .map((entry) => entry.group);
}

function liveRender(data, options) {
    liveGroups.innerHTML = "";

    if (!data.groups || data.groups.length === 0) {
        hide(liveGroups);
        show(liveEmpty);
        return;
    }

    const background = !!(options && options.background);
    const remembered = liveState.favoriteOrder;
    const sameDay = remembered && remembered.date === liveState.selectedDate;

    let groups;
    if (background && sameDay) {
        // Reihenfolge des Tages beibehalten (siehe liveApplyRememberedOrder).
        groups = liveApplyRememberedOrder(data.groups, remembered.leagueIds);
    } else {
        groups = liveOrderGroupsForFavorite(data.groups);
        liveState.favoriteOrder = {
            date: liveState.selectedDate,
            leagueIds: groups.map((group) => group.league_id),
        };
    }

    groups.forEach(group => liveGroups.appendChild(liveBuildGroup(group)));

    hide(liveEmpty);
    show(liveGroups);
}

/**
 * Laedt die Spiele des gewaehlten Tages.
 *
 * options.background: true bei einem Auto-Refresh-Tick. Dann wird der
 * Ladezustand nicht per Statustext angekuendigt (kein "Spiele werden
 * geladen"-Flackern alle 50 Sekunden) - nur das Ergebnis erscheint.
 */
async function liveLoad(options) {
    if (!liveGroups) return;

    const background = !!(options && options.background);
    const token = ++liveState.requestToken;
    const isoDate = liveState.selectedDate;

    liveState.loading = true;

    if (!background) {
        if (liveHeading) liveHeading.textContent = liveHeadingText(isoDate);
        if (liveDateLabel) liveDateLabel.textContent = liveFormatDateLabel(isoDate);
        liveSetStatus(t("live.loading"));
    }

    try {
        const data = await fetchJson(`/api/live-matches?date=${encodeURIComponent(isoDate)}`);

        // Eine zwischenzeitliche Tagesnavigation hat Vorrang.
        if (token !== liveState.requestToken) return;

        liveRender(data, { background });

        if (liveHeading) liveHeading.textContent = liveHeadingText(isoDate);
        if (liveDateLabel) liveDateLabel.textContent = liveFormatDateLabel(isoDate);

        if (data.match_count === 0) {
            liveSetStatus(t("live.emptyForDay"));
        } else if (data.live_count > 0) {
            liveSetStatus(t("live.matchCountLive", {
                count: data.match_count,
                live: data.live_count,
            }));
        } else {
            liveSetStatus(t("live.matchCount", { count: data.match_count }));
        }

        // Der Server konnte die Quelle nicht erreichen und liefert den
        // letzten bekannten Stand. Das gehoert sichtbar gemacht.
        if (data.stale) {
            liveSetStatus(t("live.stale", { count: data.match_count }));
        }

        liveState.ready = true;
        liveState.lastData = data;

        // Nach jedem Laden neu entscheiden, ob Auto-Refresh laufen soll -
        // die Bedingungen (heute? noch etwas live?) koennen sich mit
        // jeder Antwort aendern.
        liveScheduleAutoRefresh(data);

    } catch (error) {
        if (token !== liveState.requestToken) return;

        // Ein fehlgeschlagener Hintergrund-Tick darf die sichtbare Seite
        // nicht kaputt machen - die zuletzt erfolgreich geladenen Daten
        // bleiben einfach stehen. Nur ein regulaerer Ladevorgang zeigt
        // den Fehler.
        if (!background) {
            // Bewusst NICHT der leere Zustand: "Keine Spiele" waere eine
            // Falschaussage, wenn wir es schlicht nicht laden konnten.
            const message = error.message || t("live.unavailable");

            liveGroups.innerHTML = "";
            liveGroups.appendChild(make("div", "loading-hint", message));
            hide(liveEmpty);
            show(liveGroups);

            liveSetStatus(message);
        }

        liveStopAutoRefresh();

    } finally {
        if (token === liveState.requestToken) liveState.loading = false;
    }
}


/* ---------- 16c1. DATUMSNAVIGATION: STREIFEN, PFEILE, KALENDER ---------- */

/**
 * Setzt den gewaehlten Tag zentral und stoesst alles Weitere an:
 * Streifen neu zeichnen, aktiven Chip zentrieren, Daten laden.
 *
 * Einzige Stelle, die liveState.selectedDate aendert - Pfeile, Chips,
 * Kalender und der Streifen-Swipe rufen alle nur diese Funktion.
 */
function liveSetSelectedDate(isoDate) {
    if (liveState.selectedDate === isoDate) return;

    liveState.selectedDate = isoDate;

    // Der alte Timer gehoerte zum vorherigen Tag. Ob ein neuer noetig
    // ist, entscheidet liveLoad() nach der Antwort neu.
    liveStopAutoRefresh();

    liveRenderStrip();
    if (liveCalendarInput) liveCalendarInput.value = isoDate;

    liveLoad();
}

/** Baut die Chip-Reihe um liveState.selectedDate herum neu auf. */
function liveRenderStrip() {
    if (!liveDateStrip) return;

    const center = liveState.selectedDate;
    const today = liveBerlinToday();

    liveDateStrip.innerHTML = "";

    for (let offset = -LIVE_STRIP_RADIUS_DAYS; offset <= LIVE_STRIP_RADIUS_DAYS; offset++) {
        const chipDate = liveShiftDate(center, offset);
        const isToday = chipDate === today;
        const isActive = chipDate === center;

        const chip = make("button", "live-date-chip" + (isActive ? " active" : "") + (isToday ? " is-today" : ""));
        chip.type = "button";
        chip.dataset.date = chipDate;
        if (isActive) chip.setAttribute("aria-current", "date");

        chip.appendChild(make("span", "live-date-chip-top", isToday ? t("live.todayShort") : liveWeekdayShort(chipDate)));
        chip.appendChild(make("span", "live-date-chip-day", liveChipDayLabel(chipDate)));

        liveDateStrip.appendChild(chip);
    }

    const activeChip = liveDateStrip.querySelector(".live-date-chip.active");
    if (activeChip) {
        // "auto" statt "smooth": nach einem Pfeil-/Kalenderklick soll der
        // Streifen sofort stehen, nicht bei jedem Tastendruck neu animieren.
        activeChip.scrollIntoView({ inline: "center", block: "nearest", behavior: "auto" });
    }
}

if (liveDateStrip) {
    liveDateStrip.addEventListener("click", (event) => {
        const chip = event.target.closest(".live-date-chip");
        if (chip) liveSetSelectedDate(chip.dataset.date);
    });

    /**
     * Der Streifen ist nativ horizontal scrollbar (CSS scroll-snap) -
     * das ist bereits das komplette Swipe-Verhalten, ohne eigenen
     * Touch-Code. Hier wird nur erkannt, wann das Scrollen zur Ruhe
     * gekommen ist und welcher Chip dann in der Mitte steht, damit ein
     * Swipe denselben Effekt hat wie ein Klick auf diesen Chip.
     */
    liveDateStrip.addEventListener("scroll", () => {
        if (liveState.stripSettleTimer) clearTimeout(liveState.stripSettleTimer);

        liveState.stripSettleTimer = setTimeout(() => {
            liveState.stripSettleTimer = null;

            const stripBox = liveDateStrip.getBoundingClientRect();
            const stripCenter = stripBox.left + stripBox.width / 2;

            let nearest = null;
            let nearestDistance = Infinity;

            liveDateStrip.querySelectorAll(".live-date-chip").forEach(chip => {
                const chipBox = chip.getBoundingClientRect();
                const chipCenter = chipBox.left + chipBox.width / 2;
                const distance = Math.abs(chipCenter - stripCenter);

                if (distance < nearestDistance) {
                    nearestDistance = distance;
                    nearest = chip;
                }
            });

            // Ist der zentrierte Chip bereits der gewaehlte Tag (z. B. weil
            // dies die eigene programmatische Zentrierung war), passiert
            // nichts - liveSetSelectedDate() bricht bei Gleichheit ohnehin ab.
            if (nearest) liveSetSelectedDate(nearest.dataset.date);
        }, LIVE_STRIP_SETTLE_DELAY_MS);
    }, { passive: true });
}

if (livePrevDayBtn) {
    livePrevDayBtn.addEventListener("click", () => {
        liveSetSelectedDate(liveShiftDate(liveState.selectedDate, -1));
    });
}

if (liveNextDayBtn) {
    liveNextDayBtn.addEventListener("click", () => {
        liveSetSelectedDate(liveShiftDate(liveState.selectedDate, 1));
    });
}

if (liveCalendarBtn && liveCalendarInput) {
    liveCalendarBtn.addEventListener("click", () => {
        // showPicker() ist die robuste moderne API; das defensive Fallback
        // deckt Browser ohne Unterstuetzung ab. Kein Datepicker-Framework.
        if (typeof liveCalendarInput.showPicker === "function") {
            try {
                liveCalendarInput.showPicker();
                return;
            } catch (error) {
                // faellt durch zum Fallback
            }
        }
        liveCalendarInput.focus();
        liveCalendarInput.click();
    });

    liveCalendarInput.addEventListener("change", () => {
        const value = liveCalendarInput.value;
        // Ein natives type="date" liefert entweder "" oder ein gueltiges
        // YYYY-MM-DD - trotzdem defensiv pruefen, bevor es zum Server geht.
        if (/^\d{4}-\d{2}-\d{2}$/.test(value)) liveSetSelectedDate(value);
    });
}


/* ---------- 16c2. AUTO-REFRESH FUER LAUFENDE SPIELE ---------- */

function liveStopAutoRefresh() {
    if (liveState.refreshTimer !== null) {
        clearInterval(liveState.refreshTimer);
        liveState.refreshTimer = null;
    }
}

/**
 * Alle Bedingungen muessen gleichzeitig gelten. Faellt eine weg, ist der
 * naechste Aufruf hier false und der Timer wird nicht erneuert.
 *
 * Bei geoeffnetem Match Center ist die Tagesliste verdeckt - sie dann
 * weiter zu pollen waere Arbeit fuer eine unsichtbare Ansicht. Das Match
 * Center hat seinen eigenen Timer (siehe mcScheduleAutoRefresh).
 */
function liveShouldAutoRefresh(data) {
    return state.activeArea === "live" &&
        !mcState.open &&
        !!data &&
        data.is_today === true &&
        (data.live_count || 0) > 0 &&
        document.visibilityState === "visible";
}

/** Startet oder stoppt den Timer passend zu den aktuellen Daten. Nie mehr als einer gleichzeitig. */
function liveScheduleAutoRefresh(data) {
    liveStopAutoRefresh();

    if (!liveShouldAutoRefresh(data)) return;

    liveState.refreshTimer = setInterval(() => {
        // Sicherheitsnetz: sollte sich der Zustand seit dem letzten
        // Scheduling geaendert haben, bevor der naechste Tick greift.
        if (!liveShouldAutoRefresh(liveState.lastData)) {
            liveStopAutoRefresh();
            return;
        }
        liveLoad({ background: true });
    }, LIVE_REFRESH_INTERVAL_MS);
}

/**
 * Tab wird unsichtbar: beide Timer pausieren, kein Grund fuer Requests,
 * die niemand sieht. Tab wird wieder sichtbar: die gerade sichtbare
 * Ansicht einmal leise nachladen und ihren Auto-Refresh anhand der
 * frischen Antwort neu bewerten.
 */
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
        liveStopAutoRefresh();
        mcStopAutoRefresh();
        return;
    }

    if (state.activeArea !== "live") return;

    if (mcState.open) {
        if (mcState.fixtureId !== null && !mcState.loading) mcLoad({ background: true });
        return;
    }

    if (liveState.ready && !liveState.loading) liveLoad({ background: true });
});

/**
 * Erster Aufruf beim Oeffnen des Bereichs.
 *
 * Vor dem ersten Laden ueberhaupt wird der heutige Tag gewaehlt. Danach
 * holt ein erneutes Betreten des Bereichs nur dann leise neu, wenn der
 * gewaehlte Tag heute ist - der serverseitige Cache entscheidet ohnehin,
 * wie frisch die Daten sind, und fuer vergangene/zukuenftige Tage aendert
 * sich zwischen zwei Besuchen nichts. Ein Tagwechsel ist damit weiterhin
 * kein automatischer Grund fuer einen Request, aber "heute" bleibt aktuell.
 */
function liveInit() {
    // Der Nutzer war zuletzt in einem Spiel und kommt in den Bereich
    // zurueck: dort weitermachen, nicht ungefragt zur Liste springen.
    if (mcState.open) {
        if (mcState.fixtureId !== null && !mcState.loading) mcLoad({ background: true });
        return;
    }

    if (!liveState.ready) {
        liveSetSelectedDate(liveBerlinToday());
        return;
    }

    if (liveState.selectedDate === liveBerlinToday()) {
        liveLoad({ background: true });
    } else {
        liveScheduleAutoRefresh(liveState.lastData);
    }
}


/* ---------- 16d. MATCH CENTER (Block LIVE B) ----------

   Detailansicht eines einzelnen Spiels, innerhalb des Hauptbereichs
   "live". Die Tagesliste wird dabei nur verdeckt, nicht verworfen - der
   Zurueck-Weg fuehrt deshalb ohne erneutes Laden exakt auf den vorher
   gewaehlten Tag zurueck.

   Alle vier Reiter arbeiten auf demselben einmal geladenen Payload von
   /api/live-match. Ein Reiterwechsel rendert nur neu, er laedt nicht.

   Eigener Zustand und eigener Timer, bewusst getrennt von liveState:
   die beiden Ansichten haben unterschiedliche Lebenszyklen. Es laeuft
   immer hoechstens einer von beiden Timern, weil
   liveShouldAutoRefresh() bei geoeffnetem Match Center false liefert.
------------------------------------------------------------------- */

const mcListView    = el("live-list-view");
const mcView        = el("live-match-center");
const mcBackBtn     = el("mc-back");
const mcStatus      = el("mc-status");
const mcScoreboard  = el("mc-scoreboard");
const mcTabBar      = el("mc-tab-bar");

const MC_TABS = {
    overview: el("mc-tab-overview"),
    lineups:  el("mc-tab-lineups"),
    events:   el("mc-tab-events"),
    stats:    el("mc-tab-stats"),
};

// Passend zur Server-TTL fuer laufende Spiele (TTL_LIVE_MATCH_INPLAY,
// 25s). Kuerzer waere ueberwiegend derselbe Cache-Eintrag.
const MC_REFRESH_INTERVAL_MS = 28000;

const mcState = {
    open: false,
    fixtureId: null,
    activeTab: "overview",
    loading: false,
    requestToken: 0,
    data: null,
    refreshTimer: null,
};

function mcSetStatus(text) {
    if (mcStatus) mcStatus.textContent = text;
}


/* ---------- 16d1. Aufbau der Reiter ---------- */

/**
 * Oeffnet das Teamprofil aus dem Match Center heraus (Block LIVE D2).
 *
 * league_id/season kommen aus data.league des bereits geladenen
 * Match-Center-Payloads (season seit Block D1 vorhanden) - kein
 * zusaetzlicher Request, keine eigene Herleitung.
 */
function mcOpenTeam(teamId) {
    if (teamId === null || teamId === undefined) return;
    if (!mcState.data) return;

    const league = mcState.data.league || {};

    tdOpen(teamId, {
        leagueId: league.id ?? null,
        season: league.season ?? null,
        returnTo: "live",
    });
}

function mcBuildScoreboard(data) {
    const fixture = data.fixture;
    const board = make("div", "mc-board");

    // Wettbewerb und Runde
    const meta = make("div", "mc-board-meta");
    if (data.league.logo) meta.appendChild(crest(data.league.logo, "mc-board-league-logo"));
    meta.appendChild(make("span", "mc-board-league", data.league.name || t("competition.unknown")));
    if (fixture.round) meta.appendChild(make("span", "mc-board-round", fixture.round));
    board.appendChild(meta);

    // Teams und Stand
    const line = make("div", "mc-board-line");

    const homeSide = make("div", "mc-board-team");
    if (data.home.logo) homeSide.appendChild(crest(data.home.logo, "mc-board-logo"));
    homeSide.appendChild(make("span", "mc-board-team-name", data.home.name || t("player.unknown")));
    if (data.home.id !== null && data.home.id !== undefined) {
        homeSide.dataset.teamId = data.home.id;
        mcMakeTappable(homeSide, () => mcOpenTeam(data.home.id));
    }
    line.appendChild(homeSide);

    const hasScore = data.home.goals !== null && data.home.goals !== undefined;
    const score = make("div", "mc-board-score",
        hasScore ? `${data.home.goals} : ${data.away.goals}` : "–  :  –");
    line.appendChild(score);

    const awaySide = make("div", "mc-board-team");
    if (data.away.logo) awaySide.appendChild(crest(data.away.logo, "mc-board-logo"));
    awaySide.appendChild(make("span", "mc-board-team-name", data.away.name || t("player.unknown")));
    if (data.away.id !== null && data.away.id !== undefined) {
        awaySide.dataset.teamId = data.away.id;
        mcMakeTappable(awaySide, () => mcOpenTeam(data.away.id));
    }
    line.appendChild(awaySide);

    board.appendChild(line);

    // Statuszeile - dieselbe Sprache wie in der Tagesliste
    const statusRow = make("div", "mc-board-status");

    if (fixture.phase === "live") {
        statusRow.appendChild(make("span", "live-badge", t("matchCenter.live")));
        statusRow.appendChild(make("span", "mc-board-minute",
            fixture.minute_label || localizedLiveStatus(fixture)));
    } else if (fixture.phase === "paused") {
        statusRow.appendChild(make("span", "live-badge", t("matchCenter.live")));
        statusRow.appendChild(make("span", "mc-board-minute", localizedLiveStatus(fixture)));
    } else if (fixture.phase === "scheduled") {
        statusRow.appendChild(make("span", "mc-board-minute",
            fixture.kickoff_time
                ? t("matchCenter.kickoffAt", { time: fixture.kickoff_time })
                : localizedLiveStatus(fixture)));
    } else if (fixture.phase === "cancelled" || fixture.phase === "unknown") {
        statusRow.appendChild(make("span", "mc-board-minute live-meta-warn", localizedLiveStatus(fixture)));
    } else {
        // "Ende n.V." (AET) unterscheidet den Status bereits eindeutig
        // von einem regulaeren Spielende - keine weitere Ergaenzung
        // noetig. Nur bei Elfmeterschiessen (PEN) fehlt sonst, WER die
        // Serie gewonnen hat: der grosse Stand oben bleibt der Stand
        // nach Verlaengerung (data.home/away.goals), das
        // Elfmeterergebnis kommt als eigene, klar getrennte Zeile dazu
        // (Block LIVE E) - nie in den regulaeren Spielstand gemischt.
        statusRow.appendChild(make("span", "mc-board-minute", localizedLiveStatus(fixture)));

        if (fixture.status_short === "PEN") {
            const penalty = mcPenaltyScore(data);
            if (penalty) statusRow.appendChild(make("span", "mc-board-penalty",
                t("matchCenter.penalties", { score: penalty })));
        }
    }

    board.appendChild(statusRow);
    return board;
}

/** "5 : 4", oder null ohne verwertbares Elfmeterschiessen-Ergebnis. */
function mcPenaltyScore(data) {
    const penalty = data.score && data.score.penalty;
    if (!penalty) return null;
    if (penalty.home === null || penalty.home === undefined) return null;
    if (penalty.away === null || penalty.away === undefined) return null;
    return `${penalty.home} : ${penalty.away}`;
}

/** Kleine "Bezeichnung / Wert"-Zeile; wird bei fehlendem Wert weggelassen. */
function mcInfoRow(label, value) {
    if (value === null || value === undefined || value === "") return null;

    const row = make("div", "mc-info-row");
    row.appendChild(make("span", "mc-info-label", label));
    row.appendChild(make("span", "mc-info-value", String(value)));
    return row;
}

function mcRenderOverview(data) {
    const target = MC_TABS.overview;
    target.innerHTML = "";

    const fixture = data.fixture;
    const box = make("div", "mc-info");

    const venue = [fixture.venue_name, fixture.venue_city].filter(Boolean).join(" · ");

    const rows = [
        mcInfoRow(t("matchCenter.info.competition"), data.league.name),
        mcInfoRow(t("matchCenter.info.country"), data.league.country),
        mcInfoRow(t("matchCenter.info.round"), fixture.round),
        mcInfoRow(t("matchCenter.info.venue"), venue),
        mcInfoRow(t("matchCenter.info.kickoff"), fixture.kickoff_time),
        mcInfoRow(t("matchCenter.info.status"), localizedLiveStatus(fixture)),
        mcInfoRow(t("matchCenter.info.referee"), fixture.referee),
    ].filter(Boolean);

    rows.forEach(row => box.appendChild(row));
    target.appendChild(box);
}

/**
 * Ereignisse je Spieler zusammenfassen (Block LIVE C).
 *
 * Zugeordnet wird ausschliesslich ueber die API-Football-Player-ID, nie
 * ueber den Namen: Umschriften und Namensgleichheit machen einen
 * Namensvergleich unzuverlaessig.
 *
 * Mehrfachereignisse werden gezaehlt, nicht ueberschrieben - wer zweimal
 * trifft, soll auch zwei Tore sehen.
 */
function mcBuildPlayerEventIndex(events) {
    const index = new Map();

    const bucketFor = (person) => {
        if (!person || person.id === null || person.id === undefined) return null;

        if (!index.has(person.id)) {
            index.set(person.id, {
                goals: 0, ownGoals: 0, assists: 0,
                yellow: 0, yellowRed: 0, red: 0,
                inMinute: null, outMinute: null,
            });
        }
        return index.get(person.id);
    };

    (events || []).forEach(event => {
        if (event.type === "substitution") {
            // Beim Wechsel fuehrt die Quelle den ausgewechselten Spieler
            // zusaetzlich unter "player". Nur player_out/player_in
            // auswerten, sonst zaehlte derselbe Wechsel doppelt.
            const leaving = bucketFor(event.player_out);
            if (leaving) leaving.outMinute = event.minute_label;

            const entering = bucketFor(event.player_in);
            if (entering) entering.inMinute = event.minute_label;
            return;
        }

        const own = bucketFor(event.player);
        if (own) {
            if (event.type === "goal")             own.goals += 1;
            else if (event.type === "own_goal")    own.ownGoals += 1;
            else if (event.type === "yellow_card") own.yellow += 1;
            else if (event.type === "yellow_red_card") own.yellowRed += 1;
            else if (event.type === "red_card")    own.red += 1;
        }

        // Vorlagen nur bei regulaeren Toren - eine "Vorlage" zum
        // Eigentor waere keine.
        if (event.type === "goal") {
            const helper = bucketFor(event.assist);
            if (helper) helper.assists += 1;
        }
    });

    return index;
}

/** Bewertung immer mit einer Nachkommastelle: die Quelle liefert auch "8". */
function mcFormatRating(rating) {
    return Number(rating).toFixed(1);
}

/**
 * Bewertungsabzeichen, oder null wenn keine Bewertung vorliegt.
 *
 * Ohne echte Bewertung entsteht KEIN Abzeichen. FootSim zeigt an dieser
 * Stelle nie einen geschaetzten oder voreingestellten Wert.
 *
 * Die Stufe kommt fertig aus dem Backend (rating_tier); hier wird daraus
 * nur noch eine CSS-Klasse. Dadurch stehen die Schwellenwerte an genau
 * einer Stelle und nicht als Zahlen im Frontend.
 */
function mcBuildRatingBadge(player, extraClass) {
    if (player.rating === null || player.rating === undefined) return null;

    const tier = player.rating_tier || "average";
    const text = mcFormatRating(player.rating);

    const badge = make("span",
        `mc-rating mc-rating--${tier}${extraClass ? " " + extraClass : ""}`, text);
    badge.title = t("matchCenter.rating", { rating: text });
    return badge;
}

/** Initialen als Rueckfall, wenn kein Spielerbild vorliegt. */
function mcInitials(name) {
    if (!name) return "?";

    return name.trim().split(/\s+/).slice(0, 2)
        .map(part => part.charAt(0).toUpperCase())
        .join("");
}

/**
 * Spielerbild als Kreis, mit Initialen darunter als Rueckfall.
 *
 * Die Initialen liegen immer im DOM und werden vom Bild ueberdeckt.
 * Laedt das Bild nicht, wird es entfernt und die Initialen stehen da -
 * nie ein leerer Kreis.
 */
function mcBuildAvatar(player) {
    const avatar = make("div", "mc-pp-avatar");
    avatar.appendChild(make("span", "mc-pp-initials", mcInitials(player.name)));

    if (player.photo) {
        const photo = make("img", "mc-pp-photo");
        photo.src = player.photo;
        photo.alt = "";
        photo.loading = "lazy";
        photo.onerror = () => { photo.remove(); };
        avatar.appendChild(photo);
    }

    return avatar;
}

/**
 * Kleine Marker fuer Tore, Vorlagen, Karten und Auswechslung.
 *
 * Rueckgabe null, wenn der Spieler nichts davon hat - dann entsteht auch
 * kein leerer Container.
 *
 * Auf dem Spielfeld traegt der Wechselpfeil nur die Richtung; die Minute
 * steht im Titel und in der Ersatzbankliste, wo Platz dafuer ist.
 *
 * options.include waehlt eine Teilmenge: "match" nur Tore/Vorlagen/Karten
 * (fuers Spielfeld, dort direkt am Avatar verankert), "substitution" nur
 * die Wechselpfeile (bleiben auf dem Spielfeld unter dem Namen, siehe
 * mcBuildPitchPlayer), "all" (Default) beides zusammen wie bisher -
 * genau das braucht die Ersatzbank-/Rueckfallliste unveraendert weiter.
 */
function mcBuildEventMarkers(stats, options) {
    if (!stats) return null;

    const withMinutes = !!(options && options.withMinutes);
    const include = (options && options.include) || "all";
    const showMatchEvents = include !== "substitution";
    const showSubstitution = include !== "match";
    const markers = make("div", "mc-pp-markers");
    let count = 0;

    const addMarker = (className, text, title) => {
        const marker = make("span", `mc-pp-marker ${className}`, text);
        marker.title = title;
        markers.appendChild(marker);
        count += 1;
    };

    if (showMatchEvents) {
        if (stats.goals > 0) {
            addMarker("is-goal", stats.goals > 1 ? `⚽${stats.goals}` : "⚽",
                stats.goals > 1
                    ? t("matchCenter.goals", { count: stats.goals })
                    : t("matchCenter.goal"));
        }

        if (stats.ownGoals > 0) {
            addMarker("is-owngoal", stats.ownGoals > 1 ? `⚽${stats.ownGoals}` : "⚽",
                stats.ownGoals > 1
                    ? t("matchCenter.ownGoals", { count: stats.ownGoals })
                    : t("matchCenter.ownGoal"));
        }

        if (stats.assists > 0) {
            addMarker("is-assist", stats.assists > 1 ? `A${stats.assists}` : "A",
                stats.assists > 1
                    ? t("matchCenter.assists", { count: stats.assists })
                    : t("matchCenter.assist"));
        }

        // Karten als farbige Flaeche statt Zeichen - auf kleinen Displays
        // deutlich besser erkennbar als ein Emoji.
        //
        // Block LIVE E, bewusst korrigiert: fruehere Fassung deutete zwei
        // gezaehlte Gelbe Karten (stats.yellow > 1) als "Gelb-Rot" - das
        // traf den tatsaechlichen Ausschluss durch zweite Gelbe nie, weil
        // der Provider diesen als EIN eigenes Ereignis liefert
        // (classify_event() erkennt "Second Yellow card" jetzt separat als
        // yellow_red_card statt es der generischen Gelb-Zaehlung
        // zuzuschlagen). Gelb-Rot bekommt darum einen eigenen Marker.
        if (stats.yellow > 0) {
            addMarker("is-yellow", "", t("matchCenter.yellowCard"));
        }

        if (stats.yellowRed > 0) {
            addMarker("is-yellowred", "", t("matchCenter.yellowRedCard"));
        }

        if (stats.red > 0) {
            addMarker("is-red", "", t("matchCenter.redCard"));
        }
    }

    if (showSubstitution) {
        if (stats.outMinute) {
            addMarker("is-out", withMinutes ? `↓${stats.outMinute}` : "↓",
                t("matchCenter.substitutedOff", { minute: stats.outMinute }));
        }

        if (stats.inMinute) {
            addMarker("is-in", withMinutes ? `↑${stats.inMinute}` : "↑",
                t("matchCenter.substitutedOn", { minute: stats.inMinute }));
        }
    }

    return count ? markers : null;
}

/**
 * Langer Name auf dem Spielfeld: lieber nur der Nachname als ein
 * abgeschnittener Wortanfang. Der vollstaendige Name bleibt im Titel.
 */
function mcShortName(name) {
    if (!name) return "";

    const trimmed = name.trim();
    if (trimmed.length <= 14) return trimmed;

    const parts = trimmed.split(/\s+/);
    return parts[parts.length - 1];
}

/** Ein Spieler auf dem Spielfeld: Bild, Nummer, Name, Bewertung, Marker. */
/**
 * Macht ein Element per Maus UND Tastatur aktivierbar (Block LIVE D1).
 *
 * Bewusst KEIN <button>: mc-pp und mc-player verschachteln Bloecke
 * (div in div) - in einem <button>-Element waere das ungueltiges HTML.
 * role="button" + tabindex + Enter/Leertaste ist der Standardweg fuer
 * ein aktivierbares Nicht-button-Element.
 */
function mcMakeTappable(node, handler) {
    node.classList.add("mc-tappable");
    node.setAttribute("role", "button");
    node.setAttribute("tabindex", "0");
    node.addEventListener("click", handler);
    node.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            handler(event);
        }
    });
}

/**
 * Oeffnet das Spielerprofil aus dem Match Center heraus (Block LIVE D1).
 *
 * Die Saison kommt aus data.league.season des bereits geladenen
 * Match-Center-Payloads (live_api.py) - kein zusaetzlicher Request, keine
 * eigene Herleitung. player.number ist die echte Aufstellungsnummer aus
 * genau diesem Spiel und wird als Kontext mitgegeben (siehe pdState.
 * contextNumber): /players liefert laut Analyse keine verlaessliche
 * aktuelle Rueckennummer, diese hier ist es aber tatsaechlich.
 */
function mcOpenPlayer(player) {
    if (!player || player.id === null || player.id === undefined) return;
    if (!mcState.data) return;

    const league = mcState.data.league || {};

    pdOpen(player.id, {
        season: league.season ?? null,
        contextNumber: player.number ?? null,
        returnTo: "live",
    });
}

function mcBuildPitchPlayer(player, stats) {
    const node = make("div", "mc-pp");

    // API-Football Player ID erhalten - spaetere Spielerprofile haengen
    // sich hier an, ohne dass eine neue Identitaet noetig waere.
    if (player.id !== null && player.id !== undefined) {
        node.dataset.playerId = player.id;
        mcMakeTappable(node, () => mcOpenPlayer(player));
    }

    const figure = make("div", "mc-pp-figure");
    figure.appendChild(mcBuildAvatar(player));

    if (player.number !== null && player.number !== undefined) {
        figure.appendChild(make("span", "mc-pp-number", String(player.number)));
    }

    const badge = mcBuildRatingBadge(player);
    if (badge) figure.appendChild(badge);

    // Tor/Vorlage/Karte sitzen direkt am Avatar (unten rechts), nicht mehr
    // lose unter dem Namen: bei eng stehenden Spielern war sonst nicht
    // erkennbar, wem ein Ereignis zwischen zwei Namen gehoert (siehe
    // Bugreport: ⚽ zwischen zwei benachbarten Spielern). Der Avatar traegt
    // damit alle drei Abzeichen - Bewertung oben rechts, Nummer unten
    // links, Ereignis unten rechts - und ist selbst der eindeutige Anker.
    const eventBadge = mcBuildEventMarkers(stats, { include: "match" });
    if (eventBadge) {
        eventBadge.classList.add("mc-pp-events");
        figure.appendChild(eventBadge);
    }

    node.appendChild(figure);

    const name = make("div", "mc-pp-name", mcShortName(player.name) || t("player.unknown"));
    if (player.name) name.title = player.name;
    node.appendChild(name);

    // Der Wechselpfeil bleibt unter dem Namen: andere Bedeutung als ein
    // Ereignis (Richtung, nicht "was ist passiert"), keine Zuordnungs-
    // Ambiguitaet zwischen Nachbarspielern, deshalb bewusst nicht verlegt.
    const subMarkers = mcBuildEventMarkers(stats, { include: "substitution" });
    if (subMarkers) node.appendChild(subMarkers);

    return node;
}

/**
 * Grafisches Spielfeld einer Startelf.
 *
 * Die Reihen kommen fertig sortiert aus dem Backend (pitch_rows, siehe
 * build_pitch_rows in src/api/live_api.py) und enthalten Indizes auf
 * start_xi. Hier wird KEINE Formation ausgewertet und keine Position
 * gerechnet: die Reihen sind Flex-Container, die ihre Spieler von selbst
 * gleichmaessig verteilen. Dadurch stimmt die Darstellung fuer jede
 * Anzahl Spieler je Reihe, ohne dass sich etwas ueberlappen kann.
 *
 * Reihe 1 ist die eigene Torlinie. Das Feld ordnet sie per CSS unten an
 * (column-reverse), sodass die Mannschaft nach oben angreift.
 */
function mcBuildPitch(lineup, eventIndex) {
    const pitch = make("div", "mc-pitch");

    const markings = make("div", "mc-pitch-markings");
    markings.setAttribute("aria-hidden", "true");
    markings.appendChild(make("div", "mc-pitch-box"));
    markings.appendChild(make("div", "mc-pitch-halfway"));
    markings.appendChild(make("div", "mc-pitch-circle"));
    pitch.appendChild(markings);

    const rows = make("div", "mc-pitch-rows");

    lineup.pitch_rows.forEach(rowIndexes => {
        const row = make("div", "mc-pitch-row");

        rowIndexes.forEach(index => {
            const player = lineup.start_xi[index];
            if (!player) return;
            row.appendChild(mcBuildPitchPlayer(player, eventIndex.get(player.id)));
        });

        rows.appendChild(row);
    });

    pitch.appendChild(rows);
    return pitch;
}

function mcBuildPlayerRow(player, stats) {
    const row = make("div", "mc-player");

    row.appendChild(make("span", "mc-player-number",
        player.number === null || player.number === undefined ? "–" : String(player.number)));
    row.appendChild(make("span", "mc-player-name", player.name || t("player.unknown")));

    // Wechsel und Ereignisse mit Minute - hier ist Platz dafuer.
    const markers = mcBuildEventMarkers(stats, { withMinutes: true });
    if (markers) row.appendChild(markers);

    const badge = mcBuildRatingBadge(player, "mc-rating--inline");
    if (badge) row.appendChild(badge);

    if (player.pos) row.appendChild(make("span", "mc-player-pos", player.pos));

    // API-Football Player ID erhalten - spaetere Spielerprofile haengen
    // sich hier an, ohne dass eine neue Identitaet noetig waere.
    if (player.id !== null && player.id !== undefined) {
        row.dataset.playerId = player.id;
        mcMakeTappable(row, () => mcOpenPlayer(player));
    }

    return row;
}

function mcBuildLineupBlock(lineup, teamName, eventIndex) {
    const block = make("div", "mc-lineup");

    const head = make("div", "mc-lineup-head");
    const teamHeading = make("h3", "mc-lineup-team", teamName || t("player.unknown"));
    if (lineup.team_id !== null && lineup.team_id !== undefined) {
        teamHeading.dataset.teamId = lineup.team_id;
        mcMakeTappable(teamHeading, () => mcOpenTeam(lineup.team_id));
    }
    head.appendChild(teamHeading);
    if (lineup.formation) head.appendChild(make("span", "mc-lineup-formation", lineup.formation));
    block.appendChild(head);

    if (lineup.start_xi.length) {
        // Nur wenn das Backend das Raster fuer die GANZE Mannschaft
        // verstanden hat, entsteht ein Spielfeld. Sonst bleibt es bei der
        // Liste - lieber schlicht als teilweise falsch aufgestellt.
        if (lineup.has_pitch && lineup.pitch_rows) {
            block.appendChild(mcBuildPitch(lineup, eventIndex));
        } else {
            block.appendChild(make("p", "mc-lineup-label", t("matchCenter.startingLineup")));
            const list = make("div", "mc-player-list");
            lineup.start_xi.forEach(p =>
                list.appendChild(mcBuildPlayerRow(p, eventIndex.get(p.id))));
            block.appendChild(list);
        }
    }

    if (lineup.substitutes.length) {
        block.appendChild(make("p", "mc-lineup-label", t("matchCenter.bench")));
        const list = make("div", "mc-player-list");
        lineup.substitutes.forEach(p =>
            list.appendChild(mcBuildPlayerRow(p, eventIndex.get(p.id))));
        block.appendChild(list);
    }

    if (lineup.coach && lineup.coach.name) {
        block.appendChild(make("p", "mc-lineup-label", t("matchCenter.coach")));
        block.appendChild(make("div", "mc-coach", lineup.coach.name));
    }

    return block;
}

function mcRenderLineups(data) {
    const target = MC_TABS.lineups;
    target.innerHTML = "";

    // Bereich konnte gerade nicht geladen werden (Block LIVE E,
    // Partial-Failure-Haertung) - klar unterschieden vom Normalzustand
    // "noch nicht veroeffentlicht" unten.
    if (data.lineups_available === false) {
        target.appendChild(mcBuildNote(t("matchCenter.lineupsUnavailable")));
        return;
    }

    // Normaler Zustand vor der Aufstellungsveroeffentlichung - kein Fehler.
    if (!data.home_lineup && !data.away_lineup) {
        target.appendChild(mcBuildNote(t("matchCenter.lineupsPending")));
        return;
    }

    // Einmal je Rendern gebaut und von beiden Mannschaften genutzt.
    const eventIndex = mcBuildPlayerEventIndex(data.events);

    const wrap = make("div", "mc-lineups");
    if (data.home_lineup) {
        wrap.appendChild(mcBuildLineupBlock(data.home_lineup, data.home.name, eventIndex));
    }
    if (data.away_lineup) {
        wrap.appendChild(mcBuildLineupBlock(data.away_lineup, data.away.name, eventIndex));
    }
    target.appendChild(wrap);
}

/** Symbol je Ereignistyp. Unbekanntes bekommt einen neutralen Punkt. */
function mcEventIcon(type) {
    if (type === "goal")            return "⚽";
    if (type === "own_goal")        return "⚽";
    if (type === "penalty_missed")  return "✖";
    if (type === "yellow_card")     return "🟨";
    if (type === "yellow_red_card") return "🟨🟥";
    if (type === "red_card")        return "🟥";
    if (type === "substitution")    return "🔄";
    if (type === "var")             return "VAR";
    return "•";
}

function mcBuildEventRow(event, homeId) {
    const row = make("div", "mc-event");

    // Heim links, Auswaerts rechts unterscheidbar machen.
    if (event.team_id !== null && event.team_id !== undefined) {
        row.classList.add(event.team_id === homeId ? "is-home" : "is-away");
    }

    row.appendChild(make("span", "mc-event-minute", event.minute_label || ""));
    row.appendChild(make("span", "mc-event-icon", mcEventIcon(event.type)));

    const body = make("div", "mc-event-body");

    if (event.type === "substitution") {
        const inName = event.player_in && event.player_in.name;
        const outName = event.player_out && event.player_out.name;

        if (inName)  body.appendChild(make("div", "mc-event-main", `↑ ${inName}`));
        if (outName) body.appendChild(make("div", "mc-event-sub", `↓ ${outName}`));
        if (!inName && !outName) {
            body.appendChild(make("div", "mc-event-main", t("matchCenter.substitution")));
        }

    } else {
        const name = (event.player && event.player.name) || t("player.unknown");
        body.appendChild(make("div", "mc-event-main", name));

        if (event.type === "own_goal") {
            body.appendChild(make("div", "mc-event-sub mc-event-owngoal", t("matchCenter.ownGoal")));
        } else if (event.type === "yellow_red_card") {
            body.appendChild(make("div", "mc-event-sub mc-event-yellowred", t("matchCenter.yellowRedCard")));
        } else if (event.is_penalty) {
            body.appendChild(make("div", "mc-event-sub mc-event-penalty", t("matchCenter.penalty")));
        } else if (event.assist && event.assist.name) {
            body.appendChild(make("div", "mc-event-sub", t("matchCenter.assistBy", {
                name: event.assist.name,
            })));
        } else if (event.type === "other" && event.detail) {
            // Unbekannter Typ: den Rohtext zeigen statt ihn zu verschlucken.
            body.appendChild(make("div", "mc-event-sub", event.detail));
        }
    }

    row.appendChild(body);
    return row;
}

function mcRenderEvents(data) {
    const target = MC_TABS.events;
    target.innerHTML = "";

    if (data.events_available === false) {
        target.appendChild(mcBuildNote(t("matchCenter.eventsUnavailable")));
        return;
    }

    if (!data.events.length) {
        target.appendChild(mcBuildNote(t("matchCenter.eventsEmpty")));
        return;
    }

    const list = make("div", "mc-event-list");
    data.events.forEach(event => list.appendChild(mcBuildEventRow(event, data.home.id)));
    target.appendChild(list);
}

/**
 * Anteil eines Wertes am Paar, fuer den Vergleichsbalken.
 * Nur fuer Zahlen und Prozentwerte; sonst null (dann kein Balken).
 */
function mcStatShare(home, away) {
    const toNumber = (value) => {
        if (value === null || value === undefined) return null;
        const numeric = parseFloat(String(value).replace("%", "").replace(",", "."));
        return Number.isFinite(numeric) ? numeric : null;
    };

    const homeNumber = toNumber(home);
    const awayNumber = toNumber(away);

    if (homeNumber === null || awayNumber === null) return null;

    const total = homeNumber + awayNumber;
    if (total <= 0) return null;

    return (homeNumber / total) * 100;
}

function mcBuildStatRow(stat) {
    const row = make("div", "mc-stat" + (stat.core ? " is-core" : ""));

    const head = make("div", "mc-stat-head");
    // null heisst "nicht erhoben" - niemals als 0 darstellen.
    head.appendChild(make("span", "mc-stat-value",
        stat.home === null || stat.home === undefined ? "–" : String(stat.home)));
    head.appendChild(make("span", "mc-stat-label", localizedMatchStatLabel(stat)));
    head.appendChild(make("span", "mc-stat-value",
        stat.away === null || stat.away === undefined ? "–" : String(stat.away)));
    row.appendChild(head);

    const share = mcStatShare(stat.home, stat.away);
    if (share !== null) {
        const bar = make("div", "mc-stat-bar");
        const homeBar = make("div", "mc-stat-bar-home");
        homeBar.style.width = `${share}%`;
        bar.appendChild(homeBar);
        row.appendChild(bar);
    }

    return row;
}

function mcRenderStats(data) {
    const target = MC_TABS.stats;
    target.innerHTML = "";

    if (data.statistics_available === false) {
        target.appendChild(mcBuildNote(t("matchCenter.statisticsUnavailable")));
        return;
    }

    if (!data.statistics.length) {
        target.appendChild(mcBuildNote(t("matchCenter.statisticsPending")));
        return;
    }

    const head = make("div", "mc-stat-teams");
    head.appendChild(make("span", "mc-stat-team", data.home.name || ""));
    head.appendChild(make("span", "mc-stat-team", data.away.name || ""));
    target.appendChild(head);

    const list = make("div", "mc-stat-list");
    data.statistics.forEach(stat => list.appendChild(mcBuildStatRow(stat)));
    target.appendChild(list);
}

/**
 * Neutraler Hinweis fuer "Daten liegen (noch) nicht vor".
 *
 * Bewusst dieselbe ruhige Optik wie andere Hinweise im Projekt und
 * KEINE Fehlerdarstellung: fehlende Aufstellungen vor Anpfiff sind der
 * Normalfall, kein Defekt.
 */
function mcBuildNote(text) {
    return make("div", "loading-hint", text);
}

function mcRenderAll(data) {
    mcScoreboard.innerHTML = "";
    mcScoreboard.appendChild(mcBuildScoreboard(data));
    show(mcScoreboard);

    mcRenderOverview(data);
    mcRenderLineups(data);
    mcRenderEvents(data);
    mcRenderStats(data);

    show(mcTabBar);
}


/* ---------- 16d2. Reiter ---------- */

function mcSetTab(tabName) {
    if (!MC_TABS[tabName]) return;

    mcState.activeTab = tabName;

    document.querySelectorAll("#mc-tab-bar .tab-btn").forEach(button => {
        const isActive = button.dataset.mctab === tabName;
        button.classList.toggle("active", isActive);
        if (isActive) {
            button.setAttribute("aria-current", "true");
        } else {
            button.removeAttribute("aria-current");
        }
    });

    Object.keys(MC_TABS).forEach(name => {
        // Ein Reiterwechsel zeigt nur um - er laedt nichts nach.
        MC_TABS[name].classList.toggle("hidden", name !== tabName);
    });
}

document.querySelectorAll("#mc-tab-bar .tab-btn").forEach(button => {
    button.addEventListener("click", () => mcSetTab(button.dataset.mctab));
});


/* ---------- 16d3. Laden, Oeffnen, Schliessen ---------- */

async function mcLoad(options) {
    if (!mcView || mcState.fixtureId === null) return;

    const background = !!(options && options.background);
    const token = ++mcState.requestToken;
    const fixtureId = mcState.fixtureId;

    mcState.loading = true;

    if (!background) mcSetStatus(t("matchCenter.loading"));

    try {
        const data = await fetchJson(`/api/live-match?fixture=${encodeURIComponent(fixtureId)}`);

        // Der Nutzer hat inzwischen ein anderes Spiel geoeffnet oder das
        // Match Center verlassen - diese Antwort ist ueberholt.
        if (token !== mcState.requestToken) return;

        mcState.data = data;
        mcRenderAll(data);

        // Der gewaehlte Reiter bleibt beim Hintergrund-Refresh erhalten.
        mcSetTab(mcState.activeTab);

        if (data.stale) {
            mcSetStatus(t("matchCenter.stale"));
        } else {
            mcSetStatus("");
        }

        mcScheduleAutoRefresh(data);

    } catch (error) {
        if (token !== mcState.requestToken) return;

        // Ein fehlgeschlagener Hintergrund-Tick laesst die sichtbare
        // Ansicht unveraendert stehen.
        if (!background) {
            mcSetStatus(error.message || t("matchCenter.unavailable"));
            hide(mcScoreboard);
            hide(mcTabBar);
        }

        mcStopAutoRefresh();

    } finally {
        if (token === mcState.requestToken) mcState.loading = false;
    }
}

function mcOpen(fixtureId) {
    if (fixtureId === null || fixtureId === undefined) return;

    // Die Tagesliste bleibt im DOM stehen und wird nur verdeckt - der
    // Zurueck-Weg braucht dadurch kein erneutes Laden.
    mcState.open = true;
    mcState.fixtureId = fixtureId;
    mcState.data = null;
    mcState.activeTab = "overview";

    // Solange das Match Center offen ist, poll die verdeckte Liste nicht.
    liveStopAutoRefresh();

    hide(mcListView);
    show(mcView);

    hide(mcScoreboard);
    hide(mcTabBar);
    Object.keys(MC_TABS).forEach(name => { MC_TABS[name].innerHTML = ""; });
    mcSetTab("overview");

    window.scrollTo({ top: 0, behavior: "auto" });

    mcLoad();
}

function mcClose() {
    mcState.open = false;
    mcState.fixtureId = null;
    mcState.data = null;

    // Laufende Antwort verwerfen, damit sie die Liste nicht mehr anfasst.
    mcState.requestToken++;
    mcStopAutoRefresh();

    hide(mcView);
    show(mcListView);

    window.scrollTo({ top: 0, behavior: "auto" });

    // Die Liste steht unveraendert auf dem vorher gewaehlten Tag. Nur
    // wenn dort etwas laufen kann, wird ihr Auto-Refresh wieder
    // aufgenommen - liveShouldAutoRefresh() entscheidet das selbst.
    liveScheduleAutoRefresh(liveState.lastData);
}

if (mcBackBtn) mcBackBtn.addEventListener("click", mcClose);


/* ---------- 16d4. Auto-Refresh des Match Centers ---------- */

function mcStopAutoRefresh() {
    if (mcState.refreshTimer !== null) {
        clearInterval(mcState.refreshTimer);
        mcState.refreshTimer = null;
    }
}

/** Alle Bedingungen muessen gleichzeitig gelten - sonst kein Timer. */
function mcShouldAutoRefresh(data) {
    return state.activeArea === "live" &&
        mcState.open &&
        !!data &&
        data.fixture &&
        data.fixture.is_live === true &&
        document.visibilityState === "visible";
}

/** Startet oder stoppt den Timer. Raeumt immer zuerst auf - nie zwei parallel. */
function mcScheduleAutoRefresh(data) {
    mcStopAutoRefresh();

    if (!mcShouldAutoRefresh(data)) return;

    mcState.refreshTimer = setInterval(() => {
        if (!mcShouldAutoRefresh(mcState.data)) {
            mcStopAutoRefresh();
            return;
        }
        mcLoad({ background: true });
    }, MC_REFRESH_INTERVAL_MS);
}


/* ---------- 16d5. DETAIL-VIEW-STACK (Block LIVE D2) ----------

   Generische "verstecken / anzeigen / vorherige Ansicht merken"-Logik
   fuer Detailansichten, die unabhaengig vom aktiven Hauptbereich
   (state.activeArea) angezeigt werden - das Spielerprofil (D1, seit
   dieser Version darauf umgestellt) und das Teamprofil (D2).

   Warum das jetzt einen eigenen, kleinen Stack braucht statt wie in D1
   einfach den urspruenglichen .app-area-Knoten zu merken: D2 fuehrt
   echte Verschachtelung ein (Match -> Team -> Spieler aus dem Kader).
   Ohne einen Stack muesste die Spieleransicht wissen, ob sie ueber dem
   Match Center oder ueber dem Teamprofil liegt - mit dem Stack merkt
   sich jede Ebene nur "was war unmittelbar davor sichtbar" und stellt
   beim Schliessen genau das wieder her, beliebig tief verschachtelbar,
   ohne dass eine Ansicht von der anderen weiss.

   Bewusst KEIN Router, keine History-API, keine URL-Zustaende - nur
   eine kleine Sichtbarkeitsverwaltung fuer die Faelle, die es in
   FootSim gibt.

   Bewusst KEIN Aufruf von setActiveArea(): das wuerde ueber dessen
   eigene Logik den Match-Center-Auto-Refresh stoppen
   (mcStopAutoRefresh()) und die Navigation auf einen anderen
   Hauptbereich umschalten - fuer einen Tap innerhalb von LIVE waere
   beides ein unerwuenschter Bereichswechsel. Der jeweils darunter
   liegende Bereich/Ansicht wird stattdessen direkt per .hidden-Klasse
   versteckt; sein State (mcState, aktiver Tab, Timer) wird dabei nie
   angefasst.
------------------------------------------------------------------- */

const detailViewStack = [];

/**
 * Zeigt viewNode an und merkt sich, was zuvor sichtbar war.
 *
 * Der zu versteckende Knoten ist entweder die bereits oben liegende
 * Detailansicht (ein zweiter, verschachtelter Tap - z. B. ein
 * Kaderspieler innerhalb des Teamprofils) oder, beim allerersten
 * Oeffnen, der gerade aktive .app-area-Knoten.
 *
 * Ist viewNode bereits die oberste Ansicht (z. B. ein zweiter Tap auf
 * einen anderen Spieler, waehrend das Profil schon offen ist), wird
 * nichts an der Sichtbarkeit oder am Stack veraendert - nur der
 * Aufrufer laedt anschliessend neue Daten.
 */
function openDetailView(viewNode) {
    if (!viewNode) return;

    const top = detailViewStack[detailViewStack.length - 1];
    if (top && top.view === viewNode) return;

    const toHide = top
        ? top.view
        : document.querySelector(`.app-area[data-area="${state.activeArea}"]`);

    if (toHide) hide(toHide);

    detailViewStack.push({ view: viewNode, hidden: toHide });
    show(viewNode);
    window.scrollTo({ top: 0, behavior: "auto" });
}

/** Schliesst die zuletzt geoeffnete Detailansicht und zeigt die vorherige. */
function closeDetailView() {
    const entry = detailViewStack.pop();
    if (!entry) return;

    hide(entry.view);
    if (entry.hidden) show(entry.hidden);

    window.scrollTo({ top: 0, behavior: "auto" });
}


/* ---------- 16e. SPIELERPROFIL (Block LIVE D1) ----------

   Ein einzelner Spieler im Detail - erreichbar durch Antippen eines
   Spielers im Match Center (Pitch oder Bank/Liste) ODER eines
   Kaderspielers im Teamprofil (D2). player_id kommt unveraendert aus
   dataset.playerId (siehe mcBuildPitchPlayer/mcBuildPlayerRow, Block
   LIVE C, bzw. tdBuildSquadEntry, Block LIVE D2), die Saison aus
   data.league.season des Match-Center-Payloads bzw. wird beim
   Kader-Tap weggelassen (siehe pdOpen-Aufrufer). Keine Namenssuche,
   kein zusaetzlicher Request nur fuer die Saison.

   Zeigen/Verstecken laeuft seit D2 ueber den generischen
   Detail-View-Stack oben (openDetailView/closeDetailView) - die
   eigentliche Spieler-Fachlogik (pdLoad, pdRenderAll, Scopes,
   "Vergleichen") ist davon unberuehrt.

   Einzige gewollte Ausnahme vom "kein Bereichswechsel"-Prinzip ist der
   "Vergleichen"-Knopf: er verlaesst bewusst den aktuellen Kontext und
   wechselt in den Spielerbereich - das ist eine explizite
   Nutzerentscheidung, kein impliziter Sprung.
------------------------------------------------------------------- */

const pdView        = el("player-detail-view");
const pdBackBtn      = el("pd-back");
const pdBackLabel    = el("pd-back-label");
const pdStatus       = el("pd-status");
const pdHeader       = el("pd-header");
const pdScopeBlock   = el("pd-scope-block");
const pdScopeNote    = el("pd-scope-note");
const pdStatsBox     = el("pd-stats");
const pdCompareBtn   = el("pd-compare-btn");

const pdState = {
    open: false,
    playerId: null,
    season: null,
    scope: "club_all",
    // Rueckennummer aus dem LIVE-Aufstellungskontext, falls vorhanden.
    // Kommt NICHT aus /api/player-profile - die Analyse hat gezeigt, dass
    // /players keine verlaessliche aktuelle Nummer liefert. Der Client
    // kennt sie hier bereits aus dem Match-Center-Payload, ein zweiter
    // Weg ueber den Server waere unnoetig.
    contextNumber: null,
    // "live" oder "team" - nur fuer die Beschriftung des Zurueck-Knopfs.
    // Direktintegration aus der Spielersuche (D1, Abschnitt 12) bleibt
    // weiterhin bewusst zurueckgestellt, um den Radar-/Plots-Workflow
    // nicht anzufassen.
    returnTo: null,
    requestToken: 0,
    data: null,
};

function pdSetStatus(text) {
    if (pdStatus) pdStatus.textContent = text;
}

function pdBuildInfoRow(label, value) {
    if (value === null || value === undefined || value === "") return null;
    const row = make("div", "mc-info-row");
    row.appendChild(make("span", "mc-info-label", label));
    row.appendChild(make("span", "mc-info-value", String(value)));
    return row;
}

function pdBuildHeader(data) {
    pdHeader.innerHTML = "";

    const figure = mcBuildAvatar({ name: data.name, photo: data.photo });
    pdHeader.appendChild(figure);

    const identity = make("div", "pd-identity");
    identity.appendChild(make("h2", "pd-name", data.name || t("player.unknown")));

    const meta = make("div", "pd-meta-row");
    if (data.team_logo) meta.appendChild(crest(data.team_logo, "pd-team-logo"));
    if (data.team_name) meta.appendChild(make("span", "pd-team-name", data.team_name));
    if (data.position_label) meta.appendChild(make("span", "pd-badge", data.position_label));
    if (pdState.contextNumber !== null && pdState.contextNumber !== undefined) {
        meta.appendChild(make("span", "pd-badge", `#${pdState.contextNumber}`));
    }
    identity.appendChild(meta);

    pdHeader.appendChild(identity);
    show(pdHeader);

    const rows = [
        pdBuildInfoRow(t("profile.nationality"), data.nationality),
        pdBuildInfoRow(t("profile.age"), data.age),
        pdBuildInfoRow(t("profile.birthDate"), data.birth_date),
        pdBuildInfoRow(t("profile.height"), data.height),
        pdBuildInfoRow(t("profile.weight"), data.weight),
    ].filter(Boolean);

    return rows;
}

/** Kernwerte als Kachel-Raster: Spiele, Minuten, Tore, Assists, Bewertung. */
function pdBuildCoreGrid(coreStats) {
    const grid = make("div", "pd-core-grid");
    (coreStats || []).forEach(stat => {
        const tile = make("div", "pd-core-tile");
        tile.appendChild(make("span", "pd-core-value", pcFormatValue(stat.value, stat.kind)));
        tile.appendChild(make("span", "pd-core-label", stat.label));
        grid.appendChild(tile);
    });
    return grid;
}

/** Weitere Statistiken als Label/Wert-Liste - dieselbe Optik wie mc-info-row. */
function pdBuildExtraList(extraStats) {
    const wrap = make("div", "mc-info");
    (extraStats || []).forEach(stat => {
        const row = make("div", "mc-info-row");
        row.appendChild(make("span", "mc-info-label", stat.label));
        row.appendChild(make("span", "mc-info-value", pcFormatValue(stat.value, stat.kind)));
        wrap.appendChild(row);
    });
    return wrap;
}

function pdSetScopeButtons(scope) {
    document.querySelectorAll("#pd-scope-nav .pc-scope-btn").forEach(button => {
        const isActive = button.dataset.scope === scope;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-checked", isActive ? "true" : "false");
    });
}

/**
 * Ein gewonnener Titel - Wettbewerb links, Anzahl rechts. Dieselbe Optik
 * wie mc-info-row (Block D2+). Das Land steht als Tooltip am
 * Wettbewerbsnamen, nicht als eigene Spalte - kompakt bleibt kompakt.
 */
function pdBuildTrophyRow(trophy) {
    const row = make("div", "mc-info-row");

    const label = make("span", "mc-info-label", trophy.league);
    if (trophy.country) label.title = trophy.country;
    row.appendChild(label);

    row.appendChild(make("span", "mc-info-value", `${trophy.count}×`));
    return row;
}

/**
 * Erfolge-Abschnitt. Nur ECHTE, vom Provider bestaetigte Titel
 * (place === "Winner", bereits serverseitig gefiltert und gruppiert -
 * siehe normalize_trophies() in player_compare_loader.py). Ohne Titel
 * entfaellt der ganze Abschnitt einfach, statt einen leeren oder
 * neutralen Hinweis zu zeigen - "keine Erfolge" waere hier eher
 * verstimmend als informativ.
 */
function pdBuildTrophiesSection(trophies) {
    if (!trophies || !trophies.length) return null;

    const box = make("div");
    box.appendChild(make("p", "mc-lineup-label", t("profile.trophies")));

    const list = make("div", "mc-info");
    trophies.forEach(trophy => list.appendChild(pdBuildTrophyRow(trophy)));
    box.appendChild(list);

    return box;
}

function pdRenderAll(data) {
    pdStatsBox.innerHTML = "";

    const identityRows = pdBuildHeader(data);

    const identityBox = make("div", "mc-info");
    identityRows.forEach(row => identityBox.appendChild(row));
    if (identityRows.length) pdStatsBox.appendChild(identityBox);

    // Wettbewerbsumfang: dieselben sieben Scopes wie im Spielervergleich.
    pdSetScopeButtons(data.scope);
    pdScopeNote.textContent = (PC_TEXT.scopeHint[data.scope] && PC_TEXT.scopeHint[data.scope]())
        || (activeLocale === "de" ? data.scope_hint || "" : "");
    show(pdScopeBlock);

    // data_available bedeutet "im Pool der fuenf Vergleichsligen
    // vertreten" (Perzentil-Faehigkeit) - NICHT "hat Werte". Ein Spieler
    // ausserhalb der fuenf Ligen kann trotzdem echte Zahlen haben, z. B.
    // aus seinen Champions-League-Auftritten (Cup-Bloecke sind in
    // club_all immer zulaessig, siehe entry_matches_scope() in
    // player_compare_loader.py). Massgeblich ist deshalb, ob ueberhaupt
    // ein Kernwert vorliegt - nicht das Pool-Flag.
    const hasAnyCoreValue = (data.core_stats || [])
        .some(stat => stat.value !== null && stat.value !== undefined);

    if (!hasAnyCoreValue) {
        // Normaler Zustand, z. B. vor jedem Einsatz in der Saison oder bei
        // einem Wettbewerbsumfang ohne jede Teilnahme (Spieler ohne
        // WM-Einsatz im Scope "world_cup") - kein technischer Fehler,
        // nur eine ehrliche, neutrale Meldung.
        pdStatsBox.appendChild(mcBuildNote(
            t("profile.noStats")
        ));
    } else {
        pdStatsBox.appendChild(make("p", "mc-lineup-label", t("profile.coreStats")));
        pdStatsBox.appendChild(pdBuildCoreGrid(data.core_stats));

        if ((data.extra_stats || []).length) {
            pdStatsBox.appendChild(make("p", "mc-lineup-label", t("profile.extraStats")));
            pdStatsBox.appendChild(pdBuildExtraList(data.extra_stats));
        }

        if (!data.data_available) {
            // Zahlen sind da, aber ausserhalb des Fuenf-Ligen-Pools -
            // ehrlich einordnen, ohne die Werte zu verstecken.
            pdStatsBox.appendChild(mcBuildNote(
                t("profile.outsideTopFive")
            ));
        }
    }

    // Erfolge sind saisonunabhaengig (siehe get_player_trophies) - werden
    // deshalb IMMER angehaengt, unabhaengig vom hasAnyCoreValue-Zweig
    // oben, der nur die scope-abhaengigen Saisonwerte betrifft.
    const trophiesSection = pdBuildTrophiesSection(data.trophies);
    if (trophiesSection) pdStatsBox.appendChild(trophiesSection);

    show(pdStatsBox);
    show(pdCompareBtn);
}

async function pdLoad(options) {
    if (!pdView || pdState.playerId === null) return;

    const background = !!(options && options.background);
    const token = ++pdState.requestToken;
    const playerId = pdState.playerId;

    if (!background) {
        pdSetStatus(t("profile.loading"));
        hide(pdHeader);
        hide(pdScopeBlock);
        hide(pdStatsBox);
        hide(pdCompareBtn);
    }

    try {
        const params = new URLSearchParams({
            player_id: String(playerId),
            scope: pdState.scope,
        });
        if (pdState.season !== null && pdState.season !== undefined) {
            params.set("season", String(pdState.season));
        }

        const data = await fetchJson(`/api/player-profile?${params.toString()}`);

        // Der Nutzer hat inzwischen einen anderen Spieler geoeffnet oder
        // das Profil verlassen - diese Antwort ist ueberholt.
        if (token !== pdState.requestToken) return;

        const localizedData = {
            ...data,
            position_label: translatedPosition(data.position, data.position_label || ""),
            core_stats: (data.core_stats || []).map(localizedMetric),
            extra_stats: (data.extra_stats || []).map(localizedMetric),
        };
        pdState.data = localizedData;
        pdRenderAll(localizedData);
        pdSetStatus("");

    } catch (error) {
        if (token !== pdState.requestToken) return;
        pdSetStatus(error.message || t("profile.unavailable"));
    }
}

function pdSetScope(scope) {
    if (scope === pdState.scope) return;
    pdState.scope = scope;
    pdLoad();
}

document.querySelectorAll("#pd-scope-nav .pc-scope-btn").forEach(button => {
    button.addEventListener("click", () => pdSetScope(button.dataset.scope));
});

/**
 * Oeffnet das Spielerprofil.
 *
 * options.season:        API-Football-Saisonjahr. Aus LIVE immer
 *                         data.league.season des Match-Center-Payloads.
 * options.contextNumber: Rueckennummer aus dem Aufstellungskontext,
 *                         optional - siehe pdState.contextNumber.
 * options.returnTo:       nur fuer die Beschriftung des Zurueck-Knopfs
 *                         ("live" oder "team").
 */
function pdOpen(playerId, options) {
    if (playerId === null || playerId === undefined) return;

    const opts = options || {};

    pdState.open = true;
    pdState.playerId = playerId;
    pdState.season = opts.season ?? null;
    pdState.scope = "club_all";
    pdState.contextNumber = opts.contextNumber ?? null;
    pdState.returnTo = opts.returnTo || null;
    pdState.data = null;

    pdBackLabel.textContent =
        pdState.returnTo === "live" ? t("profile.backToMatch") :
        pdState.returnTo === "team" ? t("profile.backToTeam") :
        t("profile.back");

    openDetailView(pdView);
    pdLoad();
}

function pdClose() {
    pdState.open = false;
    pdState.playerId = null;
    pdState.data = null;
    pdState.requestToken++;

    closeDetailView();
}

if (pdBackBtn) pdBackBtn.addEventListener("click", pdClose);


/* ---------- 16f. "Vergleichen" (Uebergabe an den Spielervergleich) ----------

   Uebernimmt den gerade angezeigten Spieler in den bestehenden
   Spielervergleich (pcState/pcSelectPlayer, siehe Abschnitt 16d oben -
   dieselbe Architektur, kein zweiter Vergleichsmechanismus).

   Zielslot: der erste freie von A/B, sonst A. pcState.position wird
   bewusst NICHT veraendert - der Nutzer waehlt die Gegenseite frei.
------------------------------------------------------------------- */

function pdPickCompareSlot() {
    if (!pcState.a.player) return "a";
    if (!pcState.b.player) return "b";
    return "a";
}

async function pdCompare() {
    const data = pdState.data;
    if (!data || data.player_id === null || data.player_id === undefined) return;

    // Saisonauswahl muss stehen, bevor ein Slot befuellt wird - dieselbe
    // Absicherung wie pcHandleInput() beim ersten Suchversuch.
    await pcInitControls();

    const slot = pdPickCompareSlot();

    pcState[slot].season = data.season || pcState[slot].season;
    if (pcSeasonSelects[slot] && pcState[slot].season) {
        pcSeasonSelects[slot].value = String(pcState[slot].season);
    }

    pcSelectPlayer(slot, {
        player_id: data.player_id,
        name: data.name,
        photo: data.photo,
        age: data.age,
        nationality: data.nationality,
        season: data.season,
        team_name: data.team_name,
        team_logo: data.team_logo,
        league_code: data.league_code,
        league_label: data.league_label,
        position: data.position,
        position_label: data.position_label,
        minutes: data.minutes,
        comparable: data.data_available,
    });

    pdClose();
    setActiveArea("players");
    pcSetMode("radar");
}

if (pdCompareBtn) pdCompareBtn.addEventListener("click", pdCompare);


/* ---------- 16g. TEAMPROFIL (Block LIVE D2) ----------

   Ein Team im Detail - erreichbar durch Antippen von Heim- oder
   Auswaertsteam im Match Center (Anzeigetafel oder Aufstellungskopf).
   team_id kommt unveraendert aus data.home.id/data.away.id bzw.
   lineup.team_id (beide seit LIVE B/C vorhanden), league_id/season aus
   data.league.id/data.league.season (season seit Block D1 vorhanden) -
   alles bereits im geladenen Match-Center-Payload, kein zusaetzlicher
   Request nur fuer diese drei Werte.

   Zeigen/Verstecken laeuft ueber denselben Detail-View-Stack wie das
   Spielerprofil (Abschnitt 16d5). Ein Kaderspieler antippen oeffnet das
   BESTEHENDE Spielerprofil (pdOpen) ueber dem Teamprofil - keine zweite
   Player-Detail-Implementierung, keine zusaetzlichen Player-Requests
   fuer den ganzen Kader, nur beim tatsaechlichen Oeffnen eines
   konkreten Spielers.
------------------------------------------------------------------- */

const tdView      = el("team-detail-view");
const tdBackBtn    = el("td-back");
const tdBackLabel  = el("td-back-label");
const tdStatus     = el("td-status");
const tdHeader     = el("td-header");
const tdBody       = el("td-body");

const tdState = {
    open: false,
    teamId: null,
    leagueId: null,
    season: null,
    returnTo: null,
    requestToken: 0,
    data: null,
};

function tdSetStatus(text) {
    if (tdStatus) tdStatus.textContent = text;
}

function tdBuildHeader(data) {
    tdHeader.innerHTML = "";

    const team = data.team;
    if (team.logo) tdHeader.appendChild(crest(team.logo, "td-logo"));

    const identity = make("div", "td-identity");
    identity.appendChild(make("h2", "td-name", team.name || t("player.unknown")));

    const metaParts = [team.country, [team.venue_name, team.venue_city].filter(Boolean).join(", ")]
        .filter(Boolean);
    if (metaParts.length) {
        identity.appendChild(make("div", "td-meta-row", metaParts.join(" · ")));
    }

    tdHeader.appendChild(identity);
    show(tdHeader);
}

/**
 * Dezentes Stadionbild, falls venue.image gueltig ist (Block D2+).
 *
 * Bewusst KEIN mcBuildAvatar-artiger Umgang mit dem Fallback: bei einem
 * kaputten/fehlenden Bild verschwindet der ganze Block per photo.onerror
 * (element.remove()), statt eine leere, sichtbare Flaeche zu
 * hinterlassen - anders als bei einem kleinen Avatar waere eine leere
 * Bildflaeche in dieser Groesse deutlich sichtbar kaputt.
 */
function tdBuildVenueImage(url) {
    if (!url) return null;

    const wrap = make("div", "td-venue-image-wrap");
    const img = document.createElement("img");
    img.src = url;
    img.alt = "";
    img.loading = "lazy";
    img.className = "td-venue-image";
    img.onerror = () => { wrap.remove(); };
    wrap.appendChild(img);
    return wrap;
}

/** Tausendertrennzeichen fuer die Zuschauerkapazitaet, sonst unveraendert. */
function tdFormatCapacity(capacity) {
    if (capacity === null || capacity === undefined) return null;
    const number = Number(capacity);
    return Number.isFinite(number) ? number.toLocaleString(activeIntlLocale()) : null;
}

/**
 * Kompakte Club Facts - dieselbe Kachel-Optik wie die Tabellenwerte
 * (pd-core-grid) und die Kernwerte im Spielerprofil. Nur Kacheln fuer
 * tatsaechlich vorhandene Werte - nichts als "–" oder "0" erfunden.
 *
 * Adresse wird bewusst NICHT als eigene Kachel gezeigt (zu lang, zu
 * wenig Mehrwert neben Stadionname+Stadt), sondern nur als Titel-Tooltip
 * auf der Stadion-Kachel - kein Informationsverlust, aber kompakt.
 */
function tdBuildFactsGrid(team) {
    const tiles = [];

    if (team.founded) tiles.push([t("team.facts.founded"), String(team.founded), null]);
    if (team.venue_name) tiles.push([t("team.facts.venue"), team.venue_name, team.venue_address]);

    const capacity = tdFormatCapacity(team.venue_capacity);
    if (capacity) tiles.push([t("team.facts.capacity"), capacity, null]);

    const cityCountry = [team.country, team.venue_city].filter(Boolean).join(" · ");
    if (cityCountry) tiles.push([t("team.facts.location"), cityCountry, null]);

    if (!tiles.length) return null;

    const grid = make("div", "pd-core-grid");
    tiles.forEach(([label, value, title]) => {
        const tile = make("div", "pd-core-tile");
        const valueNode = make("span", "pd-core-value", value);
        if (title) valueNode.title = title;
        tile.appendChild(valueNode);
        tile.appendChild(make("span", "pd-core-label", label));
        grid.appendChild(tile);
    });
    return grid;
}

/** Ein Kachel-Raster fuer die Tabellenwerte - dieselbe Optik wie pd-core-grid. */
function tdBuildStandingsTiles(standings) {
    const grid = make("div", "pd-core-grid");

    const tiles = [
        [t("team.standings.rank"), standings.rank !== null && standings.rank !== undefined ? `#${standings.rank}` : "–"],
        [t("team.standings.points"), standings.points ?? "–"],
        [t("team.standings.goalDifference"), standings.goals_diff !== null && standings.goals_diff !== undefined
            ? (standings.goals_diff > 0 ? `+${standings.goals_diff}` : String(standings.goals_diff))
            : "–"],
        [t("team.standings.record"), (standings.wins ?? "–") + "-" + (standings.draws ?? "–") + "-" + (standings.losses ?? "–")],
    ];

    tiles.forEach(([label, value]) => {
        const tile = make("div", "pd-core-tile");
        tile.appendChild(make("span", "pd-core-value", String(value)));
        tile.appendChild(make("span", "pd-core-label", label));
        grid.appendChild(tile);
    });

    return grid;
}

/** Form-Badges aus dem fertigen "form"-String der Quelle (z. B. "DLDWL"). */
function tdBuildFormRow(form) {
    if (!form) return null;

    const row = make("div", "td-form-row");
    form.split("").forEach(letter => {
        const kind = letter === "W" ? "is-w" : letter === "L" ? "is-l" : "is-d";
        row.appendChild(make("span", `td-form-badge ${kind}`, letter));
    });
    return row;
}

function tdBuildStandingsSection(standings) {
    if (!standings) {
        return mcBuildNote(t("team.standings.unavailable"));
    }

    const box = make("div");
    box.appendChild(make("p", "mc-lineup-label", t("team.standings.title")));
    box.appendChild(tdBuildStandingsTiles(standings));

    const formRow = tdBuildFormRow(standings.form);
    if (formRow) box.appendChild(formRow);

    // "description" ist seit der CL/EL-Ligaphasen-Reform keine klassische
    // Gruppenaussage mehr (z. B. "Promotion - Champions League (Play
    // Offs: 1/16-finals)") - unveraendert als Text gezeigt, nicht als
    // "Gruppe X" umgedeutet.
    if (standings.description) {
        box.appendChild(make("p", "td-standings-note", standings.description));
    }

    return box;
}

function tdBuildFixtureRow(fixture, kind) {
    const row = make("div", "td-fixture-row");

    row.appendChild(make("span", "td-fixture-date", fixture.kickoff_time || "–"));
    if (fixture.opponent_logo) row.appendChild(crest(fixture.opponent_logo, "td-fixture-logo"));

    let opponentNode;
    if (fixture.opponent_id !== null && fixture.opponent_id !== undefined) {
        opponentNode = make("a", "td-fixture-opponent tappable", fixture.opponent_name || t("player.unknown"));
        opponentNode.href = "#";
        opponentNode.addEventListener("click", (e) => {
            e.preventDefault();
            tdOpen(fixture.opponent_id, { returnTo: "team:" + tdState.teamId });
        });
    } else {
        opponentNode = make("span", "td-fixture-opponent", fixture.opponent_name || t("player.unknown"));
    }
    row.appendChild(opponentNode);

    row.appendChild(make("span", "td-fixture-side",
        fixture.is_home ? t("team.fixture.home") : t("team.fixture.away")));

    if (kind === "recent") {
        const hasScore = fixture.team_goals !== null && fixture.team_goals !== undefined;
        row.appendChild(make("span", "td-fixture-result",
            hasScore ? `${fixture.team_goals}:${fixture.opponent_goals}` : "–"));
    } else {
        // Kommendes Spiel: KEIN erfundenes Ergebnis, nur der Status.
        row.appendChild(make("span", "td-fixture-result", localizedLiveStatus(fixture)));
    }

    return row;
}

function tdBuildFixtureSection(title, fixtures, kind, emptyText) {
    const box = make("div");
    box.appendChild(make("p", "mc-lineup-label", title));

    if (!fixtures || !fixtures.length) {
        box.appendChild(mcBuildNote(emptyText));
        return box;
    }

    const list = make("div", "td-fixture-list");
    fixtures.forEach(fixture => list.appendChild(tdBuildFixtureRow(fixture, kind)));
    box.appendChild(list);
    return box;
}

/**
 * Ein Kaderspieler - tappable, oeffnet das BESTEHENDE Spielerprofil
 * (Block LIVE D1). Keine Saisonstatistik wird hier geladen; /players/
 * squads liefert ohnehin keine, und /api/player-profile faellt ohne
 * season-Parameter auf die aktuelle Saison zurueck (siehe app.py) -
 * fuer einen Kadereintrag ist das genau richtig.
 */
function tdBuildSquadEntry(player) {
    const entry = make("div", "td-squad-entry");

    entry.appendChild(mcBuildAvatar({ name: player.name, photo: player.photo }));
    entry.appendChild(make("span", "td-squad-name", mcShortName(player.name) || t("player.unknown")));

    const metaParts = [];
    if (player.number !== null && player.number !== undefined) metaParts.push(`#${player.number}`);
    if (player.position) metaParts.push(player.position);
    if (metaParts.length) entry.appendChild(make("span", "td-squad-meta", metaParts.join(" · ")));

    if (player.id !== null && player.id !== undefined) {
        entry.dataset.playerId = player.id;
        mcMakeTappable(entry, () => pdOpen(player.id, {
            contextNumber: player.number ?? null,
            returnTo: "team",
        }));
    }

    return entry;
}

function tdBuildSquadSection(squad) {
    const box = make("div");
    box.appendChild(make("p", "mc-lineup-label", t("team.squad.title")));

    if (!squad || !squad.length) {
        box.appendChild(mcBuildNote(t("team.squad.unavailable")));
        return box;
    }

    const grid = make("div", "td-squad-grid");
    squad.forEach(player => grid.appendChild(tdBuildSquadEntry(player)));
    box.appendChild(grid);
    return box;
}

function tdBuildCoachSection(coach) {
    const box = make("div");
    box.appendChild(make("p", "mc-lineup-label", t("team.coach.title")));

    if (!coach) {
        box.appendChild(mcBuildNote(t("team.coach.unavailable")));
        return box;
    }

    const row = make("div", "td-coach-row");
    row.appendChild(mcBuildAvatar({ name: coach.name, photo: coach.photo }));

    const info = make("div", "td-coach-info");
    info.appendChild(make("div", "td-coach-name", coach.name || t("player.unknown")));

    const metaParts = [];
    if (coach.nationality) metaParts.push(coach.nationality);
    if (coach.age !== null && coach.age !== undefined) {
        metaParts.push(t("player.age", { count: coach.age }));
    }
    if (coach.since) metaParts.push(t("team.coach.since", { date: coach.since }));
    if (metaParts.length) info.appendChild(make("div", "td-coach-meta", metaParts.join(" · ")));

    row.appendChild(info);
    box.appendChild(row);
    return box;
}

function tdRenderAll(data) {
    tdBuildHeader(data);

    tdBody.innerHTML = "";

    // Club Facts (Block D2+): dezentes Stadionbild, falls vorhanden, dann
    // die Kachelreihe. Beide nutzen ausschliesslich Felder aus derselben
    // teams?id=-Antwort, die die Identitaet im Header schon geliefert hat -
    // kein zusaetzlicher Request.
    const venueImage = tdBuildVenueImage(data.team.venue_image);
    if (venueImage) tdBody.appendChild(venueImage);

    const factsGrid = tdBuildFactsGrid(data.team);
    if (factsGrid) tdBody.appendChild(factsGrid);

    tdBody.appendChild(tdBuildStandingsSection(data.standings));
    tdBody.appendChild(tdBuildFixtureSection(
        t("team.fixtures.recent"), data.recent_fixtures, "recent", t("team.fixtures.recentEmpty")));
    tdBody.appendChild(tdBuildFixtureSection(
        t("team.fixtures.upcoming"), data.upcoming_fixtures, "upcoming", t("team.fixtures.upcomingEmpty")));
    tdBody.appendChild(tdBuildSquadSection(data.squad));
    tdBody.appendChild(tdBuildCoachSection(data.coach));

    show(tdBody);
}

async function tdLoad(options) {
    if (!tdView || tdState.teamId === null) return;

    const background = !!(options && options.background);
    const token = ++tdState.requestToken;
    const teamId = tdState.teamId;

    if (!background) {
        tdSetStatus(t("team.loading"));
        hide(tdHeader);
        hide(tdBody);
    }

    try {
        const params = new URLSearchParams({ team_id: String(teamId) });
        if (tdState.leagueId !== null && tdState.leagueId !== undefined) {
            params.set("league_id", String(tdState.leagueId));
        }
        if (tdState.season !== null && tdState.season !== undefined) {
            params.set("season", String(tdState.season));
        }

        const data = await fetchJson(`/api/team-detail?${params.toString()}`);

        // Der Nutzer hat inzwischen ein anderes Team geoeffnet oder das
        // Profil verlassen - diese Antwort ist ueberholt.
        if (token !== tdState.requestToken) return;

        tdState.data = data;
        tdRenderAll(data);
        tdSetStatus("");

    } catch (error) {
        if (token !== tdState.requestToken) return;
        tdSetStatus(error.message || t("team.unavailable"));
    }
}

/**
 * Oeffnet das Teamprofil.
 *
 * options.leagueId: API-Football-Liga-ID des Wettbewerbs, aus dem das
 *                   Team geoeffnet wurde - bestimmt, gegen welche
 *                   Tabelle die Zeile gezogen wird.
 * options.season:   API-Football-Saisonjahr, ebenfalls fuer die Tabelle.
 * options.returnTo: nur fuer die Beschriftung des Zurueck-Knopfs.
 */
function tdOpen(teamId, options) {
    if (teamId === null || teamId === undefined) return;

    const opts = options || {};

    tdState.open = true;
    tdState.teamId = teamId;
    tdState.leagueId = opts.leagueId ?? null;
    tdState.season = opts.season ?? null;
    tdState.returnTo = opts.returnTo || null;
    tdState.data = null;

    tdBackLabel.textContent = tdState.returnTo === "live"
        ? t("team.backToMatch")
        : t("team.back");

    openDetailView(tdView);
    tdLoad();
}

function tdClose() {
    if (tdState.returnTo && tdState.returnTo.startsWith("team:")) {
        const prevId = parseInt(tdState.returnTo.split(":")[1], 10);
        tdOpen(prevId);
        return;
    }

    tdState.open = false;
    tdState.teamId = null;
    tdState.data = null;
    tdState.requestToken++;

    closeDetailView();
}

if (tdBackBtn) tdBackBtn.addEventListener("click", tdClose);


/* ---------- 16b. THEME SWITCH ---------- */

function applyTheme(theme) {
    const isLight = theme === 'light' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: light)').matches);
    if (isLight) {
        document.documentElement.setAttribute('data-theme', 'light');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }

    document.querySelectorAll('button[data-theme]').forEach(btn => {
        if (btn.dataset.theme === theme) {
            btn.classList.add('active');
            btn.setAttribute('aria-pressed', 'true');
        } else {
            btn.classList.remove('active');
            btn.setAttribute('aria-pressed', 'false');
        }
    });
}

function initTheme() {
    const stored = localStorage.getItem('theme') || 'system';
    applyTheme(stored);

    document.querySelectorAll('button[data-theme]').forEach(btn => {
        btn.addEventListener('click', () => {
            const theme = btn.dataset.theme;
            localStorage.setItem('theme', theme);
            applyTheme(theme);
        });
    });

    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
        const currentTheme = localStorage.getItem('theme') || 'system';
        if (currentTheme === 'system') {
            applyTheme('system');
        }
    });
}

/* ---------- 17. START ---------- */

async function init() {
    initTheme();

    const i18nReady = await initI18n();
    if (!i18nReady) return;

    // Bereichszustand einmalig setzen, damit versteckte Bereiche von Anfang an
    // inert sind und beide Navigationen dieselbe Markierung zeigen.
    //
    // ?area= wird dabei beruecksichtigt: Die Verknuepfungen im Manifest
    // (/?area=simulation, /?area=compare) landen damit wirklich im
    // gewuenschten Bereich. Frueher trugen sie ?mode=, das nirgends
    // gelesen wurde - beide oeffneten wirkungslos die Startansicht.
    const startBereich = areaFromUrl(state.activeArea);
    setActiveArea(startBereich);

    // replaceState statt pushState: Der Seitenaufbau selbst ist kein
    // Navigationsschritt und darf keinen zusaetzlichen Eintrag erzeugen.
    // Die URL bleibt unangetastet - ?area= erscheint erst, wenn der
    // Nutzer den Bereich tatsaechlich wechselt.
    window.history.replaceState({ footsimArea: startBereich }, "",
                                window.location.href);

    await loadSeasons();
    await loadCompetitions();
}

init();

/* ============================================================
   AUTH UI
   ============================================================ */

const authBtn      = el('auth-btn');
const authDrawer   = el('auth-drawer');
const authBackdrop = el('auth-backdrop');
const authClose    = el('auth-close');

let authDrawerOpen = false;

function openAuthDrawer() {
    // Waehrend des PWA-Erststarts ist der Wizard die einzige
    // Account-Oberflaeche. Die Sperre sitzt bewusst hier und nicht an
    // den einzelnen Aufrufern, damit auch Deeplinks wie ?reset_token=
    // oder ?verified=1 den Overlay nicht durchstossen koennen.
    if (wizardActive) return;
    if (authDrawerOpen || !authDrawer) return;
    authDrawerOpen = true;
    drawerLastFocus = document.activeElement;

    drawerScrollY = window.scrollY;
    document.body.classList.add('drawer-open');
    document.body.style.top = `-${drawerScrollY}px`;

    authDrawer.hidden = false;
    authBackdrop.hidden = false;
    show(authDrawer);
    show(authBackdrop);

    authBtn.setAttribute('aria-expanded', 'true');
    authClose.focus();

    // Der Drawer beginnt immer auf der Uebersicht, nie in einer
    // Unterebene, die beim letzten Mal offen war.
    if (typeof showAccountPanel === 'function') showAccountPanel('account-root');
}

function closeAuthDrawer() {
    if (!authDrawerOpen || !authDrawer) return;
    authDrawerOpen = false;

    hide(authDrawer);
    hide(authBackdrop);

    setTimeout(() => {
        authDrawer.hidden = true;
        authBackdrop.hidden = true;
        document.body.classList.remove('drawer-open');
        document.body.style.top = '';
        window.scrollTo(0, drawerScrollY);
        if (drawerLastFocus) drawerLastFocus.focus();
    }, 300);

    authBtn.setAttribute('aria-expanded', 'false');
}

if (authBtn) {
    authBtn.addEventListener('click', openAuthDrawer);
}
if (authClose) {
    authClose.addEventListener('click', closeAuthDrawer);
}
if (authBackdrop) {
    authBackdrop.addEventListener('click', closeAuthDrawer);
}

// Form logic
const loginForm = el('login-form');
const registerForm = el('register-form');
const logoutBtn = el('logout-btn');

const forgotPasswordView = el('forgot-password-view');
const resetPasswordView = el('reset-password-view');
const loggedOutView = el('auth-logged-out-view');
const loggedInView = el('auth-logged-in-view');

const showForgotBtn = el('show-forgot-btn');
const forgotCancelBtn = el('forgot-cancel-btn');
const forgotForm = el('forgot-password-form');
const forgotMessage = el('forgot-message');

const resetCancelBtn = el('reset-cancel-btn');
const resetForm = el('reset-password-form');
const resetTokenInput = el('reset-token');
const resetMessage = el('reset-message');

const resendBtn = el('resend-verification-btn');
const resendMessage = el('resend-message');
const changePasswordForm = el('change-password-form');
const changePasswordMessage = el('change-password-message');
const verificationBackBtn = el('verification-back-btn');
const verificationView = el('verification-required-view');

if (verificationBackBtn) {
    verificationBackBtn.addEventListener('click', () => {
        hide(verificationView);
        show(loggedOutView);
        if (registerForm) registerForm.reset();
        const successEl = el('register-success');
        if (successEl) hide(successEl);
    });
}

const showDeleteAccountBtn = el('show-delete-account-btn');
const cancelDeleteAccountBtn = el('cancel-delete-account-btn');
const deleteAccountConfirmation = el('delete-account-confirmation');
const deleteAccountForm = el('delete-account-form');
const deleteAccountMessage = el('delete-account-message');

/**
 * Shared request core for every auth call, drawer and PWA wizard alike.
 *
 * A CSRF token embedded in the page can go stale without anything on
 * screen changing: the tab sits open past WTF_CSRF_TIME_LIMIT (1h), or
 * the session cookie never made it back for some other reason. The
 * server tells us this precisely via error_key "auth.csrfError" (see
 * app.py's CSRFError handler) - on that single, specific signal this
 * refreshes the token once and retries the exact same request once.
 * Nothing else is ever retried: wrong credentials, validation errors,
 * duplicate email, and any other 400/401/500 are returned as-is.
 */
async function safeAuthFetch(url, options, isCsrfRetry) {
    const method = (options && options.method || 'GET').toUpperCase();
    const isMutating = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
    if (options && isMutating) {
        options.headers = { ...options.headers, 'X-CSRFToken': getCsrfToken() };
    }
    let response;
    try {
        response = await fetch(url, options);
    } catch (err) {
        throw new Error('Network error');
    }

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        return { ok: response.ok, status: response.status, data: { error: `HTTP ` + response.status + ` (Serverfehler)` } };
    }

    const data = await response.json();

    if (!response.ok && isMutating && !isCsrfRetry && data && data.error_key === 'auth.csrfError') {
        const freshToken = await refreshCsrfToken();
        if (freshToken) {
            return safeAuthFetch(url, options, true);
        }
    }

    return { ok: response.ok, status: response.status, data };
}


/* ---------- Auth-Kern, praesentationsfrei ----------
   Diese Funktionen sprechen ausschliesslich mit dem bestehenden
   Backend. Sie oeffnen keinen Drawer, laden die Seite nicht neu und
   veraendern keinen Wizard-Zustand - das entscheidet der jeweilige
   Aufrufer. Nur so koennen Drawer und PWA-Wizard dieselbe Logik
   benutzen und trotzdem unterschiedlich reagieren.                */

async function authLogin(credentials) {
    return safeAuthFetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            email: credentials.email,
            password: credentials.password,
        }),
    });
}

async function authRegister(profile) {
    return safeAuthFetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            first_name: profile.firstName,
            last_name: profile.lastName,
            email: profile.email,
            password: profile.password,
        }),
    });
}

async function authResendVerification(email) {
    return safeAuthFetch('/api/auth/resend-verification', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
    });
}

async function authForgotPassword(email) {
    return safeAuthFetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
    });
}

async function authLogout() {
    return safeAuthFetch('/api/auth/logout', { method: 'POST' });
}

/** Einzige Wahrheitsquelle fuer Session, Verifikation und Profilstand. */
async function authMe() {
    try {
        const response = await fetch('/api/auth/me');
        if (!response.ok) return { authenticated: false };
        return await response.json();
    } catch (_) {
        return { authenticated: false, offline: true };
    }
}

// Solange der PWA-Wizard laeuft, darf nichts den Account-Drawer oeffnen.
// Hier deklariert, damit checkAuth() die Variable sicher lesen kann;
// gesetzt wird sie ausschliesslich im Onboarding-Abschnitt weiter unten.
let wizardActive = false;


/* ============================================================
   ANZEIGEZUSTAND AUS DER SERVERANTWORT

   Ab hier wird gerendert. Der Auth-Kern oben bleibt bewusst frei von
   DOM-Zugriffen, damit Drawer und PWA-Wizard dieselben Requests, aber
   unterschiedliche Reaktionen benutzen koennen.
   ============================================================ */

/** Uebernimmt die Serverantwort in den globalen Anzeigezustand. */
function applyAuthPayload(data) {
    const authenticated = Boolean(data && data.authenticated);
    // Der Server liefert die ID nur, wenn sie im aktuellen Namensraum
    // deutbar ist - Altbestand kommt hier bereits als null an.
    window.favoriteTeamId = authenticated && data.favorite_team_id
        ? data.favorite_team_id
        : null;
    // Die Herkunft entscheidet, gegen welche Team-IDs verglichen werden
    // darf (siehe isFavoriteTeamId).
    window.favoriteTeamSource = authenticated && data.favorite_team_source
        ? data.favorite_team_source
        : null;
    window.favoriteTeamName = authenticated && data.favorite_team_name
        ? data.favorite_team_name
        : null;
    window.favoriteTeamCrest = authenticated && data.favorite_team_crest
        ? data.favorite_team_crest
        : null;
    // Es gibt eine gespeicherte Auswahl, die nicht mehr gedeutet werden
    // kann. Die UI bittet um Neuauswahl, statt etwas Falsches zu zeigen.
    window.favoriteTeamNeedsReselect = authenticated
        && Boolean(data.favorite_team_needs_reselect);
    window.currentUser = authenticated ? data.user : null;

    renderHeaderFavorite();
}

/**
 * Wappen des Lieblingsteams in der App-Leiste.
 *
 * Quelle ist ausschliesslich der bereits geladene /api/auth/me-Payload -
 * kein eigener Request nur fuer eine Kopfzeile. Ohne aufloesbares Team
 * (Gast, keine Auswahl, Altbestand) bleibt der Knopf versteckt.
 */
function renderHeaderFavorite() {
    const button = el("app-bar-favorite");
    const image = el("app-bar-favorite-crest");
    if (!button || !image) return;

    const teamId = window.favoriteTeamId;
    const crestUrl = window.favoriteTeamCrest;

    if (!teamId || !crestUrl) {
        hide(button);
        image.removeAttribute("src");
        return;
    }

    const teamName = window.favoriteTeamName || "";
    button.setAttribute("aria-label", t("header.favoriteTeamLabel", { team: teamName }));
    button.title = teamName;

    // Ein kaputtes Wappen darf keinen leeren Rahmen hinterlassen.
    image.onerror = () => { hide(button); };
    image.src = crestUrl;
    show(button);
}

/**
 * Uebernimmt eine frisch gespeicherte Auswahl in den Anzeigezustand.
 *
 * Ein Ort fuer alle Aufrufer (Wizard und Drawer), damit Kopfzeile,
 * Live-Sortierung und Drawer nicht auseinanderlaufen koennen. Die
 * Datenbank bleibt die Wahrheit; das hier ist nur die sofortige
 * Anzeige, bis das naechste /api/auth/me sie ohnehin bestaetigt.
 */
function applyFavoriteTeamLocally(team) {
    window.favoriteTeamId = team.id;
    window.favoriteTeamSource = "apisports";
    window.favoriteTeamName = team.name || null;
    window.favoriteTeamCrest = team.crest || null;
    window.favoriteTeamNeedsReselect = false;

    // Die gemerkte Live-Reihenfolge gehoert zum alten Lieblingsteam.
    liveState.favoriteOrder = null;

    renderHeaderFavorite();
    renderAccountMenuFavorite();
}

/** Setzt den Anzeigezustand zurueck, wenn die Auswahl entfernt wurde. */
function clearFavoriteTeamLocally() {
    window.favoriteTeamId = null;
    window.favoriteTeamSource = null;
    window.favoriteTeamName = null;
    window.favoriteTeamCrest = null;
    window.favoriteTeamNeedsReselect = false;

    liveState.favoriteOrder = null;

    renderHeaderFavorite();
    renderAccountMenuFavorite();
}

/** Kurzanzeige des Lieblingsteams in der Account-Uebersicht. */
function renderAccountMenuFavorite() {
    const target = el("account-menu-favorite");
    if (!target) return;
    if (window.favoriteTeamNeedsReselect) {
        target.textContent = t("account.favoriteNeedsReselect");
        return;
    }
    target.textContent = window.favoriteTeamName || "";
}

/** Oeffnet das BESTEHENDE Teamprofil - kein zweiter Navigationsweg. */
function openFavoriteTeamProfile() {
    if (!window.favoriteTeamId) return;
    // league_id/season sind optional (siehe build_team_detail): ohne sie
    // fehlt nur die Tabellenzeile, Identitaet und Kader laden normal.
    tdOpen(window.favoriteTeamId, { returnTo: "favorite" });
}

if (el("app-bar-favorite")) {
    el("app-bar-favorite").addEventListener("click", openFavoriteTeamProfile);
}

async function checkAuth() {
    try {
        const res = await fetch('/api/auth/me');
        if (!res.ok) return;
        const data = await res.json();
        
        // Hide all views by default
        hide(loggedOutView);
        hide(forgotPasswordView);
        hide(resetPasswordView);
        hide(loggedInView);
        hide(resendMessage);
        hide(changePasswordMessage);
        const verificationView = el('verification-required-view');
        if (verificationView) hide(verificationView);
        if (typeof deleteAccountConfirmation !== 'undefined' && deleteAccountConfirmation) hide(deleteAccountConfirmation);
        if (typeof deleteAccountMessage !== 'undefined' && deleteAccountMessage) hide(deleteAccountMessage);
        
        // Global state for personalization
        applyAuthPayload(data);

        // Die Personalisierung lebt auf der normalen Website im Drawer.
        // Kein Fullscreen-Overlay: das gehoert ausschliesslich in den
        // PWA-Erststart und wuerde die Website sonst blockieren.
        renderDrawerFavorite(data);

        if (data.authenticated) {
            show(loggedInView);
            // Uebersicht: nur der Name. E-Mail und alles Weitere liegen
            // eine Ebene tiefer unter "Profil & Personalisierung".
            el('profile-name').textContent = t('account.greeting', {
                name: data.user.first_name,
            });
            if (el('profile-first-name')) el('profile-first-name').textContent = data.user.first_name;
            if (el('profile-last-name')) el('profile-last-name').textContent = data.user.last_name;
            if (el('profile-email')) el('profile-email').textContent = data.user.email;
            if (!data.user.is_verified) {
                show(el('profile-unverified-warning'));
            } else {
                hide(el('profile-unverified-warning'));
            }
            
            const params = new URLSearchParams(window.location.search);
            let stateHandled = false;
            
            if (params.get('verified') === '1') {
                const msg = document.createElement('p');
                msg.textContent = t('auth.verifiedSuccess') || "E-Mail erfolgreich bestätigt. Dein Account ist jetzt verifiziert.";
                msg.style.color = "var(--accent-green)";
                msg.style.fontSize = "0.85rem";
                msg.style.marginTop = "0";
                loggedInView.insertBefore(msg, loggedInView.firstChild);
                stateHandled = true;
                openAuthDrawer();
            } else if (params.get('verified') === 'already') {
                const msg = document.createElement('p');
                msg.textContent = t('auth.verifiedAlready') || "Diese E-Mail-Adresse wurde bereits bestätigt.";
                msg.style.color = "var(--accent-green)";
                msg.style.fontSize = "0.85rem";
                msg.style.marginTop = "0";
                loggedInView.insertBefore(msg, loggedInView.firstChild);
                stateHandled = true;
                openAuthDrawer();
            }
            
            if (stateHandled) {
                window.history.replaceState({}, document.title, window.location.pathname);
            }
            
        } else {
            // Check if there is a reset token or verify error in URL
            const params = new URLSearchParams(window.location.search);
            let stateHandled = false;
            
            if (params.has('reset_token')) {
                show(resetPasswordView);
                resetTokenInput.value = params.get('reset_token');
                openAuthDrawer();
                stateHandled = true;
            } else if (params.get('verify_error') === 'expired') {
                show(loggedOutView);
                const err = document.createElement('p');
                err.textContent = t('auth.verifyErrorExpired') || "Der Bestätigungslink ist abgelaufen. Bitte fordere einen neuen Link an.";
                err.style.color = "var(--accent-red)";
                err.style.fontSize = "0.85rem";
                err.style.marginTop = "0";
                loggedOutView.insertBefore(err, loggedOutView.firstChild);
                openAuthDrawer();
                stateHandled = true;
            } else if (params.get('verify_error') === 'invalid') {
                show(loggedOutView);
                const err = document.createElement('p');
                err.textContent = t('auth.verifyErrorInvalid') || "Der Bestätigungslink ist ungültig.";
                err.style.color = "var(--accent-red)";
                err.style.fontSize = "0.85rem";
                err.style.marginTop = "0";
                loggedOutView.insertBefore(err, loggedOutView.firstChild);
                openAuthDrawer();
                stateHandled = true;
            } else {
                show(loggedOutView);
            }
            
            if (stateHandled) {
                // Clean up URL without reload
                window.history.replaceState({}, document.title, window.location.pathname);
            }
        }
    } catch(err) {
        console.error(err);
    }
}

if (showForgotBtn) {
    showForgotBtn.addEventListener('click', () => {
        hide(loggedOutView);
        show(forgotPasswordView);
        hide(forgotMessage);
        forgotForm.reset();
    });
}

if (forgotCancelBtn) {
    forgotCancelBtn.addEventListener('click', () => {
        hide(forgotPasswordView);
        show(loggedOutView);
    });
}

if (resetCancelBtn) {
    resetCancelBtn.addEventListener('click', () => {
        hide(resetPasswordView);
        show(loggedOutView);
    });
}

if (forgotForm) {
    forgotForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(forgotMessage);
        
        try {
            const res = await safeAuthFetch('/api/auth/forgot-password', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    email: el('forgot-email').value
                })
            });
            forgotMessage.textContent = res.data.message || 'Link gesendet.';
            forgotMessage.style.color = res.ok ? 'var(--accent-green)' : 'var(--accent-red)';
            show(forgotMessage);
            if (res.ok) forgotForm.reset();
        } catch(err) {
            forgotMessage.textContent = 'Netzwerkfehler';
            forgotMessage.style.color = 'var(--accent-red)';
            show(forgotMessage);
        }
    });
}

if (resetForm) {
    resetForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(resetMessage);
        
        try {
            const res = await safeAuthFetch('/api/auth/reset-password', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    token: resetTokenInput.value,
                    new_password: el('reset-new-password').value
                })
            });
            if (!res.ok) {
                resetMessage.textContent = res.data.error || 'Fehler beim Zurücksetzen';
                resetMessage.style.color = 'var(--accent-red)';
                show(resetMessage);
            } else {
                resetMessage.textContent = res.data.message;
                resetMessage.style.color = 'var(--accent-green)';
                show(resetMessage);
                resetForm.reset();
                setTimeout(() => {
                    hide(resetPasswordView);
                    show(loggedOutView);
                }, 2000);
            }
        } catch(err) {
            resetMessage.textContent = 'Netzwerkfehler';
            resetMessage.style.color = 'var(--accent-red)';
            show(resetMessage);
        }
    });
}

if (resendBtn) {
    resendBtn.addEventListener('click', async () => {
        hide(resendMessage);
        resendBtn.disabled = true;
        
        try {
            const res = await safeAuthFetch('/api/auth/resend-verification', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    email: localStorage.getItem('unverified_email') || (el('profile-email') ? el('profile-email').textContent : '')
                })
            });
            if (res.data.status === 'email_failed' || !res.ok) {
                resendMessage.textContent = res.data.error || 'Fehler beim Senden';
                resendMessage.style.color = 'var(--accent-red)';
            } else {
                resendMessage.textContent = res.data.message || 'Bestätigungslink gesendet.';
                resendMessage.style.color = 'var(--accent-green)';
            }
            show(resendMessage);
        } catch(err) {
            resendMessage.textContent = 'Netzwerkfehler';
            resendMessage.style.color = 'var(--accent-red)';
            show(resendMessage);
        } finally {
            resendBtn.disabled = false;
        }
    });
}

if (changePasswordForm) {
    changePasswordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(changePasswordMessage);
        
        try {
            const res = await safeAuthFetch('/api/auth/change-password', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    current_password: el('change-current-password').value,
                    new_password: el('change-new-password').value
                })
            });
            if (!res.ok) {
                changePasswordMessage.textContent = res.data.error || 'Fehler beim Ändern';
                changePasswordMessage.style.color = 'var(--accent-red)';
                show(changePasswordMessage);
            } else {
                changePasswordMessage.textContent = res.data.message;
                changePasswordMessage.style.color = 'var(--accent-green)';
                show(changePasswordMessage);
                changePasswordForm.reset();
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            }
        } catch(err) {
            changePasswordMessage.textContent = 'Netzwerkfehler';
            changePasswordMessage.style.color = 'var(--accent-red)';
            show(changePasswordMessage);
        }
    });
}

if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const errorEl = el('login-error');
        hide(errorEl);
        
        try {
            // Gemeinsamer Auth-Kern, drawer-eigene Reaktion: der Reload
            // gehoert hierher und bewusst nicht in authLogin().
            const res = await authLogin({
                email: el('login-email').value,
                password: el('login-password').value
            });
            if (!res.ok) {
                errorEl.textContent = res.data.error || 'Login failed';
                show(errorEl);
            } else {
                loginForm.reset();
                window.location.reload();
            }
        } catch(err) {
            errorEl.textContent = 'Network error';
            show(errorEl);
        }
    });
}

if (registerForm) {
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const errorEl = el('register-error');
        const successEl = el('register-success');
        hide(errorEl);
        hide(successEl);
        
        try {
            // Gemeinsamer Auth-Kern; die Drawer-Reaktion (Verification-View)
            // bleibt hier und ist unabhaengig vom PWA-Wizard.
            const res = await authRegister({
                firstName: el('register-first').value,
                lastName: el('register-last').value,
                email: el('register-email').value,
                password: el('register-password').value
            });
            if (!res.ok) {
                errorEl.textContent = res.data.error || 'Registration failed';
                show(errorEl);
            } else {
                const registeredEmail = el('register-email').value;
                registerForm.reset();
                
                // Block A: Auth UX Finish
                // Hide registration forms and show verification required view
                hide(loggedOutView);
                
                const verificationView = el('verification-required-view');
                const verificationEmailDisplay = el('verification-email-display');
                
                if (verificationView && verificationEmailDisplay) {
                    verificationEmailDisplay.textContent = registeredEmail;
                    // Store email temporarily for resend button if needed
                    localStorage.setItem('unverified_email', registeredEmail);
                    
                    if (res.data.status === 'email_failed') {
                        const resendMessageAuth = el('resend-verification-message-auth');
                        if (resendMessageAuth) {
                            resendMessageAuth.textContent = t('auth.registerSuccessEmailFailed') || "Dein Account wurde erstellt, aber die Bestätigungs-E-Mail konnte gerade nicht gesendet werden. Bitte versuche es über 'Bestätigungs-E-Mail erneut senden' erneut.";
                            resendMessageAuth.style.color = "var(--accent-red)";
                            show(resendMessageAuth);
                        }
                    }
                    
                    show(verificationView);
                }
            }
        } catch(err) {
            errorEl.textContent = 'Network error';
            show(errorEl);
        }
    });
}

// Handler for the resend button in the auth UI (after registration)
const resendBtnAuth = el('resend-verification-btn-auth');
const resendMessageAuth = el('resend-verification-message-auth');

if (resendBtnAuth) {
    resendBtnAuth.addEventListener('click', async () => {
        hide(resendMessageAuth);
        resendBtnAuth.disabled = true;
        
        try {
            const res = await safeAuthFetch('/api/auth/resend-verification', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    email: localStorage.getItem('unverified_email') || ''
                })
            });
            if (res.data.status === 'email_failed' || !res.ok) {
                resendMessageAuth.textContent = res.data.error || 'Fehler beim Senden';
                resendMessageAuth.style.color = 'var(--accent-red)';
            } else {
                resendMessageAuth.textContent = res.data.message || 'Bestätigungslink gesendet.';
                resendMessageAuth.style.color = 'var(--accent-green)';
            }
            show(resendMessageAuth);
        } catch (err) {
            resendMessageAuth.textContent = 'Network error';
            resendMessageAuth.style.color = 'var(--accent-red)';
            show(resendMessageAuth);
        } finally {
            resendBtnAuth.disabled = false;
        }
    });
}

if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
        try {
            await safeAuthFetch('/api/auth/logout', {
                method: 'POST'
            });
        } catch(err) {
            console.error(err);
        }
        // Die lokalen Kontodaten verschwinden in JEDEM Fall: der Nutzer
        // hat sich bewusst abgemeldet, und ob der Server erreichbar war,
        // aendert daran nichts. Sprache und Theme bleiben erhalten.
        clearAccountLocalData();
        window.location.reload();
    });
}

if (showDeleteAccountBtn) {
    showDeleteAccountBtn.addEventListener('click', () => {
        show(deleteAccountConfirmation);
    });
}

if (cancelDeleteAccountBtn) {
    cancelDeleteAccountBtn.addEventListener('click', () => {
        hide(deleteAccountConfirmation);
        if (deleteAccountForm) deleteAccountForm.reset();
        if (deleteAccountMessage) hide(deleteAccountMessage);
    });
}

if (deleteAccountForm) {
    deleteAccountForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(deleteAccountMessage);
        
        try {
            const res = await safeAuthFetch('/api/auth/delete-account', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_password: el('delete-current-password').value
                })
            });
            if (!res.ok) {
                deleteAccountMessage.textContent = res.data.error || 'Fehler beim Löschen';
                deleteAccountMessage.style.color = 'var(--accent-red)';
                show(deleteAccountMessage);
            } else {
                deleteAccountForm.reset();
                // Das Konto existiert serverseitig nicht mehr - alles, was
                // lokal davon uebrig ist, muss ebenfalls weg. Ohne das
                // bliebe die E-Mail-Adresse eines geloeschten Kontos auf
                // dem Geraet zurueck.
                clearAccountLocalData();
                window.location.reload();
            }
        } catch(err) {
            deleteAccountMessage.textContent = 'Netzwerkfehler';
            deleteAccountMessage.style.color = 'var(--accent-red)';
            show(deleteAccountMessage);
        }
    });
}

/* ============================================================
   18. PWA ONBOARDING

   Zwei Praesentationen, ein Auth-Kern:
     normale Website -> bestehender Account-Drawer (unveraendert)
     PWA-Erststart   -> dieser Fullscreen-Wizard

   Der Wizard oeffnet nie den Drawer und gibt die App erst frei,
   wenn der Flow wirklich abgeschlossen ist: als Gast, oder als
   Account mit erledigter bzw. bewusst uebersprungener
   Personalisierung. Session, Verifikation und Profilstand kommen
   dabei immer vom Server (/api/auth/me), nie aus dem LocalStorage.
   ============================================================ */

const ONBOARDING_KEY = "footsim_onboarding";
const ONBOARDING_VERSION = 2;

// Fachliche Reihenfolge der Zustaende, nicht bloss eine Aufzaehlung.
const WIZARD_STATES = [
    "language", "access", "login", "register", "verify", "personalize", "complete",
];

// Zustaende, die ohne Session fachlich unmoeglich sind. Wer sie im
// LocalStorage stehen hat, aber nicht angemeldet ist, landet wieder
// bei "access" statt in einem Zustand ohne Grundlage.
const WIZARD_SESSION_STATES = new Set(["verify", "personalize"]);

/** Erststart-Onboarding gilt nur fuer die App, nie fuer die Website. */
function isPwaContext() {
    try {
        if (new URLSearchParams(window.location.search).get("source") === "pwa") return true;
        if (window.matchMedia("(display-mode: standalone)").matches) return true;
        return window.navigator.standalone === true;
    } catch (_) {
        return false;
    }
}


/* ---------- Wizard-Zustand ----------
   Ein einziger versionierter Schluessel statt mehrerer unabhaengiger
   Booleans. Er haelt ausschliesslich UI-Fortschritt - keine
   Auth-Fakten. Bei unbekannter Version wird zurueckgesetzt, statt in
   einen Zustand zu starten, den es nicht mehr gibt.               */

function readWizardState() {
    let raw = null;
    try {
        raw = window.localStorage.getItem(ONBOARDING_KEY);
    } catch (_) {
        return null;
    }
    if (!raw) return null;

    let parsed = null;
    try {
        parsed = JSON.parse(raw);
    } catch (_) {
        clearWizardState();
        return null;
    }

    if (!parsed || typeof parsed !== "object"
        || parsed.v !== ONBOARDING_VERSION
        || !WIZARD_STATES.includes(parsed.state)) {
        clearWizardState();
        return null;
    }
    return parsed;
}

function writeWizardState(state, extra) {
    try {
        window.localStorage.setItem(ONBOARDING_KEY, JSON.stringify(
            Object.assign({ v: ONBOARDING_VERSION, state }, extra || {})
        ));
    } catch (_) {
        // Ohne LocalStorage bleibt der Wizard in dieser Sitzung voll
        // benutzbar, nur der Resume nach einem Reload entfaellt.
    }
}

function clearWizardState() {
    try {
        window.localStorage.removeItem(ONBOARDING_KEY);
    } catch (_) {
        // Nichts zu tun - der Zustand war ohnehin nicht lesbar.
    }
}

/**
 * Entfernt alle KONTOBEZOGENEN Werte aus dem LocalStorage.
 *
 * Wird beim Abmelden und nach erfolgreicher Kontoloeschung aufgerufen.
 * Vorher blieb insbesondere "unverified_email" - also eine echte
 * E-Mail-Adresse - nach dem Abmelden auf dem Geraet liegen und war fuer
 * den naechsten Benutzer desselben Browsers lesbar.
 *
 * Bewusst NICHT geloescht werden Einstellungen, die zum Geraet gehoeren
 * und nichts mit einem Konto zu tun haben: Sprache (footsim_lang) und
 * Theme. Wer sich abmeldet, will die App nicht ploetzlich in einer
 * anderen Sprache und Darstellung wiederfinden.
 */
function clearAccountLocalData() {
    // Die alten Einzelschluessel stehen bewusst NICHT in dieser Liste.
    // Sie gehoeren ausschliesslich migrateLegacyOnboardingState() - nur
    // eine Stelle im Code kennt das alte Format, sonst faengt es an,
    // sich zu verteilen. Inhaltlich ist das unbedenklich: sie tragen
    // reinen Oberflaechenzustand, keine personenbezogenen Angaben.
    const accountKeys = [
        "unverified_email",     // personenbezogen: E-Mail-Adresse
        ONBOARDING_KEY,         // Wizard-Zustand des jeweiligen Kontos
    ];

    accountKeys.forEach((key) => {
        try {
            window.localStorage.removeItem(key);
        } catch (_) {
            // Privater Modus oder gesperrter Speicher - dann gab es an
            // dieser Stelle ohnehin nichts zu loeschen.
        }
    });
}

/**
 * Bestandsbrowser tragen noch die alten Einzelschluessel. Sie werden
 * einmalig uebersetzt und danach entfernt, damit niemand zwischen zwei
 * Mechanismen haengen bleibt.
 */
function migrateLegacyOnboardingState() {
    let completed = null;
    let legacyStep = null;
    try {
        completed = window.localStorage.getItem("onboarding_completed");
        legacyStep = window.localStorage.getItem("pwa_onboarding_step");
    } catch (_) {
        return;
    }
    if (completed === null && legacyStep === null) return;

    if (!readWizardState()) {
        // "true" hiess frueher tatsaechlich fertig; alles andere war ein
        // angefangener Flow und beginnt bei der Zugangswahl neu.
        writeWizardState(completed === "true" ? "complete" : "access");
    }
    try {
        window.localStorage.removeItem("onboarding_completed");
        window.localStorage.removeItem("pwa_onboarding_step");
        window.localStorage.removeItem("guest_favorite_team");
    } catch (_) {
        // Der neue Schluessel ist gesetzt; Altlasten sind ab hier egal.
    }
}


/* ---------- App-Sperre ----------
   Waehrend des Onboardings darf die normale App nicht nur unsichtbar,
   sondern gar nicht erreichbar sein. Eine Klasse auf <body> statt
   Inline-Styles, damit .hidden und display: none nicht wieder
   gegeneinander arbeiten.                                          */

function lockAppForOnboarding() {
    document.body.classList.add("onboarding-lock");
}

function unlockApp() {
    document.body.classList.remove("onboarding-lock");
}


/* ---------- Datengetriebene Teamauswahl ----------
   Land -> Wettbewerb -> Verein, ausschliesslich aus den bereits
   vorhandenen Endpunkten /api/competitions und /api/standings.
   Keine gepflegte Clubliste und keine zweite Datenquelle: die
   Team-IDs stammen damit exakt aus dem Namespace, den diese
   Endpunkte ohnehin liefern (football-data.org).                  */

const teamPickerCache = { competitions: null, teams: new Map() };

async function pickerLoadCompetitions() {
    if (teamPickerCache.competitions) return teamPickerCache.competitions;

    const response = await fetch("/api/competitions");
    if (!response.ok) throw new Error(`competitions ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error("competitions payload");

    // Nur Wettbewerbe mit einer echten Tabelle - daraus kommen die Teams.
    teamPickerCache.competitions = data.filter((entry) => (
        entry && entry.available && (entry.type === "league" || entry.type === "cl")
    ));
    return teamPickerCache.competitions;
}

/**
 * Vereine eines Wettbewerbs.
 *
 * Bewusst /api/personalization/teams statt /api/standings: dessen
 * Team-IDs stammen von football-data.org, waehrend Teamprofil und Live
 * ausschliesslich API-Football-IDs verwenden. Nur aus diesem Namensraum
 * ausgewaehlt bleibt ein Lieblingsteam spaeter anklickbar UND in Live
 * erkennbar. Ein Mapping zwischen beiden Raeumen gibt es bewusst nicht.
 */
async function pickerLoadTeams(code) {
    if (teamPickerCache.teams.has(code)) return teamPickerCache.teams.get(code);

    const response = await fetch(`/api/personalization/teams?competition=${encodeURIComponent(code)}`);
    if (!response.ok) throw new Error(`teams ${response.status}`);
    const data = await response.json();

    const rows = (data && Array.isArray(data.teams)) ? data.teams : [];
    const teams = rows
        .filter((row) => row && row.team_id)
        .map((row) => ({
            id: row.team_id,
            name: row.team_name || String(row.team_id),
            fullName: row.team_name || "",
            crest: row.crest || null,
        }))
        .sort((a, b) => a.name.localeCompare(b.name, activeIntlLocale()));

    teamPickerCache.teams.set(code, teams);
    return teams;
}

/** Wettbewerbe nach ihrem bereits lokalisierten Land gruppieren. */
function pickerGroupByCountry(competitions) {
    const grouped = new Map();
    competitions.forEach((entry) => {
        const country = entry.country || "";
        if (!grouped.has(country)) grouped.set(country, []);
        grouped.get(country).push(entry);
    });
    return Array.from(grouped.entries())
        .map(([country, entries]) => ({ country, competitions: entries }))
        .sort((a, b) => a.country.localeCompare(b.country, activeIntlLocale()));
}

/**
 * Baut die dreistufige Auswahl in einen beliebigen Container.
 *
 * handlers.onSelect(team, competition)  gewaehlter Verein
 * handlers.onExit()                     Zurueck auf oberster Stufe
 *
 * Gibt einen Controller zurueck; destroy() loest den Container wieder
 * auf, damit ein zweiter Aufruf keine doppelten Listener hinterlaesst.
 */
function createTeamPicker(host, handlers) {
    const options = handlers || {};
    const picker = { level: "country", country: null, competition: null, query: "" };

    const root = make("div", "fs-pick");
    const crumb = make("div", "fs-pick-crumb");
    const heading = make("p", "fs-pick-heading");
    const searchWrap = make("div", "fs-pick-search hidden");
    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.className = "fs-pick-search-input";
    searchInput.autocomplete = "off";
    searchInput.setAttribute("data-i18n-placeholder", "onboarding.teamSearchPlaceholder");
    searchInput.placeholder = t("onboarding.teamSearchPlaceholder");
    searchWrap.appendChild(searchInput);

    const list = make("div", "fs-pick-list");
    const status = make("p", "fs-pick-status hidden");
    status.setAttribute("role", "status");

    root.appendChild(crumb);
    root.appendChild(heading);
    root.appendChild(searchWrap);
    root.appendChild(status);
    root.appendChild(list);

    host.textContent = "";
    host.appendChild(root);

    function setStatusText(key, isError) {
        status.textContent = t(key);
        status.classList.toggle("is-error", Boolean(isError));
        show(status);
    }

    function clearStatus() {
        status.textContent = "";
        status.classList.remove("is-error");
        hide(status);
    }

    function renderCrumb() {
        crumb.textContent = "";
        const trail = [];
        if (picker.country) trail.push(picker.country);
        if (picker.competition) trail.push(picker.competition.name);
        if (!trail.length) return;

        trail.forEach((label, index) => {
            if (index > 0) crumb.appendChild(make("span", "fs-pick-crumb-sep", "›"));
            crumb.appendChild(make("span", "fs-pick-crumb-item", label));
        });
    }

    function buildTile(label, sublabel, imageUrl, onActivate) {
        const tile = make("button", "fs-pick-tile");
        tile.type = "button";

        const media = make("span", "fs-pick-tile-media");
        if (imageUrl) media.appendChild(crest(imageUrl, "fs-pick-tile-crest"));
        tile.appendChild(media);

        const text = make("span", "fs-pick-tile-text");
        text.appendChild(make("span", "fs-pick-tile-label", label));
        if (sublabel) text.appendChild(make("span", "fs-pick-tile-sub", sublabel));
        tile.appendChild(text);

        tile.addEventListener("click", onActivate);
        return tile;
    }

    async function renderCountries() {
        picker.level = "country";
        picker.country = null;
        picker.competition = null;
        hide(searchWrap);
        renderCrumb();
        heading.textContent = t("onboarding.chooseCountry");
        list.textContent = "";
        setStatusText("onboarding.pickerLoading", false);

        let competitions;
        try {
            competitions = await pickerLoadCompetitions();
        } catch (error) {
            renderLoadError(renderCountries);
            return;
        }

        clearStatus();
        const groups = pickerGroupByCountry(competitions);
        if (!groups.length) {
            setStatusText("onboarding.pickerEmpty", false);
            return;
        }
        groups.forEach((group) => {
            const first = group.competitions[0];
            list.appendChild(buildTile(
                group.country,
                group.competitions.map((entry) => entry.name).join(" · "),
                first ? first.emblem : null,
                () => renderCompetitions(group)
            ));
        });
    }

    function renderCompetitions(group) {
        picker.level = "competition";
        picker.country = group.country;
        picker.competition = null;
        hide(searchWrap);
        renderCrumb();
        heading.textContent = t("onboarding.chooseCompetition");
        clearStatus();
        list.textContent = "";

        group.competitions.forEach((entry) => {
            list.appendChild(buildTile(
                entry.name,
                entry.country,
                entry.emblem,
                () => renderTeams(entry)
            ));
        });
    }

    async function renderTeams(competition) {
        picker.level = "team";
        picker.competition = competition;
        picker.query = "";
        searchInput.value = "";
        renderCrumb();
        heading.textContent = t("onboarding.chooseTeam");
        list.textContent = "";
        hide(searchWrap);
        setStatusText("onboarding.pickerLoading", false);

        let teams;
        try {
            teams = await pickerLoadTeams(competition.code);
        } catch (error) {
            renderLoadError(() => renderTeams(competition));
            return;
        }

        clearStatus();
        if (!teams.length) {
            // Eine Tabelle kann fachlich leer sein, etwa vor der Auslosung.
            setStatusText("onboarding.pickerEmpty", false);
            return;
        }
        if (teams.length > 8) show(searchWrap);
        paintTeams(teams);
    }

    function paintTeams(teams) {
        list.textContent = "";
        const needle = picker.query.trim().toLowerCase();
        const visible = needle
            ? teams.filter((team) => (
                team.name.toLowerCase().includes(needle)
                || team.fullName.toLowerCase().includes(needle)
            ))
            : teams;

        if (!visible.length) {
            setStatusText("onboarding.pickerNoMatch", false);
            return;
        }
        clearStatus();
        visible.forEach((team) => {
            list.appendChild(buildTile(
                team.name,
                team.fullName !== team.name ? team.fullName : "",
                team.crest,
                () => {
                    if (typeof options.onSelect === "function") {
                        options.onSelect(team, picker.competition);
                    }
                }
            ));
        });
    }

    function renderLoadError(retry) {
        list.textContent = "";
        setStatusText("onboarding.pickerError", true);
        const retryBtn = make("button", "fs-btn fs-btn-ghost", t("onboarding.retry"));
        retryBtn.type = "button";
        retryBtn.addEventListener("click", retry);
        list.appendChild(retryBtn);
    }

    searchInput.addEventListener("input", () => {
        picker.query = searchInput.value;
        const teams = teamPickerCache.teams.get(picker.competition && picker.competition.code);
        if (teams) paintTeams(teams);
    });

    return {
        start() {
            renderCountries();
        },
        /** true, wenn "zurueck" den Picker verlaesst statt eine Stufe hoch. */
        back() {
            if (picker.level === "team") {
                const competitions = teamPickerCache.competitions || [];
                const group = pickerGroupByCountry(competitions)
                    .find((entry) => entry.country === picker.country);
                if (group) {
                    renderCompetitions(group);
                    return false;
                }
            }
            if (picker.level === "competition") {
                renderCountries();
                return false;
            }
            if (typeof options.onExit === "function") options.onExit();
            return true;
        },
        atRoot() {
            return picker.level === "country";
        },
        destroy() {
            host.textContent = "";
        },
    };
}


/* ---------- Wizard-Steuerung ---------- */

const wizard = {
    overlay: null,
    steps: new Map(),
    current: null,
    picker: null,
    email: "",
};

function wizardStepNode(state) {
    return wizard.steps.get(state) || null;
}

/** Zeigt genau einen Schritt und haelt den gespeicherten Stand aktuell. */
function wizardGoto(state, extra) {
    if (!WIZARD_STATES.includes(state)) return;

    if (state === "complete") {
        wizardComplete();
        return;
    }

    wizard.current = state;
    writeWizardState(state, extra);

    wizard.steps.forEach((node, key) => {
        if (key === state) {
            show(node);
        } else {
            hide(node);
        }
    });

    if (state === "personalize") wizardStartPicker();
    if (state === "verify") wizardRenderVerify();

    // Fokus in den neuen Schritt holen, sonst bleibt er beim alten Button.
    const node = wizardStepNode(state);
    if (node) {
        const target = node.querySelector("input, button");
        if (target) target.focus({ preventScroll: true });
    }
}

/** Onboarding beenden und die normale App freigeben. */
function wizardComplete() {
    wizard.current = "complete";
    writeWizardState("complete");
    if (wizard.picker) {
        wizard.picker.destroy();
        wizard.picker = null;
    }
    wizardActive = false;
    hide(wizard.overlay);
    unlockApp();
}

function wizardSetBusy(button, busy, labelKey) {
    if (!button) return;
    button.disabled = busy;
    button.classList.toggle("is-busy", busy);
    if (busy) {
        button.dataset.idleLabel = button.textContent;
        button.textContent = t("onboarding.busy");
    } else if (button.dataset.idleLabel) {
        button.textContent = labelKey ? t(labelKey) : button.dataset.idleLabel;
        delete button.dataset.idleLabel;
    }
}

function wizardShowMessage(node, text, isError) {
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("is-error", Boolean(isError));
    show(node);
}

function wizardClearMessage(node) {
    if (!node) return;
    node.textContent = "";
    node.classList.remove("is-error");
    hide(node);
}

/**
 * Naechster Zustand nach erfolgreicher Authentifizierung. Die
 * Entscheidung faellt ausschliesslich anhand der Serverantwort.
 */
function wizardStateForAccount(me) {
    if (!me || !me.authenticated || !me.user) return "access";
    if (!me.user.is_verified) return "verify";
    if (me.user.profile_onboarding_completed === false) return "personalize";
    return "complete";
}

async function wizardAdvanceFromServer() {
    const me = await authMe();
    applyAuthPayload(me);
    if (me && me.authenticated && me.user && me.user.email) {
        wizard.email = me.user.email;
    }
    wizardGoto(wizardStateForAccount(me));
}


/* ---------- Schritt: Personalisierung ---------- */

function wizardStartPicker() {
    const host = el("onboarding-picker-host");
    if (!host) return;
    if (wizard.picker) wizard.picker.destroy();

    wizardClearMessage(el("onboarding-personalize-message"));
    wizard.picker = createTeamPicker(host, {
        onSelect: (team) => wizardSaveFavorite(team),
    });
    wizard.picker.start();
}

async function wizardSaveFavorite(team) {
    const message = el("onboarding-personalize-message");
    wizardShowMessage(message, t("onboarding.saving"), false);

    let result;
    try {
        result = await safeAuthFetch("/api/auth/favorite", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            // Name und Wappen kommen aus derselben Kachel, die der
            // Nutzer angetippt hat - kein spaeterer Nachschlag noetig.
            body: JSON.stringify({
                team_id: team.id,
                team_name: team.name,
                crest_url: team.crest,
                source: "apisports",
            }),
        });
    } catch (error) {
        wizardShowMessage(message, t("onboarding.networkError"), true);
        return;
    }

    if (!result.ok) {
        wizardShowMessage(message, visibleApiError(result.data, "onboarding.saveFailed"), true);
        return;
    }
    applyFavoriteTeamLocally(team);
    wizardComplete();
}

async function wizardSkipPersonalization() {
    const message = el("onboarding-personalize-message");
    const button = el("onboarding-personalize-skip");
    wizardClearMessage(message);
    wizardSetBusy(button, true);

    let result;
    try {
        result = await safeAuthFetch("/api/auth/favorite/skip", { method: "POST" });
    } catch (error) {
        wizardSetBusy(button, false, "onboarding.skip");
        wizardShowMessage(message, t("onboarding.networkError"), true);
        return;
    }
    wizardSetBusy(button, false, "onboarding.skip");

    if (!result.ok) {
        wizardShowMessage(message, visibleApiError(result.data, "onboarding.saveFailed"), true);
        return;
    }
    wizardComplete();
}


/* ---------- Schritt: Verifikation ---------- */

function wizardRenderVerify() {
    const target = el("onboarding-verify-email");
    if (target) target.textContent = wizard.email || "";
}

async function wizardResendVerification() {
    const button = el("onboarding-verify-resend");
    const message = el("onboarding-verify-message");
    if (!wizard.email) {
        wizardShowMessage(message, t("onboarding.verifyNoEmail"), true);
        return;
    }
    wizardClearMessage(message);
    wizardSetBusy(button, true);

    let result;
    try {
        result = await authResendVerification(wizard.email);
    } catch (error) {
        wizardSetBusy(button, false, "onboarding.verifyResend");
        wizardShowMessage(message, t("onboarding.networkError"), true);
        return;
    }
    wizardSetBusy(button, false, "onboarding.verifyResend");

    if (!result.ok) {
        wizardShowMessage(message, visibleApiError(result.data, "onboarding.verifyResendFailed"), true);
        return;
    }
    wizardShowMessage(message, t("onboarding.verifyResent"), false);
}

async function wizardRecheckVerification() {
    const button = el("onboarding-verify-recheck");
    const message = el("onboarding-verify-message");
    wizardClearMessage(message);
    wizardSetBusy(button, true);

    const me = await authMe();
    wizardSetBusy(button, false, "onboarding.verifyRecheck");
    applyAuthPayload(me);

    if (!me || !me.authenticated) {
        wizardGoto("access");
        return;
    }
    if (!me.user.is_verified) {
        wizardShowMessage(message, t("onboarding.verifyStillPending"), true);
        return;
    }
    wizardGoto(wizardStateForAccount(me));
}

async function wizardAbortToAccess() {
    try {
        await authLogout();
    } catch (error) {
        // Auch ohne erfolgreichen Logout darf niemand hier festsitzen.
    }
    // Auch dieser Weg ist ein Abmelden - dieselbe Bereinigung wie beim
    // Logout-Knopf. Muss VOR wizardGoto() stehen, denn das schreibt den
    // Wizard-Zustand unmittelbar danach neu.
    clearAccountLocalData();
    applyAuthPayload({ authenticated: false });
    wizard.email = "";
    wizardGoto("access");
}


/* ---------- Verdrahtung ---------- */

function wizardBindLanguage() {
    [["onboarding-lang-de", "de"], ["onboarding-lang-en", "en"]].forEach(([id, locale]) => {
        const button = el(id);
        if (!button) return;
        button.addEventListener("click", () => {
            // Der Uebergang darf NICHT davon abhaengen, dass selectLocale()
            // tatsaechlich navigiert: bei bereits aktiver Sprache tut es das
            // bewusst nicht. Erst den Zustand festschreiben, dann die
            // Sprache anwenden - so fuehrt jede Auswahl nach Tor 2, egal ob
            // ein Reload folgt oder nicht.
            writeWizardState("access");
            if (normalizeLocale(locale) === activeLocale) {
                selectLocale(locale);      // no-op, Persistenz bleibt korrekt
                wizardGoto("access");
                return;
            }
            selectLocale(locale);          // navigiert; Resume greift danach
        });
    });
}

function wizardBindAccess() {
    const login = el("onboarding-login-btn");
    if (login) login.addEventListener("click", () => wizardGoto("login"));

    const register = el("onboarding-register-btn");
    if (register) register.addEventListener("click", () => wizardGoto("register"));

    const guest = el("onboarding-guest-btn");
    if (guest) {
        // Gast ist der einzige Zweig, der direkt fertig ist.
        guest.addEventListener("click", () => wizardComplete());
    }
}

function wizardBindLogin() {
    const form = el("onboarding-login-form");
    const error = el("onboarding-login-error");
    const submit = el("onboarding-login-submit");

    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            wizardClearMessage(error);
            wizardSetBusy(submit, true);

            let result;
            try {
                result = await authLogin({
                    email: el("onboarding-login-email").value,
                    password: el("onboarding-login-password").value,
                });
            } catch (requestError) {
                wizardSetBusy(submit, false, "onboarding.loginSubmit");
                wizardShowMessage(error, t("onboarding.networkError"), true);
                return;
            }
            wizardSetBusy(submit, false, "onboarding.loginSubmit");

            if (!result.ok) {
                wizardShowMessage(error, visibleApiError(result.data, "onboarding.loginFailed"), true);
                return;
            }
            form.reset();
            await wizardAdvanceFromServer();
        });
    }

    const back = el("onboarding-login-back");
    if (back) back.addEventListener("click", () => wizardGoto("access"));

    const forgotOpen = el("onboarding-login-forgot");
    const forgotPanel = el("onboarding-forgot-panel");
    if (forgotOpen && forgotPanel) {
        forgotOpen.addEventListener("click", () => {
            show(forgotPanel);
            const field = el("onboarding-forgot-email");
            if (field) {
                field.value = el("onboarding-login-email").value;
                field.focus({ preventScroll: true });
            }
        });
    }

    const forgotCancel = el("onboarding-forgot-cancel");
    if (forgotCancel && forgotPanel) {
        forgotCancel.addEventListener("click", () => {
            hide(forgotPanel);
            wizardClearMessage(el("onboarding-forgot-message"));
        });
    }

    const forgotForm = el("onboarding-forgot-form");
    if (forgotForm) {
        forgotForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const message = el("onboarding-forgot-message");
            const button = el("onboarding-forgot-submit");
            wizardClearMessage(message);
            wizardSetBusy(button, true);

            let result;
            try {
                result = await authForgotPassword(el("onboarding-forgot-email").value);
            } catch (requestError) {
                wizardSetBusy(button, false, "onboarding.forgotSubmit");
                wizardShowMessage(message, t("onboarding.networkError"), true);
                return;
            }
            wizardSetBusy(button, false, "onboarding.forgotSubmit");

            if (!result.ok) {
                wizardShowMessage(message, visibleApiError(result.data, "onboarding.forgotFailed"), true);
                return;
            }
            wizardShowMessage(message, t("onboarding.forgotSent"), false);
        });
    }
}

function wizardBindRegister() {
    const form = el("onboarding-register-form");
    const error = el("onboarding-register-error");
    const submit = el("onboarding-register-submit");

    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            wizardClearMessage(error);
            wizardSetBusy(submit, true);

            const email = el("onboarding-register-email").value;
            let result;
            try {
                result = await authRegister({
                    firstName: el("onboarding-register-first").value,
                    lastName: el("onboarding-register-last").value,
                    email,
                    password: el("onboarding-register-password").value,
                });
            } catch (requestError) {
                wizardSetBusy(submit, false, "onboarding.registerSubmit");
                wizardShowMessage(error, t("onboarding.networkError"), true);
                return;
            }
            wizardSetBusy(submit, false, "onboarding.registerSubmit");

            if (!result.ok) {
                wizardShowMessage(error, visibleApiError(result.data, "onboarding.registerFailed"), true);
                return;
            }

            // Registrierung erzeugt bewusst keine Session: der Weg fuehrt
            // immer ueber die Bestaetigungsmail.
            wizard.email = email;
            form.reset();
            wizardGoto("verify", { email });
            if (result.data && result.data.status === "email_failed") {
                wizardShowMessage(el("onboarding-verify-message"),
                    t("onboarding.verifyMailFailed"), true);
            }
        });
    }

    const back = el("onboarding-register-back");
    if (back) back.addEventListener("click", () => wizardGoto("access"));
}

function wizardBindVerify() {
    const resend = el("onboarding-verify-resend");
    if (resend) resend.addEventListener("click", () => wizardResendVerification());

    const recheck = el("onboarding-verify-recheck");
    if (recheck) recheck.addEventListener("click", () => wizardRecheckVerification());

    const abort = el("onboarding-verify-logout");
    if (abort) abort.addEventListener("click", () => wizardAbortToAccess());
}

function wizardBindPersonalize() {
    const skip = el("onboarding-personalize-skip");
    if (skip) skip.addEventListener("click", () => wizardSkipPersonalization());

    const back = el("onboarding-personalize-back");
    if (back) {
        back.addEventListener("click", () => {
            if (wizard.picker) wizard.picker.back();
        });
    }
}


/* ---------- Einstieg ---------- */

/**
 * Entscheidet den Startzustand. Server schlaegt LocalStorage: ein lokal
 * als "complete" markierter Browser darf einen Account nicht an einer
 * serverseitig offenen Personalisierung vorbeischleusen.
 */
function resolveInitialWizardState(stored, me) {
    if (me && me.authenticated) return wizardStateForAccount(me);
    if (!stored) return "language";
    if (WIZARD_SESSION_STATES.has(stored.state)) return "access";
    return stored.state;
}

async function initOnboarding() {
    const overlay = el("onboarding-overlay");
    if (!overlay || !isPwaContext()) return;

    migrateLegacyOnboardingState();
    const stored = readWizardState();

    // Fruehe Sperre gegen ein kurzes Aufblitzen der App. Wer lokal schon
    // fertig ist, sieht gar keine Sperre - das ist der haeufige Fall.
    if (!stored || stored.state !== "complete") lockAppForOnboarding();

    wizard.overlay = overlay;
    WIZARD_STATES.forEach((state) => {
        if (state === "complete") return;
        const node = el(`onboarding-step-${state}`);
        if (node) wizard.steps.set(state, node);
    });

    // Genau einmal binden, unabhaengig vom spaeteren Zustand. Damit kann
    // kein Schritt sichtbar werden, dessen Bedienelemente tot sind.
    wizardBindLanguage();
    wizardBindAccess();
    wizardBindLogin();
    wizardBindRegister();
    wizardBindVerify();
    wizardBindPersonalize();

    const me = await authMe();
    applyAuthPayload(me);
    if (me && me.authenticated && me.user && me.user.email) wizard.email = me.user.email;
    else if (stored && stored.email) wizard.email = stored.email;

    const target = resolveInitialWizardState(stored, me);
    if (target === "complete") {
        wizardComplete();
        return;
    }

    wizardActive = true;
    lockAppForOnboarding();
    show(overlay);
    wizardGoto(target, target === "verify" ? { email: wizard.email } : undefined);
}


/* ============================================================
   PERSONALISIERUNG IM ACCOUNT-DRAWER (normale Website)

   Dieselbe datengetriebene Auswahl, andere Praesentation. Die
   Listener haengen am Modul-Scope und damit unabhaengig davon, ob
   der PWA-Wizard jemals gelaufen ist.
   ============================================================ */

const drawerFavorite = { picker: null };


/* ---------- Account-Drawer: Ebenen ----------
   Uebersicht, Profil und Sicherheit sind Geschwisterpanels. Umgeschaltet
   wird per .hidden - genau wie der Drawer seine uebrigen Ansichten
   (loggedOut/loggedIn/forgot/reset) schon immer umschaltet. Bewusst
   NICHT der Detail-View-Stack aus Abschnitt 16d: der gehoert zu den
   Vollbildansichten (Teamprofil, Spielerprofil), nicht in den Drawer. */

const ACCOUNT_PANELS = ["account-root", "account-profile", "account-security"];

function showAccountPanel(panelId) {
    ACCOUNT_PANELS.forEach((id) => {
        const node = el(id);
        if (!node) return;
        if (id === panelId) {
            show(node);
        } else {
            hide(node);
        }
    });

    // Fokus in die neue Ebene holen, sonst bleibt er auf dem gerade
    // verschwundenen Knopf stehen.
    const panel = el(panelId);
    if (panel) {
        const target = panel.querySelector("button, input, a");
        if (target) target.focus({ preventScroll: true });
    }
}

function bindAccountNavigation() {
    const openProfile = el("account-open-profile");
    if (openProfile) {
        openProfile.addEventListener("click", () => showAccountPanel("account-profile"));
    }

    const openSecurity = el("account-open-security");
    if (openSecurity) {
        openSecurity.addEventListener("click", () => showAccountPanel("account-security"));
    }

    document.querySelectorAll("[data-account-back]").forEach((button) => {
        button.addEventListener("click", () => showAccountPanel("account-root"));
    });
}

function drawerFavoriteNodes() {
    return {
        section: el("account-favorite-section"),
        current: el("account-favorite-current"),
        changeBtn: el("account-favorite-change"),
        removeBtn: el("account-favorite-remove"),
        pickerHost: el("account-favorite-picker"),
        message: el("account-favorite-message"),
    };
}

function renderDrawerFavorite(me) {
    const nodes = drawerFavoriteNodes();
    if (!nodes.section) return;

    if (!me || !me.authenticated) {
        hide(nodes.section);
        return;
    }
    show(nodes.section);
    closeDrawerFavoritePicker();

    // Altbestand aus dem alten ID-Raum: Zeile bleibt in der Datenbank,
    // wird aber nicht gedeutet. Der Nutzer waehlt einmal neu, statt
    // einen womoeglich fremden Verein angezeigt zu bekommen.
    if (me.favorite_team_needs_reselect) {
        renderDrawerFavoriteTeam(null, null, { needsReselect: true });
        return;
    }

    renderDrawerFavoriteTeam(me.favorite_team_name, me.favorite_team_crest);
}

/**
 * Zeigt Name und Wappen der aktuellen Auswahl im Drawer.
 *
 * Beides kommt aus /api/auth/me bzw. direkt aus der angetippten
 * Kachel - frueher wurden dafuer bis zu sechs Tabellen nachgeladen,
 * nur um zu einer ID den Namen zu finden. Seit Name und Wappen
 * mitgespeichert werden, entfaellt das vollstaendig.
 */
function renderDrawerFavoriteTeam(teamName, crestUrl, options) {
    const nodes = drawerFavoriteNodes();
    const needsReselect = !!(options && options.needsReselect);
    const crest = el("account-favorite-crest");
    const hasTeam = Boolean(teamName) && !needsReselect;

    if (nodes.current) {
        if (needsReselect) {
            nodes.current.textContent = t("account.favoriteNeedsReselect");
        } else if (hasTeam) {
            nodes.current.textContent = t("account.favoriteCurrent", { team: teamName });
        } else {
            nodes.current.textContent = t("account.favoriteNone");
        }
    }

    if (crest) {
        if (hasTeam && crestUrl) {
            crest.onerror = () => { hide(crest); };
            crest.src = crestUrl;
            show(crest);
        } else {
            crest.removeAttribute("src");
            hide(crest);
        }
    }

    // Auch eine nicht deutbare Auswahl darf entfernt werden.
    if (nodes.removeBtn) nodes.removeBtn.disabled = !hasTeam && !needsReselect;
    if (nodes.changeBtn) {
        nodes.changeBtn.textContent = hasTeam
            ? t("account.favoriteChangeOther")
            : t("account.favoriteChoose");
    }

    renderAccountMenuFavorite();
}

function closeDrawerFavoritePicker() {
    const nodes = drawerFavoriteNodes();
    if (drawerFavorite.picker) {
        drawerFavorite.picker.destroy();
        drawerFavorite.picker = null;
    }
    if (nodes.pickerHost) hide(nodes.pickerHost);
}

function bindDrawerFavorite() {
    const nodes = drawerFavoriteNodes();
    if (!nodes.section) return;

    if (nodes.changeBtn && nodes.pickerHost) {
        nodes.changeBtn.addEventListener("click", () => {
            if (drawerFavorite.picker) {
                closeDrawerFavoritePicker();
                return;
            }
            wizardClearMessage(nodes.message);
            show(nodes.pickerHost);
            drawerFavorite.picker = createTeamPicker(nodes.pickerHost, {
                onSelect: (team) => saveDrawerFavorite(team),
            });
            drawerFavorite.picker.start();
        });
    }

    if (nodes.removeBtn) {
        nodes.removeBtn.addEventListener("click", async () => {
            wizardClearMessage(nodes.message);
            let result;
            try {
                result = await safeAuthFetch("/api/auth/favorite", { method: "DELETE" });
            } catch (error) {
                wizardShowMessage(nodes.message, t("onboarding.networkError"), true);
                return;
            }
            if (!result.ok) {
                wizardShowMessage(nodes.message,
                    visibleApiError(result.data, "onboarding.saveFailed"), true);
                return;
            }
            clearFavoriteTeamLocally();
            closeDrawerFavoritePicker();
            renderDrawerFavoriteTeam(null, null);
            wizardShowMessage(nodes.message, t("account.favoriteRemoved"), false);
        });
    }
}

async function saveDrawerFavorite(team) {
    const nodes = drawerFavoriteNodes();
    wizardShowMessage(nodes.message, t("onboarding.saving"), false);

    let result;
    try {
        result = await safeAuthFetch("/api/auth/favorite", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            // Name und Wappen kommen aus derselben Kachel, die der
            // Nutzer angetippt hat - kein spaeterer Nachschlag noetig.
            body: JSON.stringify({
                team_id: team.id,
                team_name: team.name,
                crest_url: team.crest,
                source: "apisports",
            }),
        });
    } catch (error) {
        wizardShowMessage(nodes.message, t("onboarding.networkError"), true);
        return;
    }
    if (!result.ok) {
        wizardShowMessage(nodes.message,
            visibleApiError(result.data, "onboarding.saveFailed"), true);
        return;
    }

    applyFavoriteTeamLocally(team);
    closeDrawerFavoritePicker();
    renderDrawerFavoriteTeam(team.name, team.crest);
    if (nodes.removeBtn) nodes.removeBtn.disabled = false;
    if (nodes.changeBtn) nodes.changeBtn.textContent = t("account.favoriteChangeOther");
    wizardShowMessage(nodes.message, t("account.favoriteSaved"), false);
}


// Init
document.addEventListener("DOMContentLoaded", () => {
    bindDrawerFavorite();
    bindAccountNavigation();
    checkAuth();
    initOnboarding();
});
