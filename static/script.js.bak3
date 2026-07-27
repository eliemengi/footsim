/* ============================================================
   FootSim - Frontend
   Vanilla JavaScript, keine Abhaengigkeiten.

   Aufbau:
     1. Elemente und Zustand
     2. Hilfsfunktionen
     3. Modus Umschalter
     4. Wettbewerbe
     5. Spieltage
     6. Champions League Runden
     7. Spiele
     8. Tabs
     9. Tabelle
    10. Torjaeger
    11. Simulation
    12. Ligenvergleich
    13. Start
   ============================================================ */


/* ---------- 1. ELEMENTE UND ZUSTAND ---------- */

const el = (id) => document.getElementById(id);

const competitionList   = el("competition-list");
const competitionInfo   = el("competition-info");
const roundSection      = el("round-section");
const roundList         = el("round-list");
const legModeSection    = el("leg-mode-section");
const legModeList       = el("leg-mode-list");
const matchdaySection   = el("matchday-section");
const matchdayList      = el("matchday-list");
const matchSection      = el("match-section");
const matchStepLabel    = el("match-step-label");
const matchList         = el("match-list");
const simulateBtn       = el("simulate-btn");
const statusBox         = el("status");
const leftEmptyState    = el("left-empty-state");

const tabBar            = el("tab-bar");
const emptyState        = el("empty-state");
const tabTable          = el("tab-table");
const tabScorers        = el("tab-scorers");
const tabSimulation     = el("tab-simulation");

const tableTitle        = el("table-title");
const tableContent      = el("table-content");
const scorersTitle      = el("scorers-title");
const scorersContent    = el("scorers-content");

const simEmpty          = el("sim-empty");
const resultBox         = el("result");
const knockoutSection   = el("knockout-section");
const knockoutContent   = el("knockout-content");

const compareLeagueList = el("compare-league-list");
const compareBtn        = el("compare-btn");
const compareStatus     = el("compare-status");
const compareEmpty      = el("compare-empty");
const compareResult     = el("compare-result");

const state = {
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
    compareSelection: [],
};


/* ---------- 2. HILFSFUNKTIONEN ---------- */

function setStatus(text, isError = false) {
    statusBox.textContent = text;
    statusBox.classList.toggle("error", isError);
}

function show(node)  { if (node) node.classList.remove("hidden"); }
function hide(node)  { if (node) node.classList.add("hidden"); }

function clearActive(selector) {
    document.querySelectorAll(selector).forEach(n => n.classList.remove("active"));
}

/**
 * Baut ein Element und setzt Text sicher ueber textContent.
 * Verhindert, dass Vereinsnamen mit Sonderzeichen als HTML interpretiert werden.
 */
function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
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

function formatValue(value, unit) {
    if (value === null || value === undefined) return "-";
    return `${value}${unit || ""}`;
}


/* ---------- 3. MODUS UMSCHALTER ---------- */

document.querySelectorAll(".mode-btn").forEach(button => {
    button.addEventListener("click", () => {
        const mode = button.dataset.mode;

        clearActive(".mode-btn");
        button.classList.add("active");

        if (mode === "simulation") {
            show(el("mode-simulation"));
            hide(el("mode-compare"));
        } else {
            hide(el("mode-simulation"));
            show(el("mode-compare"));
        }
    });
});


/* ---------- 4. WETTBEWERBE ---------- */

