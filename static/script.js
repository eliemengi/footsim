const competitionCards = document.querySelectorAll(".competition-card");
const competitionInfo = document.getElementById("competition-info");
const legModeSection = document.getElementById("leg-mode-section");
const legModeList = document.getElementById("leg-mode-list");
const matchdaySection = document.getElementById("matchday-section");
const matchdayList = document.getElementById("matchday-list");
const matchSection = document.getElementById("match-section");
const matchSectionTitle = document.getElementById("match-section-title");
const matchStepLabel = document.getElementById("match-step-label");
const matchList = document.getElementById("match-list");
const simulateBtn = document.getElementById("simulate-btn");
const statusBox = document.getElementById("status");
const emptyState = document.getElementById("empty-state");
const resultBox = document.getElementById("result");
const leftEmptyState = document.getElementById("left-empty-state");
const knockoutSection = document.getElementById("knockout-section");
const knockoutContent = document.getElementById("knockout-content");

let matches = [];
let selectedCompetitionCode = null;
let selectedMatchId = null;
let selectedMatchday = null;
let selectedMatch = null;
let selectedClLegMode = null;

const TEAM_CRESTS = {
    "Galatasaray": "https://crests.football-data.org/610.png",
    "Liverpool": "https://crests.football-data.org/64.png",
    "Newcastle": "https://crests.football-data.org/67.png",
    "Barcelona": "https://crests.football-data.org/81.png",
    "Atletico": "https://crests.football-data.org/78.png",
    "Tottenham": "https://crests.football-data.org/73.png",
    "Atalanta": "https://crests.football-data.org/102.png",
    "Bayern": "https://crests.football-data.org/5.png",
    "Leverkusen": "https://crests.football-data.org/3.png",
    "Arsenal": "https://crests.football-data.org/57.png",
    "Real Madrid": "https://crests.football-data.org/86.png",
    "Man City": "https://crests.football-data.org/65.png",
    "Bodo Glimt": "https://crests.football-data.org/754.png",
    "Sporting": "https://crests.football-data.org/498.png",
    "Paris": "https://crests.football-data.org/524.png",
    "Chelsea": "https://crests.football-data.org/61.png"
};


function resetSelectionState() {
    matches = [];
    selectedMatchId = null;
    selectedMatchday = null;
    selectedMatch = null;
    selectedClLegMode = null;
    matchList.innerHTML = "";
    matchdayList.innerHTML = "";
    legModeList.innerHTML = "";
    knockoutSection.classList.add("hidden");
    knockoutContent.innerHTML = "";
}


function showComingSoonBox(title, text) {
    competitionInfo.innerHTML = `
        <div class="coming-soon-box">
            <h3>${title}</h3>
            <p>${text}</p>
        </div>
    `;
    competitionInfo.classList.remove("hidden");
}


function getLeagueTitle(competitionCode, matchday) {
    if (competitionCode === "bl1") {
        return `Bundesliga Spieltag ${matchday}`;
    }

    if (competitionCode === "pl") {
        return `Premier League Matchday ${matchday}`;
    }

    if (competitionCode === "pd") {
        return `LaLiga Matchday ${matchday}`;
    }

    if (competitionCode === "sa") {
        return `Serie A Matchday ${matchday}`;
    }

    return `Spieltag ${matchday}`;
}


function getTeamLogoUrl(match, side) {
    if (side === "home") {
        if (match.home_id) {
            return `https://crests.football-data.org/${match.home_id}.png`;
        }
        return TEAM_CRESTS[match.home_team] || "";
    }

    if (side === "away") {
        if (match.away_id) {
            return `https://crests.football-data.org/${match.away_id}.png`;
        }
        return TEAM_CRESTS[match.away_team] || "";
    }

    return "";
}


function renderClLegModes() {
    legModeList.innerHTML = "";

    const modes = [
        {
            id: "first",
            label: "Hinspiel",
            sub: "Normale Einzelspiel Simulation ohne K o Kontext"
        },
        {
            id: "second",
            label: "Rückspiel",
            sub: "Mit echtem Hinspiel, Weiterkommen, Verlängerung und Elfmeterschießen"
        }
    ];

    modes.forEach((mode) => {
        const button = document.createElement("button");
        button.className = "leg-mode-option";

        button.innerHTML = `
            <div class="option-head">${mode.label}</div>
            <div class="option-sub">${mode.sub}</div>
        `;

        button.addEventListener("click", async () => {
            selectedClLegMode = mode.id;

            document.querySelectorAll(".leg-mode-option").forEach(item => item.classList.remove("active"));
            button.classList.add("active");

            matchSection.classList.remove("hidden");
            matchStepLabel.textContent = "Step 3";

            if (mode.id === "first") {
                matchSectionTitle.textContent = "Champions League Hinspiel";
            } else {
                matchSectionTitle.textContent = "Champions League Rückspiel";
            }

            await loadMatches("cl");
        });

        legModeList.appendChild(button);
    });
}


