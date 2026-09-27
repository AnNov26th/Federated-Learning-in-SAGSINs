const form = document.getElementById("experiment-form");
const message = document.getElementById("message");
const startButton = document.getElementById("start-button");
let pollTimer;

const number = (value, digits = 2) => value == null ? "—" : Number(value).toFixed(digits);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));

async function loadScenarios() {
    const select = document.getElementById("scenario");
    try {
        const response = await fetch("/api/simulations/scenarios");
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error("Scenario data is unavailable.");
        const scenarios = result.data || [];
        select.innerHTML = scenarios.length
            ? scenarios.map((scenario) => `<option value="${scenario.id}">${escapeHtml(scenario.name)}</option>`).join("")
            : '<option value="">No scenario found; initialize the database first</option>';
        if (!scenarios.length) startButton.disabled = true;
    } catch (error) {
        select.innerHTML = '<option value="">Could not load scenarios</option>';
        showMessage(error.message, true);
        startButton.disabled = true;
    }
}

function showMessage(text, isError = false) {
    message.textContent = text;
    message.classList.toggle("error", isError);
}

function renderExperiment(data) {
    const rounds = data.rounds || [];
    const completed = data.completed_rounds || 0;
    const latest = rounds.at(-1);
    const testAccuracy = data.latest_accuracy == null ? "—" : `${number(data.latest_accuracy * 100, 1)}%`;
    document.getElementById("summary").innerHTML = `Experiment <strong>#${data.id}</strong> · ${escapeHtml(data.status)} · ${completed}/${data.target_rounds} rounds · test accuracy <strong>${testAccuracy}</strong> · test loss <strong>${number(data.latest_loss, 4)}</strong>${data.error_message ? ` · ${escapeHtml(data.error_message)}` : ""}`;
    document.getElementById("rounds").innerHTML = rounds.map((round) => `
        <div class="round"><span>Round ${round.round}</span><progress max="1" value="${round.accuracy}"></progress><span>Test ${number(round.accuracy * 100, 1)}% · loss ${number(round.loss, 4)} · clients ${round.participants_count}/${round.selected_count} · dropped ${round.dropped_count}</span></div>
    `).join("");
    if (!latest) return;
    document.getElementById("clients").innerHTML = latest.clients.map((client) => `<tr>
        <td>${escapeHtml(client.client_id)}</td><td>${escapeHtml(client.status)}</td><td>${client.samples_used}</td>
        <td>${client.local_accuracy == null ? "—" : `${number(client.local_accuracy * 100, 1)}%`}</td>
        <td>${number(client.training_duration_s, 2)} s</td><td>${number(client.communication_time_ms, 1)} ms</td>
    </tr>`).join("");
}

async function pollExperiment(experimentId) {
    try {
        const response = await fetch(`/api/fl/experiments/${experimentId}`);
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.detail || "Could not read experiment status.");
        renderExperiment(result.data);
        if (["COMPLETED", "FAILED", "CANCELLED"].includes(result.data.status)) {
            clearInterval(pollTimer);
            startButton.disabled = false;
            showMessage(result.data.status === "COMPLETED" ? "Training completed." : `Training ${result.data.status.toLowerCase()}.`, result.data.status !== "COMPLETED");
        }
    } catch (error) {
        clearInterval(pollTimer);
        startButton.disabled = false;
        showMessage(error.message, true);
    }
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    clearInterval(pollTimer);
    startButton.disabled = true;
    showMessage("Creating experiment…");
    const values = Object.fromEntries(new FormData(form));
    for (const key of ["scenario_id", "rounds", "client_count", "local_epochs", "learning_rate", "batch_size", "dropout_probability", "timeout_ms", "seed"]) {
        values[key] = Number(values[key]);
    }
    try {
        const response = await fetch("/api/fl/experiments", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify(values),
        });
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.detail || result.message || "Could not create experiment.");
        showMessage(`Experiment #${result.data.id} queued.`);
        await pollExperiment(result.data.id);
        if (startButton.disabled) pollTimer = setInterval(() => pollExperiment(result.data.id), 1500);
    } catch (error) {
        startButton.disabled = false;
        showMessage(error.message, true);
    }
});

loadScenarios();