async function loadCompetitions() {
    try {
        const competitions = await fetchJson("/api/competitions");
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

        const icon = make("img", "competition-icon");
        icon.src = competition.emblem;
        icon.alt = "";
        icon.loading = "lazy";
        icon.onerror = () => { icon.style.visibility = "hidden"; };

        const textWrap = make("div");
        textWrap.appendChild(make("div", "competition-name", competition.name));
        textWrap.appendChild(make("div", "competition-sub", competition.subtitle));

        left.appendChild(icon);
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

    // Zustand zuruecksetzen
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
    hide(competitionInfo);
    hide(matchSection);
    hide(roundSection);
    hide(legModeSection);
    hide(matchdaySection);
    hide(resultBox);
    show(simEmpty);
    hide(knockoutSection);

    setStatus(`${competition.name} gewaehlt`);

    if (competition.type === "league") {
        show(tabBar);
        hide(emptyState);

        await loadMatchdays(competition.code);

        // Tabelle und Torjaeger sofort laden, das ist der Kern von Variante C
        switchTab("table");
        loadStandings(competition.code);
        loadScorers(competition.code);
    } else {
        // Pokalwettbewerb: keine Tabelle, direkt zur Simulation
        hide(tabBar);
        hide(emptyState);
        switchTab("simulation");

        if (competition.code === "cl") {
            renderClRounds();
            show(roundSection);
        }
    }
}


/* ---------- 5. SPIELTAGE ---------- */

async function loadMatchdays(competitionCode) {
    matchdayList.innerHTML = "";
    show(matchdaySection);

    try {
        const matchdays = await fetchJson(`/api/matchdays?competition=${competitionCode}`);

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

    matchStepLabel.textContent = "Schritt 3";
    setStatus(`Spieltag ${matchday} wird geladen`);

    await loadMatches(competitionCode, matchday);
}


/* ---------- 6. CHAMPIONS LEAGUE RUNDEN ---------- */

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

            hide(matchSection);
            matchList.innerHTML = "";

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
            matchStepLabel.textContent = "Schritt 4";

            setStatus(`${mode.label} gewaehlt`);
            await loadMatches("cl", null, state.clRound);
        });

        legModeList.appendChild(button);
    });
}


/* ---------- 7. SPIELE ---------- */

async function loadMatches(competitionCode, matchday = null, round = null) {
    matchList.innerHTML = "";
    show(matchSection);

    let url = `/api/matches?competition=${competitionCode}`;
    if (matchday !== null) url += `&matchday=${matchday}`;
    if (round !== null)    url += `&round=${round}`;

    try {
        const matches = await fetchJson(url);
        state.matches = matches;

        if (!matches.length) {
            matchList.appendChild(make("div", "loading-hint", "Fuer diese Auswahl liegen keine Spiele vor."));
            setStatus("Keine Spiele gefunden");
            return;
        }

        matches.forEach(match => matchList.appendChild(buildMatchCard(match)));
        setStatus(`${matches.length} Spiele geladen`);

    } catch (error) {
        matchList.appendChild(make("div", "loading-hint", error.message));
        setStatus(error.message, true);
    }
}


function buildMatchCard(match) {
    const button = make("button", "match-option");
    const wrap = make("div", "match-card-clean");

    wrap.appendChild(buildTeamRow(match.home_team, match.home_crest, match.home_id));
    wrap.appendChild(make("div", "match-vs-clean", "gegen"));
    wrap.appendChild(buildTeamRow(match.away_team, match.away_crest, match.away_id));

    // Bereits gespielt? Ergebnis anzeigen
    if (match.status === "FINISHED" && match.home_score !== null && match.home_score !== undefined) {
        wrap.appendChild(make("div", "option-sub", `Endstand ${match.home_score}:${match.away_score}`));
    }

    button.appendChild(wrap);

    button.addEventListener("click", () => {
        clearActive(".match-option");
        button.classList.add("active");

        state.selectedMatch = match;
        state.selectedMatchId = match.id;

        setStatus(`${match.home_team} gegen ${match.away_team}`);
    });

    return button;
}


function buildTeamRow(teamName, crestUrl, teamId) {
    const row = make("div", "match-team-side");

    const url = crestUrl || (teamId ? `https://crests.football-data.org/${teamId}.png` : null);

    if (url) {
        const logo = make("img", "team-logo-clean");
        logo.src = url;
        logo.alt = "";
        logo.loading = "lazy";
        logo.onerror = () => { logo.style.visibility = "hidden"; };
        row.appendChild(logo);
    }

    row.appendChild(make("div", "team-name-clean", teamName));
    return row;
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
    hide(tabSimulation);
    hide(emptyState);

    if (tabName === "table")      show(tabTable);
    if (tabName === "scorers")    show(tabScorers);
    if (tabName === "simulation") show(tabSimulation);
}