competitionCards.forEach(card => {
    card.addEventListener("click", async () => {
        competitionCards.forEach(c => c.classList.remove("active"));
        card.classList.add("active");

        const competition = card.dataset.competition;
        selectedCompetitionCode = competition;

        resetSelectionState();

        resultBox.classList.add("hidden");
        emptyState.classList.remove("hidden");
        leftEmptyState.classList.add("hidden");

        competitionInfo.classList.add("hidden");
        legModeSection.classList.add("hidden");
        matchdaySection.classList.add("hidden");
        matchSection.classList.add("hidden");

        if (competition === "cl") {
            legModeSection.classList.remove("hidden");
            renderClLegModes();
            statusBox.textContent = "Wähle Hinspiel oder Rückspiel";
            return;
        }

        if (competition === "bl1") {
            matchdaySection.classList.remove("hidden");
            matchStepLabel.textContent = "Step 3";
            await loadMatchdays("bl1");
            return;
        }

        if (competition === "pl") {
            matchdaySection.classList.remove("hidden");
            matchStepLabel.textContent = "Step 3";
            await loadMatchdays("pl");
            return;
        }

        if (competition === "el") {
            showComingSoonBox(
                "Coming Soon",
                "Europa League UI wird als nächstes sauber eingebaut."
            );
            return;
        }

        if (competition === "pd") {
            matchdaySection.classList.remove("hidden");
            matchStepLabel.textContent = "Step 3";
            await loadMatchdays("pd");
            return;
        }

        if (competition === "sa") {
            matchdaySection.classList.remove("hidden");
            matchStepLabel.textContent = "Step 3";
            await loadMatchdays("sa");
            return;
        }

        showComingSoonBox(
            "Coming Soon",
            "Dieser Wettbewerb ist noch nicht verfügbar."
        );
    });
});


async function loadMatchdays(competitionCode) {
    statusBox.textContent = "Lade Spieltage...";

    try {
        const response = await fetch(`/api/matchdays?competition=${competitionCode}`);

        if (!response.ok) {
            throw new Error("Spieltage konnten nicht geladen werden");
        }

        const matchdays = await response.json();

        matchdayList.innerHTML = "";

        matchdays.forEach((item) => {
            const button = document.createElement("button");
            button.className = "matchday-option";
            button.textContent = item.label;

            if (!item.available) {
                button.disabled = true;
                button.classList.add("disabled");
            }

            button.addEventListener("click", async () => {
                if (!item.available) {
                    return;
                }

                selectedMatchday = item.matchday;

                document.querySelectorAll(".matchday-option").forEach(btn => btn.classList.remove("active"));
                button.classList.add("active");

                matchSection.classList.remove("hidden");
                matchSectionTitle.textContent = getLeagueTitle(competitionCode, item.matchday);

                await loadMatches(competitionCode, item.matchday);
            });

            matchdayList.appendChild(button);
        });

        statusBox.textContent = "Bereit";
    } catch (error) {
        statusBox.textContent = `Fehler: ${error.message}`;
    }
}


