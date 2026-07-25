/* ============================================================
   FootSim Tools - PDF Merge
   Vanilla JS, gleicher Aufbau wie static/script.js
   ============================================================ */

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const addBtn = document.getElementById("add-btn");
const optionsSection = document.getElementById("options-section");
const outputName = document.getElementById("output-name");
const reverseOrder = document.getElementById("reverse-order");
const mergeBtn = document.getElementById("merge-btn");
const clearBtn = document.getElementById("clear-btn");
const leftEmptyState = document.getElementById("left-empty-state");
const statusBox = document.getElementById("status");

const emptyState = document.getElementById("empty-state");
const fileView = document.getElementById("file-view");
const fileList = document.getElementById("file-list");
const summaryCount = document.getElementById("summary-count");
const summarySize = document.getElementById("summary-size");

const resultBox = document.getElementById("result-box");
const resultText = document.getElementById("result-text");
const downloadLink = document.getElementById("download-link");
const newMergeBtn = document.getElementById("new-merge-btn");

const ALLOWED_EXTENSIONS = ["pdf", "jpg", "jpeg", "png"];
const MAX_TOTAL_BYTES = 50 * 1024 * 1024;

let files = [];
let dragIndex = null;
let lastObjectUrl = null;


/* ===================== HILFSFUNKTIONEN ===================== */

function getExtension(name) {
    const parts = name.split(".");

    if (parts.length < 2) {
        return "";
    }

    return parts.pop().toLowerCase();
}


function isImage(name) {
    const extension = getExtension(name);
    return extension === "jpg" || extension === "jpeg" || extension === "png";
}


function formatSize(bytes) {
    if (bytes < 1024) {
        return `${bytes} B`;
    }

    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(0)} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


function getTotalBytes() {
    return files.reduce((sum, entry) => sum + entry.file.size, 0);
}


function setStatus(text) {
    statusBox.textContent = text;
}


/* ===================== DATEIEN VERWALTEN ===================== */

function addFiles(fileObjects) {
    let skippedType = 0;
    let skippedDuplicate = 0;
    let added = 0;

    for (const file of fileObjects) {
        if (!ALLOWED_EXTENSIONS.includes(getExtension(file.name))) {
            skippedType += 1;
            continue;
        }

        const isDuplicate = files.some(
            entry => entry.file.name === file.name && entry.file.size === file.size
        );

        if (isDuplicate) {
            skippedDuplicate += 1;
            continue;
        }

        files.push({
            file: file,
            previewUrl: isImage(file.name) ? URL.createObjectURL(file) : null
        });

        added += 1;
    }

    renderAll();

    const notes = [];

    if (added > 0) {
        notes.push(`${added} Datei${added === 1 ? "" : "en"} hinzugefügt`);
    }

    if (skippedType > 0) {
        notes.push(`${skippedType} übersprungen, falsches Format`);
    }

    if (skippedDuplicate > 0) {
        notes.push(`${skippedDuplicate} übersprungen, schon in der Liste`);
    }

    setStatus(notes.length > 0 ? notes.join(" · ") : "Keine passenden Dateien gefunden");
}


function removeFile(index) {
    const entry = files[index];

    if (entry && entry.previewUrl) {
        URL.revokeObjectURL(entry.previewUrl);
    }

    files.splice(index, 1);
    renderAll();
    setStatus("Datei entfernt");
}


function clearAll() {
    files.forEach(entry => {
        if (entry.previewUrl) {
            URL.revokeObjectURL(entry.previewUrl);
        }
    });

    files = [];
    renderAll();
    setStatus("Liste geleert");
}


function moveFile(fromIndex, toIndex) {
    if (toIndex < 0 || toIndex >= files.length) {
        return;
    }

    const [moved] = files.splice(fromIndex, 1);
    files.splice(toIndex, 0, moved);
    renderAll();
}


/* ===================== RENDERING ===================== */

function renderAll() {
    renderFileList();
    renderSummary();
    updateVisibility();
}