/* ---------- 9. TABELLE ---------- */

document.querySelectorAll(".type-btn").forEach(button => {
    button.addEventListener("click", () => {
        clearActive(".type-btn");
        button.classList.add("active");

        state.tableType = button.dataset.type;

        if (state.competitionCode) {
            loadStandings(state.competitionCode);
        }
    });
});


async function loadStandings(competitionCode) {
    tableContent.innerHTML = "";
    tableContent.appendChild(make("div", "loading-hint", "Tabelle wird geladen"));

    try {
        const data = await fetchJson(
            `/api/standings?competition=${competitionCode}&type=${state.tableType}`
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

    // Kopfzeile
    const thead = make("thead");
    const headRow = make("tr");

    const columns = [
        { label: "#",  cls: "col-pos" },
        { label: "Team", cls: "col-team" },
        { label: "Sp", cls: "" },
        { label: "S",  cls: "" },
        { label: "U",  cls: "" },
        { label: "N",  cls: "" },
        { label: "Tore", cls: "" },
        { label: "Diff", cls: "" },
        { label: "Pkt", cls: "col-points" },
    ];

    columns.forEach(column => {
        const th = make("th", column.cls, column.label);
        headRow.appendChild(th);
    });

    thead.appendChild(headRow);
    table.appendChild(thead);

    // Datenzeilen
    const tbody = make("tbody");
    const teamCount = rows.length;

    rows.forEach(row => {
        const tr = make("tr");

        // Position mit Farbmarkierung
        const posCell = make("td", "col-pos");
        const marker = make("span", `pos-marker ${positionClass(row.position, teamCount)}`);
        posCell.appendChild(marker);
        posCell.appendChild(document.createTextNode(String(row.position)));
        tr.appendChild(posCell);

        // Team mit Wappen
        const teamCell = make("td", "col-team");
        const teamWrap = make("div", "team-cell");

        if (row.crest) {
            const crest = make("img");
            crest.src = row.crest;
            crest.alt = "";
            crest.loading = "lazy";
            crest.onerror = () => { crest.style.visibility = "hidden"; };
            teamWrap.appendChild(crest);
        }

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

    // Legende nur bei der Gesamttabelle
    if (state.tableType === "TOTAL") {
        tableContent.appendChild(buildLegend());
    }
}


function positionClass(position, teamCount) {
    if (position <= 4) return "pos-cl";
    if (position <= 6) return "pos-el";
    if (position > teamCount - 3) return "pos-relegation";
    return "";
}


function buildLegend() {
    const legend = make("div", "table-legend");

    const items = [
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


/* ---------- 10. TORJAEGER ---------- */

async function loadScorers(competitionCode) {
    scorersContent.innerHTML = "";
    scorersContent.appendChild(make("div", "loading-hint", "Torjaeger werden geladen"));

    try {
        const data = await fetchJson(`/api/scorers?competition=${competitionCode}&limit=20`);

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

        if (scorer.team_crest) {
            const crest = make("img", "scorer-crest");
            crest.src = scorer.team_crest;
            crest.alt = "";
            crest.loading = "lazy";
            crest.onerror = () => { crest.style.visibility = "hidden"; };
            row.appendChild(crest);
        }

        const info = make("div", "scorer-info");
        info.appendChild(make("div", "scorer-name", scorer.player_name));

        const teamLine = scorer.played_matches
            ? `${scorer.team_name} · ${scorer.played_matches} Spiele`
            : scorer.team_name;
        info.appendChild(make("div", "scorer-team", teamLine));
        row.appendChild(info);

        const stats = make("div", "scorer-stats");
        stats.appendChild(buildStat(scorer.goals, "Tore"));

        // Assists sind nicht in jedem Wettbewerb gefuellt
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


/* ---------- 11. SIMULATION ---------- */

simulateBtn.addEventListener("click", runSimulation);


async function runSimulation() {
    if (!state.selectedMatch) {
        setStatus("Bitte zuerst ein Spiel auswaehlen", true);
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

    // Haeufigster Ausgang
    const outcomes = [
        { label: `Sieg ${data.home_team}`, value: data.home_win_probability },
        { label: "Unentschieden",          value: data.draw_probability },
        { label: `Sieg ${data.away_team}`, value: data.away_win_probability },
    ];

    const top = outcomes.reduce((best, current) => current.value > best.value ? current : best);

    el("top-pick-name").textContent = top.label;
    el("top-pick-value").textContent = `${top.value} Prozent`;

    // Erwartete Tore
    el("xg-home-team").textContent = data.home_team;
    el("xg-away-team").textContent = data.away_team;
    el("xg-home").textContent = data.expected_home_goals;
    el("xg-away").textContent = data.expected_away_goals;

    // Haeufigstes Ergebnis
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
        textWrap.appendChild(make("div", "score-sub", `${((entry.count / total) * 100).toFixed(1)} Prozent der Faelle`));
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

    const cards = [
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
    ];

    cards.forEach(card => {
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


/* ---------- 12. LIGENVERGLEICH ---------- */

function renderCompareLeagues(leagues) {
    compareLeagueList.innerHTML = "";

    leagues.forEach(league => {
        const button = make("button", "compare-league-option");
        button.dataset.code = league.code;

        button.appendChild(make("span", "compare-check", ""));

        const icon = make("img");
        icon.src = league.emblem;
        icon.alt = "";
        icon.loading = "lazy";
        icon.onerror = () => { icon.style.visibility = "hidden"; };
        button.appendChild(icon);

        const textWrap = make("div");
        textWrap.appendChild(make("div", "compare-league-name", league.name));
        textWrap.appendChild(make("div", "compare-league-country", league.country));
        button.appendChild(textWrap);

        button.addEventListener("click", () => toggleCompareLeague(league.code, button));

        compareLeagueList.appendChild(button);
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
        button.querySelector(".compare-check").textContent = String(state.compareSelection.length);
    }

    // Nummerierung neu vergeben
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

    try {
        const data = await fetchJson(`/api/compare?leagues=${state.compareSelection.join(",")}`);

        renderComparison(data);
        compareStatus.textContent = "Vergleich fertig";

    } catch (error) {
        compareStatus.textContent = error.message;
    } finally {
        compareBtn.disabled = false;
        compareBtn.textContent = "Vergleichen";
    }
}


function renderComparison(data) {
    hide(compareEmpty);
    show(compareResult);
    compareResult.innerHTML = "";

    // Kopfzeile mit den Ligen
    const header = make("div", "compare-header");

    data.leagues.forEach(league => {
        const card = make("div", "compare-header-card");

        if (league.emblem) {
            const icon = make("img");
            icon.src = league.emblem;
            icon.alt = "";
            icon.onerror = () => { icon.style.visibility = "hidden"; };
            card.appendChild(icon);
        }

        card.appendChild(make("div", "compare-header-name", league.name));

        if (league.leader) {
            card.appendChild(make(
                "div",
                "compare-header-leader",
                `Erster: ${league.leader.team_name}\n${league.leader.points} Punkte aus ${league.leader.played} Spielen`
            ));
        }

        header.appendChild(card);
    });

    compareResult.appendChild(header);

    // Abschnitte mit Kennzahlen
    data.sections.forEach(section => {
        if (!section.rows || !section.rows.length) return;

        const wrap = make("div", "compare-section");
        wrap.appendChild(make("h3", "compare-section-title", section.title));

        const table = make("table", "compare-table");

        const thead = make("thead");
        const headRow = make("tr");
        headRow.appendChild(make("th", null, "Kennzahl"));
        data.leagues.forEach(league => headRow.appendChild(make("th", null, league.name)));
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = make("tbody");

        section.rows.forEach(row => {
            const tr = make("tr");
            tr.appendChild(make("td", null, row.label));

            data.leagues.forEach(league => {
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
        wrap.appendChild(table);
        compareResult.appendChild(wrap);
    });
}


/* ---------- 13. START ---------- */

loadCompetitions();
