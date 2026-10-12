const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits);
let experiment = null;
let charts = [];
function notice(message, kind = "") { const el = $("results-notice"); el.textContent = message; el.className = `notice${kind ? ` ${kind}` : ""}`; }
function downloadCsv(filename, header, rows) {
    const quote = (value) => `"${String(value ?? "").replaceAll('"','""')}"`;
    const csv = [header,...rows].map((row) => row.map(quote).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF",csv], {type:"text/csv;charset=utf-8"}));
    const link = Object.assign(document.createElement("a"), {href:url,download:filename});
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderCharts(rounds) {
    charts.forEach((chart) => chart.destroy());
    charts = [];
    if (typeof Chart === "undefined" || !rounds.length) return;
    const labels = rounds.map((round) => `Round ${round.round}`);
    const series = [
        ["accuracy-chart", rounds.map((round) => round.accuracy * 100), "#00d98b"],
        ["loss-chart", rounds.map((round) => round.loss), "#ffb43c"],
        ["communication-chart", rounds.map((round) => round.metrics?.communication_time_ms ?? null), "#48d9ff"],
        ["energy-chart", rounds.map((round) => round.metrics?.energy_j ?? null), "#bb8cff"],
    ];
    charts = series.map(([canvasId, values, color]) => new Chart($(canvasId), {
        type: "line",
        data: { labels, datasets: [{ data: values, borderColor: color, backgroundColor: `${color}22`, fill: true, tension: .25, spanGaps: false, pointRadius: 3 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: "rgba(255,255,255,.05)" } }, y: { beginAtZero: true, grid: { color: "rgba(255,255,255,.07)" } } } },
    }));
}
function renderRound(round) {
    const clients = round?.clients || [];
    $("client-results").innerHTML = clients.length ? clients.map((client) => `<tr><td>${esc(client.client_id)}</td><td><span class="status ${esc(String(client.status).toLowerCase())}">${esc(client.status)}</span></td><td>${Number(client.samples_used || 0).toLocaleString()}</td><td>${client.local_accuracy == null ? "—" : `${num(client.local_accuracy*100,1)}%`}</td><td>${num(client.training_duration_s)} s</td><td>${num(client.latency_ms,1)} ms</td><td>${num(client.communication_time_ms,1)} ms</td><td>${esc(client.failure_reason)}</td></tr>`).join("") : '<tr><td colspan="8" class="empty">No client outcome rows were saved for this round.</td></tr>';
}
function render(data) {
    experiment = data;
    const rounds = data.rounds || [];
    const config = data.config || {};
    $("result-config-link").href = `/experiments.html?experiment_id=${encodeURIComponent(data.id)}`;
    $("result-summary").innerHTML = `<strong>Experiment #${data.id}</strong> · ${esc(data.algorithm)} · ${esc(data.status)} · ${data.completed_rounds}/${data.target_rounds} rounds · Scenario ${data.scenario_id} · worker wall time ${num(data.actual_duration_s)} s<br><small>Seed ${esc(config.seed)} · ${esc(config.partition)} partition · Network profile ${esc(config.network_profile)} · Metrics: ${esc(config.metrics_source || "not specified")}</small>`;
    $("round-results").innerHTML = rounds.length ? rounds.map((round) => {
        const metrics = round.metrics || {};
        return `<tr><td>${round.round}</td><td>${num(round.accuracy*100,1)}%</td><td>${num(round.loss,4)}</td><td>${round.participants_count}/${round.selected_count}</td><td>${num(round.round_duration_s)} s</td><td>${num(metrics.communication_time_ms,1)} ms</td><td>${num(metrics.energy_j,2)} J</td><td>${num(metrics.data_transferred_mb,2)} MB</td><td>${num(metrics.client_failure_ratio == null ? null : metrics.client_failure_ratio*100,1)}%</td></tr>`;
    }).join("") : '<tr><td colspan="9" class="empty">No rounds have been saved for this experiment yet.</td></tr>';
    renderCharts(rounds);
    const roundSelect = $("result-round");
    roundSelect.innerHTML = rounds.length ? rounds.map((round) => `<option value="${round.round}">Round ${round.round}</option>`).join("") : '<option value="">No rounds</option>';
    roundSelect.disabled = !rounds.length;
    if (rounds.length) {
        roundSelect.value = String(rounds.at(-1).round);
        renderRound(rounds.at(-1));
    } else renderRound(null);
    notice(`Loaded experiment #${data.id} results.`);
}
function exportRounds() {
    if (!experiment) return notice("Choose an experiment before exporting rounds.", "error");
    const rows = (experiment.rounds || []).map((round) => [experiment.id,round.round,round.accuracy,round.loss,round.participants_count,round.selected_count,round.round_duration_s,round.metrics?.communication_time_ms,round.metrics?.energy_j,round.metrics?.data_transferred_mb,round.metrics?.client_failure_ratio]);
    downloadCsv(`sagsin-experiment-${experiment.id}-rounds.csv`,["experiment_id","round","test_accuracy","test_loss","clients_completed","clients_selected","round_duration_s","communication_time_ms","energy_j","data_transferred_mb","client_failure_ratio"],rows);
}
function exportClients() {
    if (!experiment) return notice("Choose an experiment before exporting clients.", "error");
    const roundNumber = Number($("result-round").value);
    const round = experiment.rounds?.find((item) => item.round === roundNumber);
    if (!round) return notice("There are no client outcomes for this round.", "error");
    const rows = (round.clients || []).map((client) => [experiment.id,round.round,client.client_id,client.status,client.samples_used,client.local_accuracy,client.training_duration_s,client.latency_ms,client.communication_time_ms,client.failure_reason]);
    downloadCsv(`sagsin-experiment-${experiment.id}-round-${round.round}-clients.csv`,["experiment_id","round","client_id","outcome","samples","local_accuracy","training_duration_s","latency_ms","communication_time_ms","failure_reason"],rows);
}
async function loadExperiment(id) {
    if (!id) return;
    notice(`Loading experiment #${id}…`);
    try {
        const response = await fetch(`/api/fl/experiments/${encodeURIComponent(id)}`);
        const payload = await response.json();
        if (!response.ok || payload.status !== "success") throw new Error(payload.detail || "Could not load this experiment.");
        render(payload.data);
    } catch (error) { experiment = null; notice(error.message || "Results API is unavailable.", "error"); $("round-results").innerHTML = '<tr><td colspan="9" class="empty">Experiment results could not be loaded.</td></tr>'; $("client-results").innerHTML = '<tr><td colspan="8" class="empty">No client data.</td></tr>'; }
}
async function init() {
    try {
        const response = await fetch("/api/fl/experiments");
        const payload = await response.json();
        if (!response.ok || payload.status !== "success") throw new Error(payload.detail || "Could not load experiments.");
        const runs = payload.data || [];
        const select = $("result-experiment");
        select.innerHTML = runs.length ? `<option value="">Choose an experiment…</option>${runs.map((run) => `<option value="${run.id}">#${run.id} · ${esc(run.algorithm)} · ${esc(run.status)} · ${run.completed_rounds}/${run.target_rounds} rounds</option>`).join("")}` : '<option value="">No experiments found</option>';
        const requestedId = new URLSearchParams(location.search).get("experiment_id");
        const comparisonId = new URLSearchParams(location.search).get("comparison_id");
        if (comparisonId) {
            await loadComparison(comparisonId, runs);
            return;
        }
        if (requestedId && runs.some((run) => String(run.id) === requestedId)) {
            select.value = requestedId;
            await loadExperiment(requestedId);
        } else if (runs.length) {
            select.value = String(runs[0].id);
            await loadExperiment(runs[0].id);
        } else notice("No experiment results yet. Start a run from FL Training.");
    } catch (error) { notice(error.message || "Experiment API is unavailable.", "error"); }
}

async function loadComparison(comparisonId, summaries) {
    notice("Loading paired comparison…");
    try {
        const response = await fetch(`/api/fl/comparisons/${encodeURIComponent(comparisonId)}`);
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.detail || "Could not load comparison.");
        const data = result.data;
        const fedavg = data.experiments.find((run) => run.algorithm === "FedAvg");
        const delay = data.experiments.find((run) => run.algorithm === "DelayAware");
        if (!fedavg || !delay) throw new Error("The comparison is missing one of its paired runs.");
        const rounds = new Map();
        for (const run of [fedavg, delay]) for (const round of run.rounds) {
            if (!rounds.has(round.round)) rounds.set(round.round, {});
            rounds.get(round.round)[run.algorithm] = round;
        }
        const rows = [...rounds.entries()].sort((a,b) => a[0]-b[0]).map(([roundNumber, pair]) => {
            const f = pair.FedAvg, d = pair.DelayAware;
            return `<tr><td>${roundNumber}</td><td>${num(f?.accuracy*100,1)}%</td><td>${num(d?.accuracy*100,1)}%</td><td>${num(f?.round_duration_s)} s</td><td>${num(d?.round_duration_s)} s</td><td>${num(f?.metrics?.communication_time_ms,1)} ms</td><td>${num(d?.metrics?.communication_time_ms,1)} ms</td><td>${num(f?.metrics?.energy_j,2)} J</td><td>${num(d?.metrics?.energy_j,2)} J</td></tr>`;
        }).join("");
        $("comparison-audit").textContent = `Comparison ${comparisonId} · ${data.status}. Same candidate pool: ${data.same_candidate_pool}; same seed: ${data.same_seed}; same training config: ${data.same_training_config}. Worker wall time: FedAvg ${num(fedavg.actual_duration_s)} s, Delay-Aware ${num(delay.actual_duration_s)} s. Only the client scheduling policy differs.`;
        $("comparison-round-results").innerHTML = rows || '<tr><td colspan="9" class="empty">No paired rounds saved yet.</td></tr>';
        $("comparison-panel").hidden = false;
        const fedavgSummary = summaries.find((run) => run.id === fedavg.id);
        if (fedavgSummary) $("result-experiment").value = String(fedavg.id);
        await loadExperiment(fedavg.id);
        const url = new URL(location.href); url.searchParams.set("comparison_id", comparisonId); history.replaceState(null, "", url);
        notice(`Loaded paired comparison ${comparisonId}.`);
    } catch (error) {
        notice(error.message || "Comparison results could not be loaded.", "error");
    }
}
$("result-experiment").addEventListener("change", (event) => {
    const id = event.target.value;
    if (id) {
        const url = new URL(location.href); url.searchParams.set("experiment_id", id); history.replaceState(null, "", url);
        loadExperiment(id);
    }
});
$("result-round").addEventListener("change", (event) => {
    const round = experiment?.rounds?.find((item) => String(item.round) === event.target.value);
    renderRound(round);
});
$("export-rounds").addEventListener("click", exportRounds);
$("export-clients").addEventListener("click", exportClients);
init();