function renderFileList() {
    fileList.innerHTML = "";

    files.forEach((entry, index) => {
        const card = document.createElement("div");
        card.className = "file-card";
        card.draggable = true;
        card.dataset.index = index;

        const extension = getExtension(entry.file.name).toUpperCase();

        const thumbHtml = entry.previewUrl
            ? `<img class="file-thumb" src="${entry.previewUrl}" alt="">`
            : `<div class="file-icon">${extension}</div>`;

        card.innerHTML = `
            <div class="rank-badge">${index + 1}</div>
            ${thumbHtml}
            <div class="file-meta">
                <div class="file-name"></div>
                <div class="file-sub">${extension} · ${formatSize(entry.file.size)}</div>
            </div>
            <div class="file-actions">
                <button class="icon-btn up" title="Nach oben" ${index === 0 ? "disabled" : ""}>&#9650;</button>
                <button class="icon-btn down" title="Nach unten" ${index === files.length - 1 ? "disabled" : ""}>&#9660;</button>
                <button class="icon-btn remove" title="Entfernen">&#10005;</button>
            </div>
        `;

        // Dateiname per textContent, damit Sonderzeichen im Namen kein HTML werden
        card.querySelector(".file-name").textContent = entry.file.name;

        card.querySelector(".up").addEventListener("click", () => moveFile(index, index - 1));
        card.querySelector(".down").addEventListener("click", () => moveFile(index, index + 1));
        card.querySelector(".remove").addEventListener("click", () => removeFile(index));

        card.addEventListener("dragstart", () => {
            dragIndex = index;
            card.classList.add("dragging");
        });

        card.addEventListener("dragend", () => {
            dragIndex = null;
            card.classList.remove("dragging");
            document.querySelectorAll(".file-card").forEach(item => item.classList.remove("drop-target"));
        });

        card.addEventListener("dragover", (event) => {
            event.preventDefault();

            if (dragIndex !== null && dragIndex !== index) {
                card.classList.add("drop-target");
            }
        });

        card.addEventListener("dragleave", () => {
            card.classList.remove("drop-target");
        });

        card.addEventListener("drop", (event) => {
            event.preventDefault();
            event.stopPropagation();

            if (dragIndex !== null && dragIndex !== index) {
                moveFile(dragIndex, index);
            }
        });

        fileList.appendChild(card);
    });
}


function renderSummary() {
    const count = files.length;
    summaryCount.textContent = `${count} Datei${count === 1 ? "" : "en"}`;
    summarySize.textContent = formatSize(getTotalBytes());
}


function updateVisibility() {
    const hasFiles = files.length > 0;

    optionsSection.classList.toggle("hidden", !hasFiles);
    leftEmptyState.classList.toggle("hidden", hasFiles);

    // Ergebnisbox hat Vorrang vor der Liste
    const showingResult = !resultBox.classList.contains("hidden");

    emptyState.classList.toggle("hidden", hasFiles || showingResult);
    fileView.classList.toggle("hidden", !hasFiles || showingResult);

    mergeBtn.disabled = files.length < 1;
}


function showResult(blobUrl, fileName, pageInfo) {
    if (lastObjectUrl) {
        URL.revokeObjectURL(lastObjectUrl);
    }

    lastObjectUrl = blobUrl;

    downloadLink.href = blobUrl;
    downloadLink.download = fileName;
    resultText.textContent = pageInfo;

    resultBox.classList.remove("hidden");
    fileView.classList.add("hidden");
    emptyState.classList.add("hidden");
}


function resetToStart() {
    resultBox.classList.add("hidden");
    clearAll();
    setStatus("Bereit");
}


/* ===================== MERGE ===================== */

async function mergeFiles() {
    if (files.length === 0) {
        setStatus("Bitte zuerst Dateien hinzufügen");
        return;
    }

    if (getTotalBytes() > MAX_TOTAL_BYTES) {
        setStatus(`Zu groß. Maximal ${formatSize(MAX_TOTAL_BYTES)} pro Merge.`);
        return;
    }

    const orderedFiles = reverseOrder.checked ? [...files].reverse() : files;

    const formData = new FormData();
    orderedFiles.forEach(entry => formData.append("files", entry.file));

    const rawName = (outputName.value || "merged").trim();
    formData.append("output_name", rawName);

    mergeBtn.disabled = true;
    mergeBtn.textContent = "Wird verarbeitet";
    setStatus("Dateien werden zusammengefügt");

    try {
        const response = await fetch("/tools/pdf/merge", {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            let message = `Fehler ${response.status}`;

            try {
                const errorData = await response.json();
                message = errorData.error || message;
            } catch (parseError) {
                // Antwort war kein JSON, Standardmeldung reicht
            }

            throw new Error(message);
        }

        const pages = response.headers.get("X-Total-Pages");
        const blob = await response.blob();
        const blobUrl = URL.createObjectURL(blob);

        const safeName = rawName.toLowerCase().endsWith(".pdf") ? rawName : `${rawName}.pdf`;
        const pageInfo = pages
            ? `${files.length} Dateien zu ${pages} Seiten zusammengefügt.`
            : `${files.length} Dateien zusammengefügt.`;

        showResult(blobUrl, safeName, pageInfo);
        setStatus("Fertig");

    } catch (error) {
        setStatus(`Fehler: ${error.message}`);

    } finally {
        mergeBtn.disabled = false;
        mergeBtn.textContent = "Zusammenfügen";
    }
}


/* ===================== EVENTS ===================== */

dropzone.addEventListener("click", () => fileInput.click());
addBtn.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = "";
});

dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("dragover");
});

dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
});

dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragover");

    if (event.dataTransfer && event.dataTransfer.files.length > 0) {
        addFiles(event.dataTransfer.files);
    }
});

// Verhindert, dass der Browser eine woanders fallengelassene Datei einfach oeffnet
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

mergeBtn.addEventListener("click", mergeFiles);
clearBtn.addEventListener("click", clearAll);
newMergeBtn.addEventListener("click", resetToStart);

renderAll();