async function loadMatches(competitionCode, matchday = null) {
    statusBox.textContent = "Lade Spiele...";

    try {
        let url = `/api/matches?competition=${competitionCode}`;

        if (
            competitionCode === "bl1" ||
            competitionCode === "pl" ||
            competitionCode === "pd" ||
            competitionCode === "sa"
        ) {
            url += `&matchday=${matchday}`;
        }

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error("Spiele konnten nicht geladen werden");
        }

        matches = await response.json();

        if (competitionCode === "cl" && selectedClLegMode === "second") {
            matches = matches.map(match => ({
                ...match,
                home_team: match.away_team,
                away_team: match.home_team,
                home_id: match.away_id,
                away_id: match.home_id,
                label: `${match.away_team} vs ${match.home_team}`
            }));
        }

        matchList.innerHTML = "";
        selectedMatchId = null;
        selectedMatch = null;

        if (!matches || matches.length === 0) {
            statusBox.textContent = "Keine Spiele gefunden";
            return;
        }

        matches.forEach((match, index) => {
            const button = document.createElement("button");
            button.className = "match-option";

            const homeLogo = getTeamLogoUrl(match, "home");
            const awayLogo = getTeamLogoUrl(match, "away");

            button.innerHTML = `
                <div class="match-card-clean">
                    <div class="match-team-row">
                        <div class="match-team-side">
                            ${homeLogo ? `<img class="team-logo-clean" src="${homeLogo}" alt="${match.home_team} Logo">` : ""}
                            <span class="team-name-clean">${match.home_team}</span>
                        </div>
                    </div>

                    <div class="match-vs-clean">vs</div>

                    <div class="match-team-row">
                        <div class="match-team-side">
                            ${awayLogo ? `<img class="team-logo-clean" src="${awayLogo}" alt="${match.away_team} Logo">` : ""}
                            <span class="team-name-clean">${match.away_team}</span>
                        </div>
                    </div>
                </div>
            `;

            if (index === 0) {
                button.classList.add("active");
                selectedMatchId = match.id;
                selectedMatch = match;
            }

            button.addEventListener("click", () => {
                selectedMatchId = match.id;
                selectedMatch = match;

                document.querySelectorAll(".match-option").forEach(item => item.classList.remove("active"));
                button.classList.add("active");
            });

            matchList.appendChild(button);
        });

        matchSection.classList.remove("hidden");
        statusBox.textContent = "Bereit";
    } catch (error) {
        statusBox.textContent = `Fehler: ${error.message}`;
    }
}


function getTopPick(data) {
    const values = [
        { name: data.home_team, value: data.home_win_probability },
        { name: "Unentschieden", value: data.draw_probability },
        { name: data.away_team, value: data.away_win_probability }
    ];

    values.sort((a, b) => b.value - a.value);
    return values[0];
}


function renderProbabilityBars(data) {
    const container = document.getElementById("probability-bars");
    container.innerHTML = "";

    const rows = [
        { label: `${data.home_team} Sieg`, value: data.home_win_probability },
        { label: "Unentschieden", value: data.draw_probability },
        { label: `${data.away_team} Sieg`, value: data.away_win_probability }
    ];

    rows.forEach(row => {
        const block = document.createElement("div");
        block.className = "bar-block";

        block.innerHTML = `
            <div class="bar-header">
                <span>${row.label}</span>
                <span>${row.value.toFixed(2)} %</span>
            </div>
            <div class="bar-track">
                <div class="bar-fill" style="width: ${row.value}%"></div>
            </div>
        `;

        container.appendChild(block);
    });
}


function renderTopScores(data) {
    const container = document.getElementById("top-scores");
    container.innerHTML = "";

    data.top_scores.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "score-row";

        row.innerHTML = `
            <div class="score-left">
                <div class="rank-badge">${index + 1}</div>
                <div>
                    <div class="score-name">${item.score}</div>
                    <div class="score-sub">Scoreline</div>
                </div>
            </div>
            <div class="score-count">
                <div>${item.count}</div>
                <div class="score-count-label">Simulationen</div>
            </div>
        `;

        container.appendChild(row);
    });
}


