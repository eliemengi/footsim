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
    11. Torjaeger
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
const roundSection      = el("round-section");
const roundList         = el("round-list");
const legModeSection    = el("leg-mode-section");
const legModeList       = el("leg-mode-list");
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

const state = {
    seasons: [],
    season: null,          // null bedeutet laufende Saison
    seasonLabel: "",

    competitions: [],
    competitionCode: null,
    competitionType: null,
    competitionName: null,

    matchday: null,
    matches: [],
    selectedMatch: null,
    selectedMatchId: null,

    clRound: null,
    clLegMode: null,

    activeTab: "table",
    tableType: "TOTAL",

    compareMode: "domestic",
    comparePhase: "all",
    compareSelection: [],
};

const PHASE_TEXTS = {
    all:      "Komplett wertet Ligaphase und K o Phase zusammen aus.",
    league:   "Nur die Ligaphase. Hier hat noch niemand eine Runde ueberstanden, deshalb entfallen die Turnierkennzahlen.",
    knockout: "Nur die K o Phase. Vereine, die die Ligaphase nicht ueberstanden haben, tauchen hier nicht auf.",
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

/** Haengt die gewaehlte Saison an eine URL an. */
function withSeason(url) {
    if (state.season === null) return url;
    return url + (url.includes("?") ? "&" : "?") + `season=${state.season}`;
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

    resetSimulationView();
    resetCompareView();

    setStatus(`Saison ${season.label} gewaehlt`);

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

    matchList.innerHTML = "";
    matchdayList.innerHTML = "";
    roundList.innerHTML = "";
    legModeList.innerHTML = "";

    hide(matchdaySection);
    hide(roundSection);
    hide(legModeSection);
    hide(tabBar);
    hide(tabTable);
    hide(tabScorers);
    hide(tabFixtures);
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
    compareStatus.textContent = "Mindestens zwei Ligen auswaehlen";
    compareResult.innerHTML = "";
    hide(compareResult);
    show(compareEmpty);

    compareLeagueList.querySelectorAll(".compare-league-option").forEach(node => {
        node.classList.remove("selected");
        const check = node.querySelector(".compare-check");
        if (check) check.textContent = "";
    });
}


/* ---------- 4. MODUS UMSCHALTER ---------- */

document.querySelectorAll(".mode-btn").forEach(button => {
    button.addEventListener("click", () => {
        clearActive(".mode-btn");
        button.classList.add("active");

        if (button.dataset.mode === "simulation") {
            show(el("mode-simulation"));
            hide(el("mode-compare"));
        } else {
            hide(el("mode-simulation"));
            show(el("mode-compare"));
        }
    });
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
    state.clRound = null;
    state.clLegMode = null;

    matchList.innerHTML = "";
    matchdayList.innerHTML = "";
    roundList.innerHTML = "";
    legModeList.innerHTML = "";

    hide(leftEmptyState);
    hide(emptyState);
    hide(roundSection);
    hide(legModeSection);
    hide(matchdaySection);
    hide(simControls);
    hide(resultBox);
    show(simEmpty);
    show(fixturesEmpty);
    hide(knockoutSection);

    setStatus(`${competition.name} gewaehlt`);

    if (competition.type === "league") {
        showTabsFor("league");
        await loadMatchdays(competition.code);

        switchTab("table");
        loadStandings(competition.code);
        loadScorers(competition.code);
    } else {
        // Pokal: keine Tabelle und keine Torjaeger in diesem Ablauf
        showTabsFor("cup");
        switchTab("fixtures");

        if (competition.code === "cl") {
            renderClRounds();
            show(roundSection);
        }
    }
}


/** Blendet die Reiter ein, die zum Wettbewerbstyp passen. */
function showTabsFor(type) {
    show(tabBar);

    const tableBtn   = document.querySelector('.tab-btn[data-tab="table"]');
    const scorersBtn = document.querySelector('.tab-btn[data-tab="scorers"]');

    if (type === "league") {
        show(tableBtn);
        show(scorersBtn);
    } else {
        hide(tableBtn);
        hide(scorersBtn);
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


/* ---------- 7. CHAMPIONS LEAGUE RUNDEN ---------- */

function renderClRounds() {
    roundList.innerHTML = "";

    const rounds = [
        { id: "ro16", label: "Achtelfinale", sub: "Letzte sechzehn Teams" },
        { id: "qf",   label: "Viertelfinale", sub: "Letzte acht Teams" },
        { id: "sf",   label: "Halbfinale",    sub: "Letzte vier Teams" },
    ];

    rounds.forEach(round => {
        const button = make("button", "round-option");
        button.appendChild(make("div", "option-head", round.label));
        button.appendChild(make("div", "option-sub", round.sub));

        button.addEventListener("click", () => {
            clearActive(".round-option");
            button.classList.add("active");

            state.clRound = round.id;
            state.clLegMode = null;

            matchList.innerHTML = "";
            hide(simControls);
            show(fixturesEmpty);

            renderClLegModes();
            show(legModeSection);

            setStatus(`${round.label} gewaehlt`);
        });

        roundList.appendChild(button);
    });
}


function renderClLegModes() {
    legModeList.innerHTML = "";

    const modes = [
        { id: "first",  label: "Hinspiel",   sub: "Einzelspiel ohne K o Kontext" },
        { id: "second", label: "Rueckspiel", sub: "Mit Hinspielergebnis, Verlaengerung und Elfmeterschiessen" },
    ];

    modes.forEach(mode => {
        const button = make("button", "leg-mode-option");
        button.appendChild(make("div", "option-head", mode.label));
        button.appendChild(make("div", "option-sub", mode.sub));

        button.addEventListener("click", async () => {
            clearActive(".leg-mode-option");
            button.classList.add("active");

            state.clLegMode = mode.id;
            setStatus(`${mode.label} gewaehlt`);

            switchTab("fixtures");
            await loadMatches("cl", null, state.clRound);
        });

        legModeList.appendChild(button);
    });
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
    hide(tabSimulation);
    hide(emptyState);

    if (tabName === "table")      show(tabTable);
    if (tabName === "scorers")    show(tabScorers);
    if (tabName === "fixtures")   show(tabFixtures);
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
        : "Ausgewaehlte Runde";

    fixturesTitle.textContent = state.competitionName || "Spiele";

    try {
        const matches = await fetchJson(withSeason(url));
        state.matches = matches;

        if (!matches.length) {
            show(fixturesEmpty);
            fixturesEmpty.querySelector("h2").textContent = "Keine Spiele vorhanden";
            fixturesEmpty.querySelector("p").textContent = "Fuer diese Auswahl liegen keine Partien vor.";
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


async function loadStandings(competitionCode) {
    tableContent.innerHTML = "";
    tableContent.appendChild(make("div", "loading-hint", "Tabelle wird geladen"));

    try {
        const data = await fetchJson(
            withSeason(`/api/standings?competition=${competitionCode}&type=${state.tableType}`)
        );

        tableTitle.textContent = `${data.competition} ${data.season}/${String(data.season + 1).slice(2)}`;
        renderStandings(data.table);

    } catch (error) {
        tableContent.innerHTML = "";
        tableContent.appendChild(make("div", "loading-hint", `Tabelle nicht verfuegbar: ${error.message}`));
    }
}


function renderStandings(rows) {
    tableContent.innerHTML = "";

    if (!rows || !rows.length) {
        tableContent.appendChild(make("div", "loading-hint", "Noch keine Tabellendaten fuer diese Saison."));
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
    if (position <= 4) return "pos-cl";
    if (position <= 6) return "pos-el";
    if (position > teamCount - 3) return "pos-relegation";
    return "";
}


function buildLegend() {
    const legend = make("div", "table-legend");

    [
        { cls: "pos-cl",         text: "Champions League" },
        { cls: "pos-el",         text: "Europapokal" },
        { cls: "pos-relegation", text: "Abstiegszone" },
    ].forEach(item => {
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
    scorersContent.appendChild(make("div", "loading-hint", "Torjaeger werden geladen"));

    try {
        const data = await fetchJson(
            withSeason(`/api/scorers?competition=${competitionCode}&limit=20`)
        );

        scorersTitle.textContent = `Torjaeger ${data.competition}`;
        renderScorers(data.scorers);

    } catch (error) {
        scorersContent.innerHTML = "";
        scorersContent.appendChild(
            make("div", "loading-hint", `Torjaegerliste nicht verfuegbar: ${error.message}`)
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

        if (scorer.team_crest) row.appendChild(crest(scorer.team_crest, "scorer-crest"));

        const info = make("div", "scorer-info");
        info.appendChild(make("div", "scorer-name", scorer.player_name));
        info.appendChild(make("div", "scorer-team",
            scorer.played_matches
                ? `${scorer.team_name} · ${scorer.played_matches} Spiele`
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
        setStatus("Bitte zuerst eine Partie auswaehlen", true);
        return;
    }

    const payload = {
        competition: state.competitionCode,
        simulations: parseInt(el("simulations").value, 10) || 5000,
        use_seed: el("use-seed").checked,
    };

    if (state.competitionType === "league") {
        payload.home_team = state.selectedMatch.home_team;
        payload.away_team = state.selectedMatch.away_team;
    } else {
        payload.match_id = state.selectedMatchId;
        payload.leg_mode = state.clLegMode || "first";
    }

    simulateBtn.disabled = true;
    simulateBtn.textContent = "Wird berechnet";
    setStatus("Simulation laeuft");

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
            title: "Verlaengerung und Elfmeter",
            rows: [
                ["Verlaengerung", `${data.extra_time_probability} Prozent`],
                ["Elfmeterschiessen", `${data.penalties_probability} Prozent`],
            ],
        },
        {
            title: "Entscheidung im Elfmeterschiessen",
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
        aggregate.appendChild(make("p", null, "Haeufigste Gesamtergebnisse"));

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
                "Waehle zwei bis fuenf Ligen. Alle Werte stammen aus den bereits gespielten Partien der Saison.";
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
        ? "Mindestens zwei Ligen auswaehlen"
        : `${count} Ligen ausgewaehlt`;
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
 * Balkenbreite fuer eine Kennzahl bestimmen.
 * Bezugsgroesse ist der groesste Betrag in der Zeile, damit die Balken
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
 * Kartenansicht der Kennzahlen fuer schmale Bildschirme.
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


/** Baut eine Kennzahlentabelle fuer breite Bildschirme. */
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


/* ---------- 15. START ---------- */

async function init() {
    await loadSeasons();
    await loadCompetitions();
}

init();
