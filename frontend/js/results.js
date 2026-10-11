const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits);
let experiment = null;
let charts = [];
function notice(message, kind = "") { const el = $("results-notice"); el.textContent = message; el.className = `notice${kind ? ` ${kind}` : ""}`; }
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
    $("result-summary").innerHTML = `<strong>Experiment #${data.id}</strong> · ${esc(data.algorithm)} · ${esc(data.status)} · ${data.completed_rounds}/${data.target_rounds} rounds · Scenario ${data.scenario_id}<br><small>Seed ${esc(config.seed)} · ${esc(config.partition)} partition · Network profile ${esc(config.network_profile)} · Metrics: ${esc(config.metrics_source || "not specified")}</small>`;
    $("round-results").innerHTML = rounds.length ? rounds.map((round) => {
        const metrics = round.metrics || {};
        return `<tr><td>${round.round}</td><td>${num(round.accuracy*100,1)}%</td><td>${num(round.loss,4)}</td><td>${round.participants_count}/${round.selected_count}</td><td>${num(round.round_duration_s)} s</td><td>${num(metrics.communication_time_ms,1)} ms</td><td>${num(metrics.energy_j,2)} J</td><td>${num(metrics.data_transferred_mb,2)} MB</td><td>${num(metrics.packet_loss_ratio == null ? null : metrics.packet_loss_ratio*100,1)}%</td></tr>`;
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
        if (requestedId && runs.some((run) => String(run.id) === requestedId)) {
            select.value = requestedId;
            await loadExperiment(requestedId);
        } else if (runs.length) {
            select.value = String(runs[0].id);
            await loadExperiment(runs[0].id);
        } else notice("No experiment results yet. Start a run from FL Training.");
    } catch (error) { notice(error.message || "Experiment API is unavailable.", "error"); }
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
init();
