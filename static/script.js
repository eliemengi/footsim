const matchList = document.getElementById("match-list");
const simulateBtn = document.getElementById("simulate-btn");
const statusBox = document.getElementById("status");
const emptyState = document.getElementById("empty-state");
const resultBox = document.getElementById("result");

let matches = [];
let selectedMatchId = null;

async function loadMatches() {
    statusBox.textContent = "Lade Spiele...";

    const response = await fetch("/api/matches");
    matches = await response.json();

    matchList.innerHTML = "";

    matches.forEach((match, index) => {
        const button = document.createElement("button");
        button.className = "match-option";
        button.textContent = match.label;

        if (index === 0) {
            button.classList.add("active");
            selectedMatchId = match.id;
        }

        button.addEventListener("click", () => {
            selectedMatchId = match.id;
            document.querySelectorAll(".match-option").forEach(item => item.classList.remove("active"));
            button.classList.add("active");
        });

        matchList.appendChild(button);
    });

    statusBox.textContent = "Bereit";
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
    document.getElementById("best-score-count").textContent = `${data.top_scores[0].count} von ${document.getElementById("simulations").value} Simulationen`;

    renderProbabilityBars(data);
    renderTopScores(data);

    emptyState.classList.add("hidden");
    resultBox.classList.remove("hidden");
}

async function simulateMatch() {
    if (!selectedMatchId) {
        statusBox.textContent = "Bitte zuerst ein Spiel wählen";
        return;
    }

    const simulations = Number(document.getElementById("simulations").value);
    const useSeed = document.getElementById("use-seed").checked;

    statusBox.textContent = "Simulation läuft...";
    simulateBtn.disabled = true;

    try {
        const response = await fetch("/api/simulate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                match_id: selectedMatchId,
                simulations: simulations,
                use_seed: useSeed
            })
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
loadMatches();