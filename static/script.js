const competitionCards = document.querySelectorAll(".competition-card");
const competitionInfo = document.getElementById("competition-info");
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

let matches = [];
let selectedCompetitionCode = null;
let selectedMatchId = null;
let selectedMatchday = null;
let selectedMatch = null;


function resetSelectionState() {
    matches = [];
    selectedMatchId = null;
    selectedMatchday = null;
    selectedMatch = null;
    matchList.innerHTML = "";
    matchdayList.innerHTML = "";
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
        matchdaySection.classList.add("hidden");
        matchSection.classList.add("hidden");

        if (competition === "cl") {
            matchStepLabel.textContent = "Step 2";
            matchSectionTitle.textContent = "Champions League Spiele";
            matchSection.classList.remove("hidden");
            await loadMatches("cl");
            return;
        }

        if (competition === "bl1") {
            matchdaySection.classList.remove("hidden");
            matchStepLabel.textContent = "Step 3";
            await loadMatchdays();
            return;
        }

        if (competition === "pl") {
            showComingSoonBox(
                "Coming Soon",
                "Premier League wird bald freigeschaltet."
            );
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
            showComingSoonBox(
                "Coming Soon",
                "LaLiga wird bald freigeschaltet."
            );
            return;
        }

        if (competition === "sa") {
            showComingSoonBox(
                "Coming Soon",
                "Serie A wird bald freigeschaltet."
            );
            return;
        }

        showComingSoonBox(
            "Coming Soon",
            "Dieser Wettbewerb ist noch nicht verfügbar."
        );
    });
});


async function loadMatchdays() {
    statusBox.textContent = "Lade Spieltage...";

    try {
        const response = await fetch(`/api/matchdays?competition=bl1`);

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
                matchSectionTitle.textContent = `Bundesliga Spieltag ${item.matchday}`;
                await loadMatches("bl1", item.matchday);
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

        if (competitionCode === "bl1" && matchday !== null) {
            url += `&matchday=${matchday}`;
        }

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error("Spiele konnten nicht geladen werden");
        }

        matches = await response.json();

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
            button.textContent = match.label;

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

        if (selectedCompetitionCode === "bl1") {
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