function renderKnockoutSection(data) {
    if (!data.is_two_legged_tie) {
        knockoutSection.classList.add("hidden");
        knockoutContent.innerHTML = "";
        return;
    }

    const aggregateRows = (data.top_aggregate_scores || []).map((item, index) => `
        <div class="score-row">
            <div class="score-left">
                <div class="rank-badge">${index + 1}</div>
                <div>
                    <div class="score-name">${item.score}</div>
                    <div class="score-sub">Aggregate</div>
                </div>
            </div>
            <div class="score-count">
                <div>${item.count}</div>
                <div class="score-count-label">Simulationen</div>
            </div>
        </div>
    `).join("");

    knockoutContent.innerHTML = `
        <div class="knockout-grid">
            <div class="knockout-card">
                <p>Echtes Hinspiel</p>
                <strong class="knockout-value">${data.first_leg_score}</strong>
            </div>

            <div class="knockout-card">
                <p>Verlängerung Wahrscheinlichkeit</p>
                <strong class="knockout-value">${data.extra_time_probability.toFixed(2)} %</strong>
            </div>

            <div class="knockout-card">
                <p>Elfmeterschießen Wahrscheinlichkeit</p>
                <strong class="knockout-value">${data.penalties_probability.toFixed(2)} %</strong>
            </div>
        </div>

        <div class="knockout-columns">
            <div class="knockout-card">
                <p>Wer kommt weiter</p>

                <div class="knockout-row">
                    <span>${data.home_team}</span>
                    <strong>${data.qualification_home_probability.toFixed(2)} %</strong>
                </div>

                <div class="knockout-row">
                    <span>${data.away_team}</span>
                    <strong>${data.qualification_away_probability.toFixed(2)} %</strong>
                </div>
            </div>

            <div class="knockout-card">
                <p>Wer kommt in der Verlängerung weiter</p>

                <div class="knockout-row">
                    <span>${data.home_team}</span>
                    <strong>${data.home_qualifies_in_extra_time_probability.toFixed(2)} %</strong>
                </div>

                <div class="knockout-row">
                    <span>${data.away_team}</span>
                    <strong>${data.away_qualifies_in_extra_time_probability.toFixed(2)} %</strong>
                </div>
            </div>

            <div class="knockout-card">
                <p>Wer kommt im Elfmeterschießen weiter</p>

                <div class="knockout-row">
                    <span>${data.home_team}</span>
                    <strong>${data.home_qualifies_on_penalties_probability.toFixed(2)} %</strong>
                </div>

                <div class="knockout-row">
                    <span>${data.away_team}</span>
                    <strong>${data.away_qualifies_on_penalties_probability.toFixed(2)} %</strong>
                </div>
            </div>
        </div>

        <div class="knockout-card">
            <p>Top 5 Aggregate Ergebnisse</p>
            <div class="aggregate-list">
                ${aggregateRows}
            </div>
        </div>
    `;

    knockoutSection.classList.remove("hidden");
}


function renderResult(data) {
    const topPick = getTopPick(data);

    document.getElementById("match-title").textContent = `${data.home_team} vs ${data.away_team}`;
    document.getElementById("top-pick-name").textContent = topPick.name;
    document.getElementById("top-pick-value").textContent = `${topPick.value.toFixed(2)} %`;

    document.getElementById("xg-home-team").textContent = data.home_team;
    document.getElementById("xg-away-team").textContent = data.away_team;
    document.getElementById("xg-home").textContent = data.expected_home_goals.toFixed(2);
    document.getElementById("xg-away").textContent = data.expected_away_goals.toFixed(2);

    document.getElementById("best-score").textContent = data.top_scores[0].score;
    document.getElementById("best-score-count").textContent =
        `${data.top_scores[0].count} von ${document.getElementById("simulations").value} Simulationen`;

    renderProbabilityBars(data);
    renderTopScores(data);
    renderKnockoutSection(data);

    emptyState.classList.add("hidden");
    resultBox.classList.remove("hidden");
}


async function simulateMatch() {
    if (!selectedCompetitionCode) {
        statusBox.textContent = "Bitte zuerst Wettbewerb wählen";
        return;
    }

    if (!selectedMatchId || !selectedMatch) {
        statusBox.textContent = "Bitte zuerst Spiel wählen";
        return;
    }

    if (selectedCompetitionCode === "cl" && !selectedClLegMode) {
        statusBox.textContent = "Bitte zuerst Hinspiel oder Rückspiel wählen";
        return;
    }

    const simulations = Number(document.getElementById("simulations").value);
    const useSeed = document.getElementById("use-seed").checked;

    statusBox.textContent = "Simulation läuft...";
    simulateBtn.disabled = true;

    try {
        const payload = {
            competition: selectedCompetitionCode,
            match_id: selectedMatchId,
            simulations: simulations,
            use_seed: useSeed
        };

        if (selectedCompetitionCode === "cl") {
            payload.leg_mode = selectedClLegMode;
        }

        if (
            selectedCompetitionCode === "bl1" ||
            selectedCompetitionCode === "pl" ||
            selectedCompetitionCode === "pd" ||
            selectedCompetitionCode === "sa"
        ) {
            payload.home_team = selectedMatch.home_team;
            payload.away_team = selectedMatch.away_team;
            payload.matchday = selectedMatchday;
        }

        const response = await fetch("/api/simulate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Fehler bei der Simulation");
        }

        renderResult(data);
        statusBox.textContent = "Simulation abgeschlossen";
    } catch (error) {
        statusBox.textContent = `Fehler: ${error.message}`;
    } finally {
        simulateBtn.disabled = false;
    }
}


simulateBtn.addEventListener("click", simulateMatch);