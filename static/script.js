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
};

const PHASE_TEXTS = {
    all:      "Komplett wertet Ligaphase und K.-o.-Phase zusammen aus.",
    league:   "Nur die Ligaphase. Hier hat noch niemand eine Runde überstanden, deshalb entfallen die Turnierkennzahlen.",
    knockout: "Nur die K.-o.-Phase. Vereine, die die Ligaphase nicht überstanden haben, tauchen hier nicht auf.",
};


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

function crest(url, className) {
    const img = make("img", className);
    img.src = url;
    img.alt = "";
    img.loading = "lazy";
    img.onerror = () => { img.style.visibility = "hidden"; };
    return img;
}

async function fetchJson(url, options) {
    const response = await fetch(url, options);
    let data = null;

    try {
        data = await response.json();
    } catch (error) {
        throw new Error("Antwort konnte nicht gelesen werden");
    }

    if (!response.ok) {
        throw new Error((data && data.error) || `Fehler ${response.status}`);
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
        seasonList.appendChild(make("div", "loading-hint", "Saisons nicht ladbar"));
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
        if (season.is_current) top.appendChild(make("span", "season-item-badge", "Aktuell"));
        if (season.is_complete) top.appendChild(make("span", "season-item-badge season-item-done", "Abgeschlossen"));

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

    setStatus(`Saison ${season.label} gewählt`);

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
    compareStatus.textContent = "Mindestens zwei Ligen auswählen";
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
    // tatsaechlich im Live-Bereich ist. Jeder andere Bereich stoppt ihn.
    if (area === "live") {
        liveInit();
    } else {
        liveStopAutoRefresh();
    }

    // Nach oben, damit der neue Bereich von seinem Anfang an gelesen wird.
    window.scrollTo({ top: 0, behavior: "auto" });
}

document.querySelectorAll(".area-btn, .bottom-nav-btn").forEach(button => {
    button.addEventListener("click", () => setActiveArea(button.dataset.area));
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

        setStatus("Bereit");
    } catch (error) {
        competitionList.innerHTML = "";
        competitionList.appendChild(
            make("div", "loading-hint", `Wettbewerbe konnten nicht geladen werden: ${error.message}`)
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

    setStatus(`${competition.name} gewählt`);

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
        ? `Saison ${state.seasonLabel} ist abgeschlossen. Alle Spieltage sind spielbar.`
        : "Gesperrte Spieltage werden freigeschaltet, sobald die Partien feststehen.";

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
                cell.title = day.message || "Noch nicht freigeschaltet";
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
    setStatus(`Spieltag ${matchday} wird geladen`);

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

    setStatus(`Champions League – ${phase === "league" ? "Ligaphase" : "K.-o.-Phase"}`);
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
            ? `Für die Champions League ${state.seasonLabel} sind aktuell noch keine Ligaphasen-Spiele verfügbar.`
            : isPastSeason
                ? "Saison abgeschlossen. Alle Spieltage sind spielbar."
                : "Spieltage der Champions-League-Ligaphase.";

        matchdays.forEach(day => {
            const cell = make("button", "matchday-cell", String(day.matchday));

            if (day.is_current) cell.classList.add("is-current");

            if (!day.available) {
                cell.classList.add("locked");
                cell.disabled = true;
                cell.title = day.message || "Noch nicht freigeschaltet";
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
    setStatus(`CL Spieltag ${matchday} wird geladen`);

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
            clKoEmpty.textContent =
                `Für die Champions League ${state.seasonLabel} stehen aktuell noch keine K.-o.-Runden fest.`;
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
                setStatus(`${stage.label} wird geladen`);

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
            fixturesEmpty.querySelector("h2").textContent =
                "Noch keine Spiele in dieser Runde";
            fixturesEmpty.querySelector("p").textContent =
                "Die Begegnungen werden angezeigt, sobald die Daten vorhanden sind.";
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

        setStatus(`${data.ties.length} Begegnungen geladen`);

    } catch (error) {
        matchList.innerHTML = "";
        matchList.appendChild(make("div", "loading-hint", `K.-o.-Daten nicht verfügbar: ${error.message}`));
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
        ? `Spieltag ${matchday}`
        : "Ausgewählte Runde";

    fixturesTitle.textContent = state.competitionName || "Spiele";

    try {
        const seasonedUrl = competitionCode === "cl" ? withExplicitSeason(url) : withSeason(url);
        const matches = await fetchJson(seasonedUrl);
        state.matches = matches;

        if (!matches.length) {
            show(fixturesEmpty);
            if (competitionCode === "cl") {
                fixturesEmpty.querySelector("h2").textContent = "Keine Ligaphasen-Spiele verfügbar";
                fixturesEmpty.querySelector("p").textContent =
                    `Für die Champions League ${state.seasonLabel} sind aktuell noch keine Ligaphasen-Spiele verfügbar.`;
            } else {
                fixturesEmpty.querySelector("h2").textContent = "Keine Spiele vorhanden";
                fixturesEmpty.querySelector("p").textContent = "Für diese Auswahl liegen keine Partien vor.";
            }
            setStatus("Keine Spiele gefunden");
            return;
        }

        matches.forEach(match => matchList.appendChild(buildMatchCard(match)));
        setStatus(`${matches.length} Partien geladen`);

    } catch (error) {
        show(fixturesEmpty);
        fixturesEmpty.querySelector("h2").textContent = "Fehler";
        fixturesEmpty.querySelector("p").textContent = error.message;
        setStatus(error.message, true);
    }
}


function buildMatchCard(match) {
    const button = make("button", "match-option");
    const wrap = make("div", "match-card-clean");

    wrap.appendChild(buildTeamRow(match.home_team, match.home_crest, match.home_id));
    wrap.appendChild(make("div", "match-vs-clean", "gegen"));
    wrap.appendChild(buildTeamRow(match.away_team, match.away_crest, match.away_id));

    if (match.status === "FINISHED" && match.home_score !== null && match.home_score !== undefined) {
        wrap.appendChild(make("div", "match-final-score", `Endstand ${match.home_score}:${match.away_score}`));
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

    selectedMatchLabel.textContent = `${match.home_team} gegen ${match.away_team}`;
    show(simControls);

    setStatus(`${match.home_team} gegen ${match.away_team}`);

    // Sanft zur Steuerung fuehren, ohne den Rest der Seite zu verlieren
    simControls.scrollIntoView({ behavior: "smooth", block: "nearest" });
}


function buildTeamRow(teamName, crestUrl, teamId) {
    const row = make("div", "match-team-side");

    const url = crestUrl || (teamId ? `https://crests.football-data.org/${teamId}.png` : null);

    if (url) row.appendChild(crest(url, "team-logo-clean"));

    row.appendChild(make("div", "team-name-clean", teamName));
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
    tableContent.appendChild(make("div", "loading-hint", "Tabelle wird geladen"));

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
        tableContent.appendChild(make("div", "loading-hint", `Tabelle nicht verfügbar: ${error.message}`));
    }
}


function renderStandings(rows) {
    tableContent.innerHTML = "";

    if (!rows || !rows.length) {
        const message = state.competitionType === "cl"
            ? `Für die Champions League ${state.seasonLabel} ist aktuell noch keine Ligaphasen-Tabelle verfügbar.`
            : "Noch keine Tabellendaten für diese Saison.";
        tableContent.appendChild(make("div", "loading-hint", message));
        return;
    }

    const table = make("table", "standings-table");
    const thead = make("thead");
    const headRow = make("tr");

    [
        { label: "#",    cls: "col-pos" },
        { label: "Team", cls: "col-team" },
        { label: "Sp",   cls: "" },
        { label: "S",    cls: "" },
        { label: "U",    cls: "" },
        { label: "N",    cls: "" },
        { label: "Tore", cls: "" },
        { label: "Diff", cls: "" },
        { label: "Pkt",  cls: "col-points" },
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
            { cls: "pos-cl",         text: "Direkt im Achtelfinale" },
            { cls: "pos-el",         text: "K.-o.-Play-offs" },
            { cls: "pos-relegation", text: "Ausgeschieden" },
        ]
        : [
            { cls: "pos-cl",         text: "Champions League" },
            { cls: "pos-el",         text: "Europapokal" },
            { cls: "pos-relegation", text: "Abstiegszone" },
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
    scorersContent.appendChild(make("div", "loading-hint", "Torjäger werden geladen"));

    try {
        const url = `/api/player-scorers?competition=${competitionCode}&limit=20`;
        const data = await fetchJson(
            competitionCode === "cl" ? withExplicitSeason(url) : withSeason(url)
        );

        scorersTitle.textContent = `Torjäger ${data.competition}`;

        if (data.empty_state) {
            scorersContent.innerHTML = "";
            scorersContent.appendChild(
                make("div", "loading-hint", data.empty_state_message ||
                    "Für diese Saison liegen noch keine Torjägerdaten vor.")
            );
            return;
        }

        renderScorers(data.scorers);

    } catch (error) {
        scorersContent.innerHTML = "";
        scorersContent.appendChild(
            make("div", "loading-hint", `Torjägerliste nicht verfügbar: ${error.message}`)
        );
    }
}


function renderScorers(scorers) {
    scorersContent.innerHTML = "";

    if (!scorers || !scorers.length) {
        scorersContent.appendChild(make("div", "loading-hint", "Noch keine Torschuetzen in dieser Saison."));
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
                ? `${scorer.team_name} · ${scorer.appearances} Spiele`
                : scorer.team_name
        ));
        row.appendChild(info);

        const stats = make("div", "scorer-stats");
        stats.appendChild(buildStat(scorer.goals, "Tore"));

        if (scorer.assists !== null && scorer.assists !== undefined) {
            stats.appendChild(buildStat(scorer.assists, "Vorlagen"));
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

backToFixtures.addEventListener("click", () => switchTab("fixtures"));


async function runSimulation() {
    if (!state.selectedMatch) {
        setStatus("Bitte zuerst eine Partie auswählen", true);
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

    simulateBtn.disabled = true;
    simulateBtn.textContent = "Wird berechnet";
    setStatus("Simulation läuft");

    try {
        const data = await fetchJson("/api/simulate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        renderResult(data);

        // Direkt zum Ergebnis wechseln, damit niemand danach suchen muss
        switchTab("simulation");
        setStatus("Simulation abgeschlossen");

    } catch (error) {
        setStatus(error.message, true);
    } finally {
        simulateBtn.disabled = false;
        simulateBtn.textContent = "Simulieren";
    }
}


function renderResult(data) {
    hide(simEmpty);
    show(resultBox);

    el("match-title").textContent = `${data.home_team} gegen ${data.away_team}`;

    const outcomes = [
        { label: `Sieg ${data.home_team}`, value: data.home_win_probability },
        { label: "Unentschieden",          value: data.draw_probability },
        { label: `Sieg ${data.away_team}`, value: data.away_win_probability },
    ];

    const top = outcomes.reduce((best, current) => current.value > best.value ? current : best);

    el("top-pick-name").textContent = top.label;
    el("top-pick-value").textContent = `${top.value} Prozent`;

    el("xg-home-team").textContent = data.home_team;
    el("xg-away-team").textContent = data.away_team;
    el("xg-home").textContent = data.expected_home_goals;
    el("xg-away").textContent = data.expected_away_goals;

    if (data.top_scores && data.top_scores.length) {
        el("best-score").textContent = data.top_scores[0].score;
        el("best-score-count").textContent = `${data.top_scores[0].count} von allen Simulationen`;
    }

    renderProbabilityBars(outcomes);
    renderTopScores(data.top_scores);

    if (data.is_two_legged_tie) {
        renderKnockout(data);
        show(knockoutSection);
    } else {
        hide(knockoutSection);
    }
}


function renderProbabilityBars(outcomes) {
    const container = el("probability-bars");
    container.innerHTML = "";

    outcomes.forEach(outcome => {
        const block = make("div", "bar-block");

        const header = make("div", "bar-header");
        header.appendChild(make("span", null, outcome.label));
        header.appendChild(make("span", null, `${outcome.value} Prozent`));

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
        container.appendChild(make("div", "loading-hint", "Keine Ergebnisse vorhanden."));
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
            `${((entry.count / total) * 100).toFixed(1)} Prozent der Faelle`));
        left.appendChild(textWrap);

        const right = make("div", "score-count");
        right.appendChild(make("div", null, String(entry.count)));
        right.appendChild(make("div", "score-count-label", "Simulationen"));

        row.appendChild(left);
        row.appendChild(right);
        container.appendChild(row);
    });
}


function renderKnockout(data) {
    knockoutContent.innerHTML = "";

    if (data.first_leg_score) {
        const info = make("div", "knockout-card");
        info.appendChild(make("p", null, "Hinspiel"));
        info.appendChild(make("div", "knockout-value", data.first_leg_score));
        knockoutContent.appendChild(info);
    }

    const grid = make("div", "knockout-columns");

    [
        {
            title: "Weiterkommen",
            rows: [
                [data.home_team, `${data.qualification_home_probability} Prozent`],
                [data.away_team, `${data.qualification_away_probability} Prozent`],
            ],
        },
        {
            title: "Verlängerung und Elfmeter",
            rows: [
                ["Verlängerung", `${data.extra_time_probability} Prozent`],
                ["Elfmeterschießen", `${data.penalties_probability} Prozent`],
            ],
        },
        {
            title: "Entscheidung im Elfmeterschießen",
            rows: [
                [data.home_team, `${data.home_qualifies_on_penalties_probability} Prozent`],
                [data.away_team, `${data.away_qualifies_on_penalties_probability} Prozent`],
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
        aggregate.appendChild(make("p", null, "Häufigste Gesamtergebnisse"));

        data.top_aggregate_scores.forEach(entry => {
            const row = make("div", "knockout-row");
            row.appendChild(make("span", null, entry.score));
            row.appendChild(make("strong", null, `${entry.count} mal`));
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
            compareHeading.textContent = "Welche Liga hat in Europa dominiert?";
            compareHint.textContent =
                "Alle Vereine einer Liga werden zusammen wie eine Mannschaft betrachtet. " +
                "Vereine ohne Teilnahme bleiben aussen vor.";
        } else {
            hide(phaseSection);
            compareEyebrow.textContent = "Ligenvergleich";
            compareHeading.textContent = "Welche Liga liefert die besseren Zahlen?";
            compareHint.textContent =
                "Wähle zwei bis fuenf Ligen. Alle Werte stammen aus den bereits gespielten Partien der Saison.";
        }
    });
});


document.querySelectorAll(".phase-btn").forEach(button => {
    button.addEventListener("click", () => {
        clearActive(".phase-btn");
        button.classList.add("active");

        state.comparePhase = button.dataset.phase;
        phaseHint.textContent = PHASE_TEXTS[state.comparePhase] || "";
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
            compareStatus.textContent = "Maximal fuenf Ligen gleichzeitig";
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
        ? "Mindestens zwei Ligen auswählen"
        : `${count} Ligen ausgewählt`;
}


compareBtn.addEventListener("click", runComparison);


async function runComparison() {
    if (state.compareSelection.length < 2) return;

    compareBtn.disabled = true;
    compareBtn.textContent = "Wird berechnet";
    compareStatus.textContent = "Saisondaten werden ausgewertet";

    const leagues = state.compareSelection.join(",");

    const url = state.compareMode === "cup"
        ? withSeason(`/api/cup-compare?leagues=${leagues}&phase=${state.comparePhase}&cup=cl`)
        : withSeason(`/api/compare?leagues=${leagues}`);

    try {
        const data = await fetchJson(url);

        if (state.compareMode === "cup") {
            renderCupComparison(data);
        } else {
            renderComparison(data);
        }

        compareStatus.textContent = "Vergleich fertig";

    } catch (error) {
        compareStatus.textContent = error.message;
    } finally {
        compareBtn.disabled = false;
        compareBtn.textContent = "Vergleichen";
    }
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
        head.appendChild(make("span", "metric-card-title", row.label));
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

            chip.appendChild(make("span", "stage-chip-name", runde));
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
    headRow.appendChild(make("th", null, "Kennzahl"));
    leagues.forEach(league => headRow.appendChild(make("th", null, league.name)));
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = make("tbody");

    section.rows.forEach(row => {
        const tr = make("tr");
        tr.appendChild(make("td", null, row.label));

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
            card.appendChild(make("div", "compare-header-leader",
                `Erster: ${league.leader.team_name} mit ${league.leader.points} Punkten aus ${league.leader.played} Spielen`));
        }

        header.appendChild(card);
    });

    compareResult.appendChild(header);

    data.sections.forEach(section => {
        if (!section.rows || !section.rows.length) return;

        const wrap = make("div", "compare-section");
        wrap.appendChild(make("h3", "compare-section-title", section.title));

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
    intro.appendChild(make("h2", null, data.phase_label));

    if (data.stages_played && data.stages_played.length) {
        intro.appendChild(make("p", "cup-intro-sub",
            `Ausgewertete Runden: ${data.stages_played.join(", ")}`));
    }

    if (data.notice) {
        intro.appendChild(make("p", "cup-notice", data.notice));
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
        card.appendChild(make("div", "compare-header-leader",
            league.teams === 1 ? "1 Verein dabei" : `${league.teams} Vereine dabei`));

        if (league.is_champion) {
            card.appendChild(make("div", "champion-badge", "Titelgewinner"));
        }

        if (league.biggest_win) {
            card.appendChild(make("div", "compare-header-extra",
                `Hoechster Sieg: ${league.biggest_win.label}`));
        }

        header.appendChild(card);
    });

    compareResult.appendChild(header);

    // Kennzahlen
    data.sections.forEach(section => {
        if (!section.rows || !section.rows.length) return;

        const wrap = make("div", "compare-section");
        wrap.appendChild(make("h3", "compare-section-title", section.title));

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
        wrap.appendChild(make("h3", "compare-section-title", "Wie weit kamen die Vereine"));

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

    wrap.appendChild(make("h3", "compare-section-title", "Gesamtranking"));

    // Kurzer Hinweis direkt ueber der Liste – kein langer Satz unten
    const hint = make("p", "ranking-score-hint",
        "Score bis 100. Die Liga mit dem besten Wert je Kennzahl bekommt 100, alle anderen werden relativ dazu bewertet.");
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

        const subParts = [entry.teams === 1 ? "1 Verein" : `${entry.teams} Vereine`];
        if (entry.is_champion) subParts.push("Titelgewinner");
        info.appendChild(make("div", "ranking-sub", subParts.join(" · ")));

        row.appendChild(info);

        const scoreWrap = make("div", "ranking-score");
        scoreWrap.appendChild(make("strong", null, String(entry.score)));
        scoreWrap.appendChild(make("span", null, "von 100"));
        row.appendChild(scoreWrap);

        list.appendChild(row);

        // Aufschluesselung, damit das Ergebnis nachvollziehbar bleibt
        if (entry.breakdown && entry.breakdown.length) {
            const detail = make("div", "ranking-breakdown");

            entry.breakdown.forEach(item => {
                const chip = make("div", "breakdown-chip");
                chip.appendChild(make("span", "breakdown-label", item.label));
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
    const weights = make("p", "ranking-weights",
        ranking.basis + " • Gewichtung: " +
        ranking.weights.map(w => `${w.label} ${w.weight_percent} %`).join(", ")
    );
    wrap.appendChild(weights);

    return wrap;
}


function buildReachedTable(reached) {
    const wrap = make("div");

    const stageNames = Object.keys(reached[0].stages || {});

    const table = make("table", "compare-table");

    const thead = make("thead");
    const headRow = make("tr");
    headRow.appendChild(make("th", null, "Liga"));
    stageNames.forEach(name => headRow.appendChild(make("th", null, name)));
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
    seasonSimBtn.textContent = "Wird simuliert…";
    hide(seasonSimResult);
    setStatus(`Saison wird ${sims.toLocaleString("de")} × simuliert…`);

    const url = withSeason(`/api/season-sim?competition=${state.competitionCode}&simulations=${sims}`);

    try {
        const data = await fetchJson(url);
        renderSeasonSim(data);
        switchTab("season");
        setStatus("Saisonsimulation fertig");
    } catch (error) {
        setStatus(error.message, true);
    } finally {
        seasonSimBtn.disabled = false;
        seasonSimBtn.textContent = "Saison simulieren";
    }
}

function renderSeasonSim(data) {
    const season = data.season;
    const nextYear = season ? String(season + 1).slice(2) : "";
    const label = season ? `${season}/${nextYear}` : "";

    seasonSimTitle.textContent = `${data.competition} ${label}`;
    seasonSimEyebrow.textContent = "Saisonsimulation";

    const favorite = data.entries && data.entries[0];
    if (favorite) {
        seasonSimFavorite.textContent = favorite.team_name;
        seasonSimFavPct.textContent = `${favorite.champion_pct} % Meister`;
    }

    if (data.season_done) {
        seasonSimInfo.textContent = "Saison abgeschlossen – das ist das Endergebnis.";
    } else {
        seasonSimInfo.textContent =
            `${data.simulations.toLocaleString("de")} Simulationen · ` +
            `${data.games_remaining} Spiele noch offen · ` +
            `Spieltag ${data.played_matchdays} von ${data.total_matchdays}`;
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
        parts.push(
            "Die Saison hat noch nicht begonnen. Die Prognose beruht auf den " +
            (q.historical_seasons || 0) + " zuletzt abgeschlossenen Spielzeiten " +
            "und wird mit jedem gespielten Spieltag genauer."
        );
    } else if (played <= 8) {
        parts.push(
            "Frühe Saisonphase: Die Prognose stützt sich noch überwiegend auf " +
            "die Vorsaisons, die aktuellen Ergebnisse fließen zunehmend ein."
        );
    }

    if (q.teams_promoted > 0) {
        parts.push(
            q.teams_promoted === 1
                ? "Ein Aufsteiger wird über Erfahrungswerte vergleichbarer Teams eingeschätzt."
                : q.teams_promoted + " Aufsteiger werden über Erfahrungswerte vergleichbarer Teams eingeschätzt."
        );
    }

    // Vorsaison-Daten fehlen: Der Aufsteiger-Status ist dann nicht
    // feststellbar. Lieber ehrlich benennen als falsche Badges zeigen.
    if (q.previous_season_available === false && q.teams_without_history > 0) {
        parts.push(
            q.teams_without_history + " Teams ohne hinterlegte Vorsaison-Daten " +
            "laufen vorerst auf einem neutralen Erwartungswert. Nach dem " +
            "nächsten Daten-Update werden sie präziser eingestuft."
        );
    }

    if (q.teams_neutral > 0) {
        tone = "warn";
        parts.push(
            q.teams_neutral + " von " + q.teams_total + " Teams haben keine " +
            "verwertbaren Daten und laufen auf einem Neutralwert. Ihre " +
            "Platzierung ist entsprechend unsicher."
        );
    }

    if (!parts.length) return;

    const hint = make("div", `season-quality-hint tone-${tone}`);
    hint.id = "season-quality-hint";
    hint.appendChild(make("span", "season-quality-icon", tone === "warn" ? "\u26A0" : "\u2139"));

    const body = make("div", "season-quality-body");
    parts.forEach(text => body.appendChild(make("div", "season-quality-text", text)));

    if (q.avg_confidence !== undefined) {
        const meta = make("div", "season-quality-meta");
        meta.textContent =
            `Datengrundlage: ${q.teams_with_history}/${q.teams_total} Teams mit Historie · ` +
            `mittlere Verlässlichkeit ${Math.round((q.avg_confidence || 0) * 100)} %`;
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
        const badge = make("span", "season-team-badge level-3", "Aufsteiger");
        badge.title = entry.has_historical_data
            ? "Aufsteiger mit früherer Erstliga-Historie."
            : "Aufsteiger, eingeschätzt über Erfahrungswerte vergleichbarer Aufsteiger.";
        return badge;
    }

    if (level === undefined || level <= 1) return null;

    let label, title;

    if (level === 2) {
        label = "neu";
        title = "Nur Daten der laufenden Saison, keine Vorsaison-Historie.";
    } else {
        label = "wenig Daten";
        title = "Keine Vorsaison-Daten gefunden – die Einschätzung ist entsprechend unsicher.";
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
            sub.push(`Ø ${entry.expected_points} Endpunkte`);
        }
        if (entry.current_played) {
            sub.push(`Aktuell ${entry.current_points} Pkt (${entry.current_played} Sp.)`);
        }
        if (entry.games_remaining) sub.push(`${entry.games_remaining} Spiele offen`);
        nameWrap.appendChild(make("div", "season-team-sub", sub.join(" · ")));

        left.appendChild(nameWrap);
        row.appendChild(left);

        // Rechte Seite: Wahrscheinlichkeiten
        const right = make("div", "season-row-right");

        const pcts = [
            { label: "Meister",   pct: entry.champion_pct,   cls: "pct-champion" },
            { label: "CL",        pct: entry.cl_pct,          cls: "pct-cl" },
            { label: "Abstieg",   pct: entry.relegation_pct,  cls: "pct-rel" },
        ];

        pcts.forEach(({ label, pct, cls }) => {
            if (pct === null || pct === undefined) return;
            if (pct < 0.5 && label === "Meister" && entry.rank > 5) return;

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
    clSeasonSimBtn.textContent = "Wird simuliert…";
    hide(clSeasonSimResult);
    setStatus(`Ligaphase wird ${sims.toLocaleString("de")} × simuliert…`);

    const url = withExplicitSeason(`/api/cl-season-sim?simulations=${sims}`);

    try {
        const data = await fetchJson(url);

        // Noch nicht ausgelost ist ein normaler Zustand, kein Fehler.
        if (data.empty_state) {
            state.clSeasonSim = null;
            hide(clSeasonSimControls);
            hide(clSeasonSimResult);
            clSeasonSimEmpty.querySelector("h2").textContent = "Ligaphase noch nicht verfügbar";
            clSeasonSimEmpty.querySelector("p").textContent =
                data.empty_state_message ||
                "Sobald die Spielpaarungen der Ligaphase feststehen, kann sie hier simuliert werden.";
            show(clSeasonSimEmpty);
            setStatus("Ligaphase noch nicht verfügbar");
            return;
        }

        state.clSeasonSim = data;
        renderClSeasonSim(data);
        switchTab("cl-season");
        setStatus("Ligasimulation fertig");

    } catch (error) {
        setStatus(error.message, true);
    } finally {
        clSeasonSimBtn.disabled = false;
        clSeasonSimBtn.textContent = "Ligaphase simulieren";
    }
}


function renderClSeasonSim(data) {
    const season = data.season;
    const label = season ? `${season}/${String(season + 1).slice(2)}` : "";

    clSeasonSimTitle.textContent = `${data.competition} ${label} · Ligaphase`;

    const favorite = data.entries && data.entries[0];
    if (favorite) {
        clSeasonSimFavorite.textContent = favorite.team_name;
        clSeasonSimFavPct.textContent = `${favorite.top_seed_pct} % Platz 1`;
    }

    const parts = [`${data.simulations.toLocaleString("de")} Simulationen`];

    if (data.mode === "full_resimulation") {
        parts.push(`alle ${data.fixtures_simulated} Ligaphasen-Spiele neu simuliert`);
    } else {
        parts.push(`${data.fixtures_simulated} Spiele offen`);
        parts.push(`${data.fixtures_fixed} Ergebnisse übernommen`);
    }

    parts.push(`${data.teams_total} Teams`);
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

        const sub = [`Ø ${entry.expected_points} Punkte`];
        if (entry.current_played) {
            sub.push(`Aktuell ${entry.current_points} Pkt (${entry.current_played} Sp.)`);
        }
        if (entry.games_remaining) sub.push(`${entry.games_remaining} Spiele offen`);
        nameWrap.appendChild(make("div", "season-team-sub", sub.join(" · ")));

        left.appendChild(nameWrap);
        row.appendChild(left);

        const right = make("div", "season-row-right");

        [
            { label: "Achtelfinale",  pct: entry.direct_pct,     cls: "pct-cl" },
            { label: "Play-offs",     pct: entry.playoff_pct,    cls: "pct-champion" },
            { label: "Ausgeschieden", pct: entry.eliminated_pct, cls: "pct-rel" },
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
        const badge = make("span", "season-team-badge level-2", "CL-Daten");
        badge.title = "Keine Historie aus einer Top-5-Liga. Eingeschätzt über die echten Champions-League-Ergebnisse dieser Saison.";
        return badge;
    }

    if (entry.resolution === "neutral") {
        const badge = make("span", "season-team-badge level-4", "wenig Daten");
        badge.title = "Weder Historie aus einer Top-5-Liga noch Champions-League-Ergebnisse vorhanden – die Einschätzung ist entsprechend unsicher.";
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
    minutes: "Ø Minuten",
    goals: "Ø Tore",
    assists: "Ø Assists",
    scorer_points: "Ø Scorer",
    rating: "Ø Rating",
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
    tcSetStatus("Saisons werden geladen ...");

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
            tcSetStatus("Keine gemeinsame Saison fuer diese Ligakombination verfuegbar.", true);
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
        tcSetStatus("Saisons konnten nicht geladen werden: " + (error.message || "Fehler"), true);
        seasonSelect.disabled = false;
    }
}

async function tcInitControls() {
    if (tcControlsReady) return;
    tcControlsReady = true;

    tcSetStatus("Ligen werden geladen ...");

    let leagues;
    try {
        leagues = await tcFetchLeagues();
    } catch (error) {
        tcSetStatus("Ligenliste konnte nicht geladen werden: " + (error.message || "Fehler"), true);
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
        problem = "Quelliga A und B muessen unterschiedlich sein";
    } else if (target === fromA || target === fromB) {
        problem = "Die Zielliga darf keiner Quelliga entsprechen";
    }

    button.disabled = Boolean(problem) || tcRunning;
    tcSetStatus(problem || "Bereit", Boolean(problem));
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
    button.textContent = "Analyse laeuft";
    tcSetStatus("Transferdaten werden ausgewertet. Der erste Lauf kann eine Weile dauern.");

    try {
        const url = `/api/transfer-compare?from_a=${fromA}&from_b=${fromB}&to=${target}&season=${season}`;
        const data = await fetchJson(url);
        tcLastResult = data;
        tcRenderResult(data);
        tcSetStatus("Deine Analyse ist fertig");
    } catch (error) {
        const msg = error.message || "Unbekannter Fehler";
        tcSetStatus("\u26a0 " + msg, true);
        tcLastResult = null;
        hide(el("transfer-compare-sort-row"));
        transferResult.innerHTML = "";
        hide(transferResult);
        show(transferEmpty);
        transferEmpty.innerHTML = `<h2>Analyse konnte nicht geladen werden</h2><p>${msg}</p>`;
    } finally {
        tcRunning = false;
        button.disabled = false;
        button.textContent = "Vergleich analysieren";
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
    head.appendChild(make("p", "eyebrow", "Deine Analyse"));
    head.appendChild(make("h2", "transfer-compare-title",
        `${query.source_a_label} vs. ${query.source_b_label}`));
    head.appendChild(make("p", "transfer-compare-subtitle",
        `Entwicklung der Sommertransfers in der ${query.target_label}`));
    head.appendChild(make("p", "transfer-compare-season",
        `Saisonwechsel ${query.season_label} \u00b7 Mindestspielzeit ${query.minimum_minutes} Minuten`));
    transferResult.appendChild(head);

    // Neutrale Hinweise
    (data.warnings || []).forEach(text => {
        transferResult.appendChild(make("p", "transfer-compare-warning", text));
    });

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
        `${sample.transfers_total} Transfers gefunden`));
    sampleBox.appendChild(make("div", null,
        `${sample.qualified} Spieler mit mindestens ${query.minimum_minutes} Minuten`));
    sampleBox.appendChild(make("div", null,
        `${sample.low_minutes} Spieler unter ${query.minimum_minutes} Minuten`));
    if (sample.missing_data > 0) {
        sampleBox.appendChild(make("div", null,
            `${sample.missing_data} Spieler ohne vollstaendige Daten`));
    }
    card.appendChild(sampleBox);

    const metrics = make("div", "transfer-compare-metrics");
    Object.keys(TC_METRIC_LABELS).forEach(metric => {
        const row = make("div", "transfer-compare-metric-row");
        if (comparison[metric] === side) row.classList.add("transfer-compare-better");

        row.appendChild(make("span", "transfer-compare-metric-label",
            TC_METRIC_LABELS[metric]));
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
    summary.textContent = `${group.league_label}-Spieler anzeigen`;
    details.appendChild(summary);

    const players = group.players || {};

    const addList = (title, list, extraClass) => {
        if (!list || !list.length) return;
        details.appendChild(make("h4", "transfer-compare-list-title", title));
        list.forEach(player => {
            details.appendChild(tcBuildPlayerRow(player, extraClass));
        });
    };

    addList("Qualifizierte Spieler", tcSortPlayers(players.qualified, tcSortCriterion), "");
    addList("Zu wenig Einsatzzeit", tcSortPlayers(players.low_minutes, tcSortCriterion), "transfer-compare-player-low");
    addList("Keine vollstaendigen Daten", players.missing_data, "transfer-compare-player-missing");

    if (!(players.qualified || []).length &&
        !(players.low_minutes || []).length &&
        !(players.missing_data || []).length) {
        details.appendChild(make("p", "transfer-compare-list-title",
            "Fuer diese Ligakombination und diesen Saisonwechsel wurden keine passenden Sommertransfers gefunden."));
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
    info.appendChild(make("div", "transfer-compare-player-name", player.player_name || "Unbekannt"));

    const moveText = `${player.from_team_name || "?"} \u2192 ${player.to_team_name || "?"}`
        + ` \u00b7 ${player.transfer_type || "Unbekannt"}`
        + (player.position ? ` \u00b7 ${player.position}` : "");
    info.appendChild(make("div", "transfer-compare-player-move", moveText));
    row.appendChild(info);

    const stats = make("div", "transfer-compare-player-stats");
    if (player.data_available) {
        const parts = [
            `${player.minutes ?? 0} Min`,
            `${player.goals ?? 0} Tore`,
            player.assists !== null && player.assists !== undefined
                ? `${player.assists} Assists` : "Assists \u2013",
            player.rating !== null && player.rating !== undefined
                ? `Rating ${Number(player.rating).toFixed(2)}` : "Rating \u2013",
        ];
        stats.textContent = parts.join(" \u00b7 ");
    } else {
        stats.textContent = "Keine Daten verfuegbar";
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

   Hintergrund: Das i18n-System aus Phase 2.1 wurde zurueckgerollt, es gibt
   derzeit kein t(). Statt neue Texte wieder ueber die Datei zu verstreuen,
   liegen sie hier gebuendelt. Wird i18n spaeter erneut eingefuehrt, muss nur
   dieses Objekt gegen Uebersetzungsaufrufe getauscht werden - die Aufrufer
   bleiben unveraendert.

   Der Fachbegriff "Perzentil" taucht bewusst nur in Erklaertexten auf,
   nie als Hauptbotschaft. Nutzer lesen "besser als 87 %", nicht "P87".
*/
const PC_TEXT = {
    positionHint: {
        Goalkeeper: "Es werden nur Torhüter gefunden. Das Radar zeigt Paraden, Gegentore und Spielaufbau.",
        Defender:   "Es werden nur Verteidiger gefunden. Das Radar zeigt Zweikämpfe, Abfangen und Passspiel.",
        Midfielder: "Es werden nur Mittelfeldspieler gefunden. Das Radar zeigt Passspiel, Kreativität und Defensivarbeit.",
        Attacker:   "Es werden nur Stürmer und Flügelspieler gefunden. Das Radar zeigt Abschluss, Vorlagen und Dribbling.",
        free:       "Alle Positionen erlaubt. Verglichen werden nur Kennzahlen, die für jede Position dieselbe Bedeutung haben.",
    },
    resetOnSwitch: "Auswahl zurückgesetzt, weil du eine andere Positionsgruppe gewählt hast.",

    // Wettbewerbsumfang. Die Texte spiegeln SCOPE_HINTS im Backend,
    // damit Oberflaeche und Dokumentation dasselbe sagen.
    scopeHint: {
        club_all: "Liga, nationale Pokale und europäische Wettbewerbe zusammen.",
        league:   "Nur die nationale Liga. Der fairste Vergleich, weil alle Spieler dieselbe Anzahl Partien und dieselben Gegner haben.",
        cl:       "Nur Champions League. Weniger Partien als eine Ligasaison, dafür durchgehend hohes Gegnerniveau.",
        euro:     "Nur die Endrunde der Europameisterschaft. Ein kurzes Turnier – als kleine Stichprobe zu lesen.",
        world_cup: "Nur die Endrunde der Weltmeisterschaft. Ein kurzes Turnier – als kleine Stichprobe zu lesen.",
        national: "Nur Länderspiele. Wenige Partien pro Saison, daher als kleine Stichprobe zu lesen.",
        all:      "Verein und Nationalmannschaft zusammen. Mischt sehr unterschiedliche Wettbewerbsniveaus.",
    },
    // Fachlicher Normalzustand, kein Fehler: der Spieler hat in dieser
    // Saison schlicht nicht in diesem Wettbewerb gespielt.
    scopeNoData: (name, scopeLabel) =>
        `${name} hat in dieser Saison keine Einsätze in der Datenbasis „${scopeLabel}“.`,
    scopeNoDataShort: "Keine Einsätze in dieser Datenbasis",
    scopeNoDataBoth: (scopeLabel) =>
        `Für beide Spieler liegen in dieser Saison keine Einsätze in der Datenbasis „${scopeLabel}“ vor.`,
    scopeChanged: "Datenbasis geändert – der Vergleich wird neu berechnet.",
    // Turnier fand im gewaehlten Saisonzyklus nicht statt. Ein normaler
    // fachlicher Zustand, deshalb nur ein Tooltip - keine Fehlermeldung.
    scopeUnavailable: "In diesem Saisonzyklus fand dieses Turnier nicht statt.",

    // Plots
    scatterLoading: "Spielerdaten werden ausgewertet…",
    scatterError: "Die Spielerdaten konnten nicht geladen werden. Bitte später erneut versuchen.",
    scatterCreate: "Plot erstellen",
    scatterUpdate: "Plot aktualisieren",
    scatterFiltersChanged: "Filter geändert – auf „Plot aktualisieren“ tippen.",
    scatterReady: (n) => `${n} Spieler im Plot`,
    scatterManyPoints: (n) =>
        `${n} Spieler – für mehr Übersicht Position oder Ligen eingrenzen.`,
    scatterNoMatch: (minutes) =>
        `Keine Spieler mit mindestens ${minutes} Einsatzminuten für diese Auswahl. `
        + "Mindestminuten senken oder mehr Ligen auswählen.",
    scatterPoolMissing:
        "Die Spielerdaten wurden noch nicht importiert. Auf dem Server einmalig "
        + "„refresh_players.py --all“ ausführen, danach steht der Plot zur Verfügung.",
    scatterPoolPartial: (missing) =>
        `Noch nicht alle Ligen importiert – es fehlen: ${missing}. `
        + "Der Plot zeigt nur die bereits vorhandenen Ligen.",
    scatterPoolOutdated:
        "Die Spielerdaten stammen aus einer älteren Version und müssen einmal "
        + "neu importiert werden („refresh_players.py --all“).",

    rankAvailable:   (pct) => `Besser als ${pct} % der Vergleichsgruppe`,
    rankTop:         (pct) => `Top ${pct} % der Vergleichsgruppe`,
    rankUnavailable: "Vergleichsrang noch nicht verfügbar",
    rankShortMinutes: "Zu wenig Einsatzzeit für eine Einordnung",

    rawOnly: "Aktuell siehst du die reinen Saisonwerte. Für die Einordnung "
           + "gegenüber anderen Spielern fehlen noch vorbereitete Vergleichsdaten.",

    rankExplain: (leagues, season, minutes) =>
        `Verglichen wird gegen Spieler derselben Position ${leagues} `
        + `in der Saison ${season} mit mindestens ${minutes} Einsatzminuten. `
        + `Fachlich ist das ein Perzentil.`,
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
        pcPositionNote.textContent =
            PC_TEXT.positionHint[position] || PC_TEXT.positionHint.free;
    }

    if (hadSelection && !silent) {
        pcResetSelection();
        pcStatus.textContent = PC_TEXT.resetOnSwitch;
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

    pcState.scope = scope;

    document.querySelectorAll(".pc-scope-btn").forEach(button => {
        const active = button.dataset.scope === scope;
        button.classList.toggle("active", active);
        button.setAttribute("aria-checked", active ? "true" : "false");
        button.tabIndex = active ? 0 : -1;
    });

    if (pcScopeNote) {
        pcScopeNote.textContent = PC_TEXT.scopeHint[scope] || "";
    }

    if (silent) return;

    // Beide Spieler bleiben gewaehlt. Nur ein bereits berechnetes Ergebnis
    // passt nicht mehr zur neuen Datenbasis und wird nachgezogen.
    if (pcState.lastComparison && pcState.a.player && pcState.b.player) {
        pcStatus.textContent = PC_TEXT.scopeChanged;
        pcRunComparison();
    }
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

        // Nur Scopes, die das Backend ueberhaupt als Turnier fuehrt,
        // koennen fehlen. Alle uebrigen sind immer waehlbar.
        const known = maps.some(m => Object.prototype.hasOwnProperty.call(m, scope));
        const usable = !known || maps.some(m => m[scope]);

        button.disabled = !usable;
        button.setAttribute("aria-disabled", usable ? "false" : "true");
        button.title = usable ? "" : PC_TEXT.scopeUnavailable;

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

    const scatterSeason = [pcState.season].filter(s => s);
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
                // Saisons ohne Referenzpool werden gekennzeichnet, damit
                // niemand fehlende Perzentile fuer einen Fehler haelt.
                option.textContent = season.percentiles_available
                    ? season.label
                    : `${season.label} (nur Rohwerte)`;
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
                pcClearSlot(slot);
                pcUpdateReady();

                // Slot A fuehrt die geteilte Saison fuer Plots.
                if (slot === "a") {
                    pcState.season = pcState.a.season;
                    if (pcState.scatter.ready) pcScatterMarkDirty();
                }

                // EM/WM gibt es nicht in jeder Saison - Auswahl nachziehen.
                pcRefreshScopeAvailability();
            });
        }

        pcState.ready = true;
        pcRefreshScopeAvailability();
        pcUpdateReady();

    } catch (error) {
        pcStatus.textContent = "Saisons konnten nicht geladen werden.";
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

    try {
        const url = `/api/player-search?q=${encodeURIComponent(query)}`
                  + `&season=${slotState.season}`;
        const response = await fetch(url);
        const data = await response.json();

        if (requestId !== slotState.requestId) return;   // veraltete Antwort

        if (!response.ok) {
            pcRenderResults(slot, null, "error", data.error || "Suche fehlgeschlagen.");
            return;
        }

        // Die API-Antwort wird ungefiltert gecacht (Backend), erst hier
        // auf die aktive Positionsgruppe reduziert. Ein Wechsel der Gruppe
        // kostet dadurch keinen einzigen zusaetzlichen API-Request.
        slotState.results = pcFilterByPosition(data.results);
        slotState.activeIndex = -1;
        pcRenderResults(slot, slotState.results, "ok");

    } catch (error) {
        if (requestId !== slotState.requestId) return;
        pcRenderResults(slot, null, "error", "Suche nicht erreichbar.");
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
        box.appendChild(make("div", "pc-result-note", "Wird gesucht…"));
        return;
    }

    if (mode === "error") {
        box.appendChild(make("div", "pc-result-note pc-result-error",
                             message || "Suche fehlgeschlagen."));
        return;
    }

    if (!results || results.length === 0) {
        box.appendChild(make("div", "pc-result-note", "Keine Spieler gefunden."));
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
        text.appendChild(make("span", "pc-result-name", player.name || "Unbekannt"));

        const metaParts = [];
        if (player.team_name) metaParts.push(player.team_name);
        if (player.league_label) metaParts.push(player.league_label);
        if (player.position_label) metaParts.push(player.position_label);
        if (player.age) metaParts.push(`${player.age} Jahre`);

        text.appendChild(make("span", "pc-result-meta", metaParts.join(" · ")));

        if (!player.comparable) {
            text.appendChild(make("span", "pc-result-warning",
                                  "keine Daten in den Top-5-Ligen"));
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
    info.appendChild(make("span", "pc-player-name", player.name || "Unbekannt"));

    const meta = [];
    if (player.team_name) meta.push(player.team_name);
    if (player.position_label) meta.push(player.position_label);
    info.appendChild(make("span", "pc-player-meta", meta.join(" · ")));

    const minutes = player.minutes
        ? `${player.minutes.toLocaleString("de")} Minuten`
        : "keine Einsatzzeit";
    info.appendChild(make("span", "pc-player-minutes", minutes));

    card.appendChild(info);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "pc-remove-btn";
    remove.setAttribute("aria-label", `${player.name} entfernen`);
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

    let message = "Bitte zwei Spieler auswählen";
    let enabled = false;

    if (a && b) {
        if (a.player_id === b.player_id && pcState.a.season === pcState.b.season) {
            // Derselbe Spieler in derselben Saison ergibt keinen Vergleich,
            // in zwei verschiedenen Saisons dagegen schon.
            message = "Bitte zwei unterschiedliche Spieler oder Saisons wählen";
        } else {
            message = "Bereit";
            enabled = true;
        }
    } else if (a || b) {
        message = "Noch einen zweiten Spieler auswählen";
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

    pcCompareBtn.disabled = true;
    pcStatus.textContent = "Vergleich wird geladen…";

    try {
        // Im freien Modus wird das General-Radar erzwungen, damit die
        // Darstellung nicht davon abhaengt, ob zufaellig zwei Spieler
        // derselben Position gewaehlt wurden.
        const modeParam = pcState.position ? "" : "&mode=general";
        const url = `/api/player-compare?a=${a.player_id}&b=${b.player_id}`
                  + `&season_a=${pcState.a.season}&season_b=${pcState.b.season}`
                  + `&scope=${pcState.scope}`
                  + modeParam;
        const response = await fetch(url);
        const data = await response.json();

        if (!response.ok) {
            pcStatus.textContent = data.error || "Vergleich fehlgeschlagen.";
            pcCompareBtn.disabled = false;
            return;
        }

        pcState.lastComparison = data;
        pcRenderComparison(data);
        pcStatus.textContent = "Vergleich fertig";

    } catch (error) {
        pcStatus.textContent = "Vergleich nicht erreichbar.";
    } finally {
        pcCompareBtn.disabled = false;
    }
}


/* ---------- Ergebnis aufbauen ---------- */

function pcRenderComparison(data) {
    hide(pcEmpty);
    pcResult.innerHTML = "";
    show(pcResult);

    const comparison = data.comparison || {};

    pcResult.appendChild(pcBuildHeader(data.player_a, data.player_b));

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
        info.appendChild(make("span", "pc-head-name", player.name || "Unbekannt"));

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
            detail.push(PC_TEXT.scopeNoDataShort);
        } else if (player.minutes) {
            detail.push(`${player.minutes.toLocaleString("de")} Min`);
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
    box.appendChild(make("strong", "", "Keine Daten in dieser Datenbasis"));

    if (missingA && missingB) {
        box.appendChild(make("p", "", PC_TEXT.scopeNoDataBoth(scopeLabel)));
    } else {
        const missing = missingA ? playerA : playerB;
        box.appendChild(make("p", "", PC_TEXT.scopeNoData(
            missing.name || "Dieser Spieler", scopeLabel
        )));
    }

    return box;
}


function pcBuildModeNote(comparison) {
    const box = make("div", "pc-note");
    box.appendChild(make("strong", "", "Allgemeiner Vergleich"));

    const positions = [comparison.position_a, comparison.position_b]
        .filter(Boolean).length === 2;

    box.appendChild(make("p", "",
        positions
            ? "Die beiden Spieler haben unterschiedliche Positionen. Ein gemeinsames "
              + "Radar wäre irreführend, weil dieselbe Achse für beide etwas anderes "
              + "bedeutet. Verglichen werden deshalb allgemeine Kennzahlen."
            : "Für mindestens einen Spieler ist keine Position hinterlegt. "
              + "Verglichen werden deshalb allgemeine Kennzahlen."
    ));

    return box;
}

function pcBuildPoolNote(comparison, minMinutes) {
    const box = make("div", "pc-pool-note");

    if (!comparison.percentiles_available) {
        // Kein Warnbox-Design - nur ein dezenter Hinweis unter dem Radar
        box.classList.add("pc-pool-hint");
        box.appendChild(make("span", "pc-pool-hint-text", PC_TEXT.rawOnly));
        return box;
    }

    const pool = comparison.pool_a || comparison.pool_b;
    if (!pool) return box;

    const leagueText = comparison.percentile_pool_complete
        ? "der Top-5-Ligen"
        : `aus ${(pool.leagues || []).length} Ligen`;

    box.appendChild(make("strong", "", "Wie der Vergleichsrang zu lesen ist"));
    box.appendChild(make("p", "",
        `75/100 heißt: besser als 75 Prozent der Vergleichsgruppe. `
        + PC_TEXT.rankExplain(leagueText, pool.season_label, pool.min_minutes)
    ));

    if (!comparison.percentile_pool_complete) {
        box.classList.add("pc-pool-partial");
        box.appendChild(make("p", "pc-pool-warning",
            "Hinweis: es sind noch nicht alle fünf Ligen geladen. Der "
            + "Vergleichsrang bezieht sich nur auf die vorhandenen."
        ));
    }

    [["a", comparison.percentile_blocked_a], ["b", comparison.percentile_blocked_b]]
        .forEach(([slot, blocked]) => {
            if (blocked === "below_min_minutes") {
                box.appendChild(make("p", "pc-pool-warning",
                    `Spieler ${slot.toUpperCase()} hat weniger als ${minMinutes} Minuten `
                    + "gespielt. Für einen fairen Rang ist das zu wenig, die "
                    + "Werte selbst bleiben sichtbar."
                ));
            }
        });

    return box;
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
                                 "Positionsübergreifender Vergleich"));
        caption.appendChild(make("span", "pc-radar-caption-sub",
            `${playerA.position_label || "?"} gegen ${playerB.position_label || "?"} – `
            + "gezeigt werden nur Kennzahlen, die für beide Positionen dieselbe "
            + "Bedeutung haben."));
    } else {
        caption.appendChild(make("span", "pc-radar-caption-title",
            `Positionsvergleich · ${comparison.radar_profile_label || ""}`));
        caption.appendChild(make("span", "pc-radar-caption-sub",
            "Kennzahlen, die für diese Position aussagekräftig sind."));
    }
    wrap.appendChild(caption);

    if (metrics.length < 3) {
        // Unter drei Achsen ist ein Radar keine Form mehr, sondern eine Linie.
        wrap.appendChild(make("p", "pc-radar-fallback",
            "Für ein Radar liegen zu wenige vergleichbare Kennzahlen vor. "
            + "Die Einzelwerte stehen unten."));
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
    svg.setAttribute("aria-label",
        `Radardiagramm: ${playerA.name} gegen ${playerB.name}. `
        + "Die Einzelwerte stehen als Liste darunter.");

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
        const va = m.percentile_a !== null ? m.percentile_a
                 : (hasPercentiles ? null : m.value_a);
        const vb = m.percentile_b !== null ? m.percentile_b
                 : (hasPercentiles ? null : m.value_b);

        if (!hasPercentiles && va !== null && vb !== null) {
            // Relative Normierung: der hoehere der beiden Rohwerte = 85,
            // der niedrigere proportional dazu. Niemals 0 oder 100 simulieren.
            const max = Math.max(Math.abs(va), Math.abs(vb));
            if (max === 0) return { a: 50, b: 50 };
            const inverted = m.direction === "lower_better";
            const ra = inverted ? (1 - va / max) * 70 + 15 : (va / max) * 70 + 15;
            const rb = inverted ? (1 - vb / max) * 70 + 15 : (vb / max) * 70 + 15;
            return { a: ra, b: rb };
        }
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

    wrap.appendChild(make("p", "pc-radar-hint",
        "Weiter außen ist besser. Die Achsen zeigen den Rang in der "
        + "Vergleichsgruppe, nicht die Rohwerte."));

    return wrap;
}

function pcShortLabel(label) {
    // Achsenbeschriftungen muessen auf dem Smartphone lesbar bleiben.
    return (label || "")
        .replace(" pro 90", "/90")
        .replace("Gelungene ", "")
        .replace("Abgefangene Bälle", "Abgefangen")
        .replace("Schüsse aufs Tor", "Schüsse aufs Tor");
}


/* ---------- 16g. Detailvergleich ---------- */

function pcBuildMetricList(comparison, playerA, playerB) {
    const list = make("div", "pc-metrics");

    list.appendChild(make("h3", "pc-metrics-title", "Kennzahlen im Detail"));

    (comparison.metrics || []).forEach(metric => {
        const row = make("div", "pc-metric-row");

        const head = make("div", "pc-metric-head");
        head.appendChild(make("span", "pc-metric-label", metric.label));

        const kindLabel = {
            per90: "pro 90 Min",
            rate: "Quote",
            total: "Saisonwert",
            value: "Durchschnitt",
        }[metric.kind] || "";

        const badge = make("span", "pc-metric-kind", kindLabel);
        if (metric.direction === "lower_better") {
            badge.textContent = `${kindLabel} · niedriger ist besser`;
            badge.classList.add("pc-metric-inverted");
        }
        head.appendChild(badge);

        const info = document.createElement("button");
        info.type = "button";
        info.className = "pc-metric-info";
        info.setAttribute("aria-label", `Erklärung zu ${metric.label}`);
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
                ? PC_TEXT.rankUnavailable
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
    if (kind === "total") return value.toLocaleString("de");
    return String(value);
}


/* ---------- 16h. Zusammenfassung ---------- */

function pcBuildSummary(comparison, playerA, playerB) {
    const box = make("div", "pc-summary");
    box.appendChild(make("h3", "pc-summary-title", "Kurz zusammengefasst"));

    const metrics = (comparison.metrics || [])
        .filter(m => m.percentile_a !== null && m.percentile_b !== null);

    if (metrics.length === 0) {
        box.appendChild(make("p", "",
            "Solange die Vergleichsdaten fehlen, lässt sich kein belastbarer "
            + "Vorsprung benennen. Die Werte oben sprechen für sich."));
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

    const nameA = playerA.name || "Spieler A";
    const nameB = playerB.name || "Spieler B";

    const line = (player, list) => {
        if (list.length === 0) return null;
        const sorted = list
            .slice()
            .sort((x, y) => Math.abs(y.percentile_a - y.percentile_b)
                          - Math.abs(x.percentile_a - x.percentile_b))
            .slice(0, 3)
            .map(m => m.label);
        return `${player} liegt vorne bei: ${sorted.join(", ")}.`;
    };

    const textA = line(nameA, aheadA);
    const textB = line(nameB, aheadB);

    if (textA) box.appendChild(make("p", "pc-summary-a", textA));
    if (textB) box.appendChild(make("p", "pc-summary-b", textB));

    if (similar.length > 0) {
        box.appendChild(make("p", "pc-summary-similar",
            `Nahezu gleichauf bei: ${similar.slice(0, 4).map(m => m.label).join(", ")}.`));
    }

    if (!textA && !textB) {
        box.appendChild(make("p", "",
            "Über alle verglichenen Kennzahlen liegen beide dicht beieinander."));
    }

    box.appendChild(make("p", "pc-summary-note",
        `Als Vorsprung gilt hier ein Abstand von mindestens ${AHEAD} Perzentilpunkten. `
        + "Diese Zusammenfassung wird direkt aus den Zahlen oben berechnet."));

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

    // Startzustand der Positionsnavigation setzen, ohne dabei eine
    // Ruecksetzmeldung auszuloesen (es gibt noch keine Auswahl).
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

// Anzeigenamen fuer Liga-Codes und Positionen im Scatter-Frontend.
// Bewusst dieselben deutschen Bezeichnungen wie im Radar (POSITION_LABELS
// im Backend), damit beide Ansichten dieselbe Sprache sprechen.
const COMPARE_LEAGUE_LABELS_FRONTEND = {
    bl1: "Bundesliga", pl: "Premier League", pd: "LaLiga",
    sa: "Serie A", fl1: "Ligue 1",
};
const PC_POSITION_LABELS_FRONTEND = {
    Goalkeeper: "Torhüter", Defender: "Abwehr",
    Midfielder: "Mittelfeld", Attacker: "Angriff",
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
        pcScatterStatus.textContent = PC_TEXT.scatterError;
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
        pcScatterRunBtn.textContent = PC_TEXT.scatterLoading;
        pcScatterRunBtn.disabled = true;
        pcScatterRunBtn.setAttribute("aria-busy", "true");
        return;
    }

    pcScatterRunBtn.removeAttribute("aria-busy");
    pcScatterRunBtn.textContent = hasPlot ? PC_TEXT.scatterUpdate : PC_TEXT.scatterCreate;
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
        pcScatterStatus.textContent = PC_TEXT.scatterFiltersChanged;
        if (pcScatterChartWrap) pcScatterChartWrap.classList.add("pc-scatter-stale");
    }
    pcScatterUpdateButton();
}

/** Meldet die Datenlage, ohne zu zeichnen (Initialisierung). */
function pcScatterReportPoolState(data) {
    if (!data.used_leagues || data.used_leagues.length === 0) {
        pcScatterStatus.textContent = PC_TEXT.scatterPoolMissing;
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
        pcScatterScopeNote.textContent = PC_TEXT.scopeHint[scope] || "";
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
        season: pcState.season || "",
        min_minutes: pcState.scatter.minMinutes,
        leagues: pcState.scatter.leagues.join(","),
        scope: pcState.scatter.scope,
    });
    if (pcState.position) params.set("position", pcState.position);
    return `/api/player-scatter?${params.toString()}`;
}

async function pcScatterFetch() {
    return fetchJson(pcScatterBuildUrl());
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
    pcScatterStatus.textContent = PC_TEXT.scatterLoading;

    try {
        const data = await pcScatterFetch();
        if (requestId !== pcState.scatter.requestId) return;

        pcScatterRenderResult(data);
        pcState.scatter.hasPlot = (data.points || []).length > 0;
        pcState.scatter.dirty = false;
        if (pcScatterChartWrap) pcScatterChartWrap.classList.remove("pc-scatter-stale");
    } catch (error) {
        if (requestId !== pcState.scatter.requestId) return;
        pcScatterStatus.textContent = PC_TEXT.scatterError;
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
            pcScatterStatus.textContent = PC_TEXT.scatterPoolMissing;
            pcScatterSetEmptyText(PC_TEXT.scatterPoolMissing);
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
    svg.setAttribute("aria-label",
        `Streudiagramm: ${xMeta.label} gegen ${yMeta.label}, ${points.length} Spieler`);

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
            "aria-label": `${point.name}, ${point.team || ""}, `
                + `${xMeta.label} ${point.x}, ${yMeta.label} ${point.y}`,
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
    close.setAttribute("aria-label", "Detailkarte schließen");
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
        PC_POSITION_LABELS_FRONTEND[point.position] || point.position,
        point.age ? `${point.age} Jahre` : null,
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
        `${Number(point.minutes).toLocaleString("de-DE")} Einsatzminuten`));
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
    return Number(value).toLocaleString("de-DE", {
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
    return new Intl.DateTimeFormat("de-DE", {
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
    return new Intl.DateTimeFormat("de-DE", { timeZone: "UTC", weekday: "short" }).format(value);
}

/** Tag und Monat fuer einen Chip, z. B. "11. Aug". */
function liveChipDayLabel(isoDate) {
    const [year, month, day] = isoDate.split("-").map(Number);
    const value = new Date(Date.UTC(year, month - 1, day));
    return new Intl.DateTimeFormat("de-DE", { timeZone: "UTC", day: "numeric", month: "short" }).format(value);
}

/** Ueberschrift passend zum gewaehlten Tag - relativ nah an heute, sonst mit Datum. */
function liveHeadingText(isoDate) {
    const diff = liveDaysFromToday(isoDate);
    if (diff === 0)  return "Spiele heute";
    if (diff === -1) return "Spiele gestern";
    if (diff === 1)  return "Spiele morgen";
    return `Spiele am ${liveFormatDateLabel(isoDate)}`;
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

    row.appendChild(make("span", "live-team-name", name || "Unbekannt"));

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
        meta.appendChild(make("span", "live-badge", "LIVE"));

        const minute = liveMinuteText(match);
        if (minute) meta.appendChild(make("span", "live-minute", minute));
        else meta.appendChild(make("span", "live-meta-note", match.status_label));

        return meta;
    }

    if (match.phase === "paused") {
        meta.appendChild(make("span", "live-badge", "LIVE"));
        meta.appendChild(make("span", "live-meta-note", match.status_label));
        return meta;
    }

    if (match.phase === "scheduled") {
        meta.appendChild(make("span", "live-kickoff", match.kickoff_time || match.status_label));
        return meta;
    }

    if (match.phase === "cancelled" || match.phase === "unknown") {
        meta.appendChild(make("span", "live-meta-note live-meta-warn", match.status_label));
        return meta;
    }

    // finished
    meta.appendChild(make("span", "live-meta-note", match.status_label));
    return meta;
}

/**
 * Eine Match-Karte.
 *
 * Bewusst KEIN <button>: in LIVE A gibt es noch kein Match Center, und
 * ein Knopf ohne Wirkung waere eine leere Zusage. Die fuer LIVE B
 * noetigen IDs (API-Football fixture id und Team-IDs) haengen aber
 * bereits als data-Attribute an der Karte - LIVE B braucht dann nur
 * noch einen Klick-Handler, keine neue Datenstruktur.
 */
function liveBuildMatchCard(match) {
    const card = make("article", "live-match");

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

    return card;
}

function liveBuildGroup(group) {
    const section = make("section", "live-group");

    const head = make("div", "live-group-head");
    if (group.league_logo) head.appendChild(crest(group.league_logo, "live-group-logo"));
    head.appendChild(make("h3", "live-group-name", group.league_name || "Wettbewerb"));
    if (group.league_country) {
        head.appendChild(make("span", "live-group-country", group.league_country));
    }
    section.appendChild(head);

    const list = make("div", "live-match-list");
    group.matches.forEach(match => list.appendChild(liveBuildMatchCard(match)));
    section.appendChild(list);

    return section;
}

function liveRender(data) {
    liveGroups.innerHTML = "";

    if (!data.groups || data.groups.length === 0) {
        hide(liveGroups);
        show(liveEmpty);
        return;
    }

    data.groups.forEach(group => liveGroups.appendChild(liveBuildGroup(group)));

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
        liveSetStatus("Spiele werden geladen");
    }

    try {
        const data = await fetchJson(`/api/live-matches?date=${encodeURIComponent(isoDate)}`);

        // Eine zwischenzeitliche Tagesnavigation hat Vorrang.
        if (token !== liveState.requestToken) return;

        liveRender(data);

        if (liveHeading) liveHeading.textContent = liveHeadingText(isoDate);
        if (liveDateLabel) liveDateLabel.textContent = liveFormatDateLabel(isoDate);

        if (data.match_count === 0) {
            liveSetStatus("Keine Spiele an diesem Tag");
        } else if (data.live_count > 0) {
            liveSetStatus(
                `${data.match_count} Spiele, davon ${data.live_count} live`
            );
        } else {
            liveSetStatus(`${data.match_count} Spiele`);
        }

        // Der Server konnte die Quelle nicht erreichen und liefert den
        // letzten bekannten Stand. Das gehoert sichtbar gemacht.
        if (data.stale) {
            liveSetStatus(
                `${data.match_count} Spiele - letzter bekannter Stand, gerade nicht aktualisierbar`
            );
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
            const message = error.message || "Live-Daten sind derzeit nicht verfügbar";

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

        chip.appendChild(make("span", "live-date-chip-top", isToday ? "Heute" : liveWeekdayShort(chipDate)));
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
 * Alle vier Bedingungen muessen gleichzeitig gelten. Faellt eine weg,
 * ist der naechste Aufruf hier false und der Timer wird nicht erneuert.
 */
function liveShouldAutoRefresh(data) {
    return state.activeArea === "live" &&
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
 * Tab wird unsichtbar: Timer pausieren, kein Grund fuer Requests, die
 * niemand sieht. Tab wird wieder sichtbar: einmal leise nachladen und
 * Auto-Refresh anhand der frischen Antwort neu bewerten.
 */
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
        liveStopAutoRefresh();
        return;
    }

    if (state.activeArea === "live" && liveState.ready && !liveState.loading) {
        liveLoad({ background: true });
    }
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


/* ---------- 17. START ---------- */

async function init() {
    // Bereichszustand einmalig setzen, damit versteckte Bereiche von Anfang an
    // inert sind und beide Navigationen dieselbe Markierung zeigen.
    setActiveArea(state.activeArea);

    await loadSeasons();
    await loadCompetitions();
}

init();
