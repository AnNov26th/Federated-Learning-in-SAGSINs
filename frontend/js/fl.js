const form = document.getElementById("experiment-form");
const message = document.getElementById("message");
const startButton = document.getElementById("start-button");
const compareButton = document.getElementById("compare-button");
let pollTimer;
let datasets = [];
const networkTask = (data) => data.task === "network_delay";
const qualityText = (data, round) => networkTask(data)
    ? `MAE ${number(round?.prediction_metrics?.mae_ms)} ms · RMSE ${number(round?.prediction_metrics?.rmse_ms)} ms`
    : `Accuracy ${round?.accuracy == null ? "—" : number(round.accuracy * 100, 1) + "%"}`;
const number = (value, digits = 2) => value == null ? "—" : Number(value).toFixed(digits);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function loadScenarios() {
    const select = document.getElementById("scenario");
    try {
        const response = await fetch("/api/simulations/scenarios");
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error("Scenario data is unavailable.");
        const scenarios = result.data || [];
        select.innerHTML = scenarios.length ? scenarios.map((scenario) => '<option value="' + scenario.id + '">' + escapeHtml(scenario.name) + '</option>').join("") : '<option value="">No scenario found; initialize the database first</option>';
        if (!scenarios.length) startButton.disabled = compareButton.disabled = true;
        await loadDatasets();
    } catch (error) {
        select.innerHTML = '<option value="">Could not load scenarios</option>';
        showMessage(error.message, true);
        startButton.disabled = compareButton.disabled = true;
    }
}
function showMessage(text, isError = false) {
    message.textContent = text;
    message.classList.toggle("error", isError);
}
function readPayload() {
    const values = Object.fromEntries(new FormData(form));
    ["scenario_id","rounds","client_count","local_epochs","learning_rate","batch_size","dropout_probability","timeout_ms","seed"].forEach((key) => values[key] = Number(values[key]));
    values.samples_per_client = Number(values.samples_per_client);
    if (values.task === "network_delay" && values.dataset_id) values.dataset_id = Number(values.dataset_id);
    else delete values.dataset_id;
    return values;
}
async function loadDatasets() {
    const scenarioId = form.elements.scenario_id.value;
    if (!scenarioId) return;
    const response = await fetch(`/api/fl/datasets?scenario_id=${encodeURIComponent(scenarioId)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not load datasets. Initialize database tables first.");
    datasets = result.data || [];
    form.elements.dataset_id.innerHTML = '<option value="">Generate a new snapshot when starting</option>' + datasets.map((row) => `<option value="${row.id}">#${row.id} · ${escapeHtml(row.partition)} · ${row.client_count} clients · seed ${row.seed}</option>`).join("");
}
function updateTask() {
    const isNetwork = form.elements.task.value === "network_delay";
    const predictive = [...form.elements.algorithm.options].find((option) => option.value === "Predictive");
    predictive.disabled = !isNetwork;
    if (!isNetwork && form.elements.algorithm.value === "Predictive") form.elements.algorithm.value = "FedAvg";
    document.getElementById("dataset-field").hidden = !isNetwork;
    document.getElementById("samples-field").hidden = !isNetwork;
    document.getElementById("client-quality-label").textContent = isNetwork ? "Local regression loss" : "Local accuracy";
    document.getElementById("task-note").textContent = isNetwork
        ? "Generated network observations use node/link snapshots and temporal congestion. The model predicts next-tick model transfer delay. Prediction-aware scheduling uses a random first round, then the previous global model. Client data is logically partitioned in the shared database. Network and energy outcomes are simulation estimates."
        : "MNIST demo trains a CNN. Non-IID uses label-sorted shards. Comparison uses random and static Delay-Aware scheduling; network costs are simulation estimates.";
}
function renderExperiment(data) {
    const rounds = data.rounds || [];
    const latest = rounds.at(-1);
    const accuracy = qualityText(data, latest);
    document.getElementById("summary").innerHTML = `Experiment <strong>#${data.id}</strong> · ${escapeHtml(data.algorithm)} · ${escapeHtml(data.status)} · ${data.completed_rounds}/${data.target_rounds} rounds · ${accuracy} · <a href="/results.html?experiment_id=${data.id}">Analyze results</a>${data.error_message ? ` · ${escapeHtml(data.error_message)}` : ""}`;
    document.getElementById("rounds").innerHTML = rounds.map((round) => `<div class="round"><span>Round ${round.round}</span><progress max="${data.target_rounds}" value="${round.round}" aria-label="Completed round ${round.round}"></progress><span>${qualityText(data, round)} · clients ${round.participants_count}/${round.selected_count} · ${number(round.round_duration_s)} s</span></div>`).join("");
    if (!latest) return;
    document.getElementById("clients").innerHTML = latest.clients.map((client) => '<tr><td>' + escapeHtml(client.client_id) + '</td><td>' + escapeHtml(client.status) + '</td><td>' + client.samples_used + '</td><td>' + (client.local_accuracy == null ? "—" : number(client.local_accuracy * 100, 1) + "%") + '</td><td>' + number(client.training_duration_s, 2) + ' s</td><td>' + number(client.communication_time_ms, 1) + ' ms</td></tr>').join("");
    if (networkTask(data)) document.getElementById("clients").innerHTML = latest.clients.map((client) => `<tr><td>${escapeHtml(client.client_id)}</td><td>${escapeHtml(client.status)}</td><td>${client.samples_used}</td><td>${number(client.local_loss,5)}</td><td>${number(client.training_duration_s)} s</td><td>${number(client.communication_time_ms)} ms</td></tr>`).join("");
}
async function pollExperiment(id) {
    try {
        const response = await fetch("/api/fl/experiments/" + id);
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.detail || "Could not read experiment status.");
        renderExperiment(result.data);
        if (["COMPLETED","FAILED","CANCELLED"].includes(result.data.status)) {
            clearInterval(pollTimer);
            startButton.disabled = compareButton.disabled = false;
            showMessage(result.data.status === "COMPLETED" ? "Training completed." : "Training " + result.data.status.toLowerCase() + ".", result.data.status !== "COMPLETED");
        }
    } catch (error) {
        clearInterval(pollTimer);
        startButton.disabled = compareButton.disabled = false;
        showMessage(error.message, true);
    }
}
async function pollComparison(id) {
    try {
        const response = await fetch("/api/fl/comparisons/" + encodeURIComponent(id));
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.detail || "Could not read comparison status.");
        const runs = result.data.experiments || [];
        const latest = (run) => run.rounds && run.rounds.at(-1);
        const fedavg = runs.find((run) => run.algorithm === "FedAvg");
        if (fedavg && latest(fedavg)) renderExperiment(fedavg);
        document.getElementById("summary").innerHTML = "Comparison <strong>" + escapeHtml(id) + "</strong> · " + escapeHtml(result.data.status) + " · same pool " + result.data.same_candidate_pool + " · same seed " + result.data.same_seed + ' · <a href="/results.html?comparison_id=' + encodeURIComponent(id) + '">Open comparison results</a>';
        document.getElementById("rounds").innerHTML = runs.map((run) => {
            const round = latest(run);
            return `<div class="round"><span>${escapeHtml(run.algorithm)}</span><progress max="${run.target_rounds}" value="${run.completed_rounds}" aria-label="${escapeHtml(run.algorithm)} round progress"></progress><span>${escapeHtml(run.status)} · ${run.completed_rounds}/${run.target_rounds} rounds · ${qualityText(run, round)} · communication ${number(round?.metrics?.communication_time_ms)} ms</span></div>`;
        }).join("");
        if (["COMPLETED","FAILED"].includes(result.data.status)) {
            clearInterval(pollTimer);
            startButton.disabled = compareButton.disabled = false;
            showMessage("Paired comparison " + result.data.status.toLowerCase() + ".", result.data.status !== "COMPLETED");
        }
    } catch (error) {
        clearInterval(pollTimer);
        startButton.disabled = compareButton.disabled = false;
        showMessage(error.message, true);
    }
}
async function queue(url, isComparison) {
    if (!form.reportValidity()) return;
    clearInterval(pollTimer);
    startButton.disabled = compareButton.disabled = true;
    showMessage(isComparison ? "Queueing matched scheduling policies…" : "Creating dataset and experiment…");
    try {
        const response = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json",Accept:"application/json"}, body:JSON.stringify(readPayload())});
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.detail || result.message || "Could not create experiment.");
        if (isComparison) {
            const id = result.data.comparison_id;
            showMessage("Comparison " + id + " queued.");
            await pollComparison(id);
            if (startButton.disabled) pollTimer = setInterval(() => pollComparison(id), 1500);
        } else {
            const id = result.data.id;
            showMessage("Experiment #" + id + " queued.");
            await pollExperiment(id);
            if (startButton.disabled) pollTimer = setInterval(() => pollExperiment(id), 1500);
        }
    } catch (error) {
        startButton.disabled = compareButton.disabled = false;
        showMessage(error.message, true);
    }
}
form.addEventListener("submit", (event) => { event.preventDefault(); queue("/api/fl/experiments", false); });
compareButton.addEventListener("click", () => queue("/api/fl/comparisons", true));
form.elements.task.addEventListener("change", updateTask);
form.elements.scenario_id.addEventListener("change", () => loadDatasets().catch((error) => showMessage(error.message, true)));
form.elements.dataset_id.addEventListener("change", () => {
    const dataset = datasets.find((row) => row.id === Number(form.elements.dataset_id.value));
    if (!dataset) return;
    ["seed","partition","network_profile"].forEach((key) => form.elements[key].value = dataset[key]);
});
updateTask();
loadScenarios();
