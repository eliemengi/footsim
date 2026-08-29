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

/* ===================== NATIVER DOWNLOADWEG (nur iOS-App) =============
 *
 * WARUM ES DIESEN ZWEITEN WEG GIBT
 * Der normale Weg holt das fertige PDF per fetch() als Blob und haengt
 * eine blob:-URL an <a download>. Im Browser ist das richtig: Es
 * erlaubt Vorschau, Seitenzahl und einen frei gewaehlten Dateinamen.
 *
 * In einer WKWebView ist derselbe Weg eine Sackgasse. Ein Klick auf
 * <a download href="blob:..."> erzeugt dort KEINEN WKDownload: Es
 * entsteht keine HTTP-Antwort, die die Huelle abfangen koennte, und
 * blob: ist ein reserviertes Schema, das kein eigener SchemeHandler
 * bedienen darf. Der Knopf bliebe wirkungslos - und ein sichtbarer
 * Knopf, der nichts tut, ist im App Review ein Ablehnungsgrund.
 *
 * DIE LOESUNG
 * Im iOS-Modus wird stattdessen ein echtes Formular an DIESELBE Route
 * gesendet. Die Antwort traegt Content-Disposition: attachment, und
 * genau daran erkennt die Huelle einen Download und uebergibt ihn dem
 * WKDownloadDelegate.
 *
 * WARUM IN EIN VERSTECKTES IFRAME
 * Ein Formular-POST im Hauptfenster wuerde die Seite verlassen. Bei
 * Erfolg faellt das nicht auf (die Navigation wird zum Download), bei
 * einem Fehler stuende jedoch die rohe JSON-Antwort im Fenster. Das
 * iframe faengt beides ab: Der Download laeuft unveraendert an, und
 * eine Fehlerantwort bleibt unsichtbar und ist - gleiche Herkunft -
 * auslesbar, sodass die gewohnte Meldung erscheinen kann.
 *
 * Serverseitig aendert sich nichts: dieselbe Route, dasselbe
 * multipart/form-data, dasselbe CSRF-Token, dieselben Limits und
 * dieselbe Ratenbegrenzung. Es bleibt bei EINER Anfrage.
 */

const PDF_ROUTE = "/tools/pdf/merge";
const NATIV_FEHLER_FRIST_MS = 45000;

/** Ist die Seite in der iOS-Huelle? Setzt das Include im <head>. */
function istIosApp() {
    return document.documentElement.getAttribute("data-platform") === "ios";
}

function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
}

/**
 * Sendet den Merge als echtes Formular und laesst die Huelle den
 * Download uebernehmen.
 *
 * Rueckgabe: Promise, das mit einer Fehlermeldung aufloest (Zeichenkette)
 * oder mit null, wenn kein Fehler erkennbar war - dann hat die Huelle
 * den Download uebernommen.
 */
function mergeUeberFormular(orderedFiles, rawName) {
    return new Promise((resolve) => {
        const rahmen = document.createElement("iframe");
        rahmen.name = "footsim-pdf-sink";
        rahmen.setAttribute("aria-hidden", "true");
        rahmen.style.display = "none";

        const formular = document.createElement("form");
        formular.method = "POST";
        formular.action = PDF_ROUTE;
        formular.enctype = "multipart/form-data";
        formular.target = rahmen.name;
        formular.style.display = "none";

        // Die ausgewaehlten Dateien in ein echtes File-Input uebernehmen.
        // DataTransfer ist der einzige Weg, FileList programmatisch zu
        // fuellen - ein blosses value= ist aus Sicherheitsgruenden
        // gesperrt. Die Reihenfolge bleibt dabei erhalten.
        const dateiFeld = document.createElement("input");
        dateiFeld.type = "file";
        dateiFeld.name = "files";
        dateiFeld.multiple = true;

        const uebertrag = new DataTransfer();
        orderedFiles.forEach(eintrag => uebertrag.items.add(eintrag.file));
        dateiFeld.files = uebertrag.files;

        const nameFeld = document.createElement("input");
        nameFeld.type = "hidden";
        nameFeld.name = "output_name";
        nameFeld.value = rawName;

        // CSRFProtect akzeptiert das Token als Formularfeld ODER als
        // Header. Beim Formular-POST gibt es keinen Header, also das
        // Feld - der Schutz bleibt unveraendert scharf.
        const tokenFeld = document.createElement("input");
        tokenFeld.type = "hidden";
        tokenFeld.name = "csrf_token";
        tokenFeld.value = csrfToken();

        formular.append(dateiFeld, nameFeld, tokenFeld);
        document.body.append(rahmen, formular);

        let erledigt = false;
        const aufraeumen = (meldung) => {
            if (erledigt) return;
            erledigt = true;
            clearTimeout(frist);
            rahmen.remove();
            formular.remove();
            resolve(meldung);
        };

        // Laedt das iframe, kam KEIN Download zustande - dann steht dort
        // die Fehlerantwort. Gleiche Herkunft, also lesbar.
        rahmen.addEventListener("load", () => {
            let meldung = "Der Download konnte nicht gestartet werden.";
            try {
                const inhalt = rahmen.contentDocument
                    && rahmen.contentDocument.body
                    && rahmen.contentDocument.body.textContent;
                if (inhalt && inhalt.trim()) {
                    try {
                        meldung = JSON.parse(inhalt).error || meldung;
                    } catch (parseError) {
                        meldung = inhalt.trim().slice(0, 200);
                    }
                }
            } catch (zugriffsFehler) {
                /* Sollte bei gleicher Herkunft nicht vorkommen. */
            }
            aufraeumen(meldung);
        });

        // Loest der Download aus, feuert kein load-Ereignis. Nach dieser
        // Frist gilt der Vorgang als uebergeben - der Knopf wird wieder
        // freigegeben, damit ein zweiter Merge moeglich ist.
        const frist = setTimeout(() => aufraeumen(null), NATIV_FEHLER_FRIST_MS);

        formular.submit();
    });
}


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
    const rawName = (outputName.value || "merged").trim();

    mergeBtn.disabled = true;
    mergeBtn.textContent = "Wird verarbeitet";
    setStatus("Dateien werden zusammengefügt");

    // iOS-Huelle: nativer Downloadweg statt Blob. Alles davor - Auswahl,
    // Reihenfolge, Groessenpruefung - ist identisch.
    if (istIosApp()) {
        try {
            const fehler = await mergeUeberFormular(orderedFiles, rawName);
            setStatus(fehler ? `Fehler: ${fehler}` : "Fertig. Der Download wurde übergeben.");
        } catch (error) {
            setStatus(`Fehler: ${error.message}`);
        } finally {
            mergeBtn.disabled = false;
            mergeBtn.textContent = "Zusammenfügen";
        }
        return;
    }

    const formData = new FormData();
    orderedFiles.forEach(entry => formData.append("files", entry.file));
    formData.append("output_name", rawName);

    try {
        // CSRFProtect schuetzt diesen POST serverseitig. Ohne den Header
        // antwortet der Server mit 400 und der Merge schlaegt fehl - das
        // Token gehoert deshalb an jeden Upload.
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const headers = csrfMeta ? { "X-CSRFToken": csrfMeta.content } : {};

        const response = await fetch("/tools/pdf/merge", {
            method: "POST",
            headers,
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
