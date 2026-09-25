const chartInstances = [];
let dashboardRequestId = 0;

const byId = (id) => document.getElementById(id);
const setText = (id, value) => { byId(id).textContent = value; };
const formatNumber = (value, digits = 0) => {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(Number(value));
};
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));

function setConnection(state, label) {
    const element = byId("connection-state");
    element.dataset.state = state;
    element.textContent = label;
}

function showNotice(message, kind = "info") {
    const notice = byId("dashboard-notice");
    notice.textContent = message;
    notice.className = `notice${kind === "error" ? " error" : ""}`;
    notice.hidden = !message;
}

function clearCharts() {
    while (chartInstances.length) chartInstances.pop().destroy();
}

function renderChart(canvasId, type, label, values, color, options = {}) {
    if (typeof Chart === "undefined") return false;
    const canvas = byId(canvasId);
    chartInstances.push(new Chart(canvas, {
        type,
        data: {
            labels: options.labels,
            datasets: [{
                label,
                data: values,
                borderColor: color,
                backgroundColor: options.fill ? `${color}22` : color,
                borderWidth: 2,
                tension: .3,
                fill: Boolean(options.fill),
                borderRadius: type === "bar" ? 4 : undefined,
                spanGaps: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: "index" },
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: "rgba(255,255,255,.05)" } },
                y: {
                    beginAtZero: options.beginAtZero !== false,
                    ...(options.percent ? { min: 0, max: 100 } : {}),
                    grid: { color: "rgba(255,255,255,.07)" },
                },
            },
        },
    }));
    return true;
}

function renderExperiments(experiments) {
    const tbody = byId("experiment-rows");
    if (!experiments.length) {
        tbody.innerHTML = '<tr><td class="empty-row" colspan="5">No experiments have been recorded.</td></tr>';
        return;
    }
    tbody.innerHTML = experiments.map((experiment) => {
        const status = experiment.status || "not_started";
        const accuracy = experiment.accuracy === null || experiment.accuracy === undefined
            ? "—" : `${formatNumber(experiment.accuracy, 1)}%`;
        return `<tr>
            <td>${escapeHtml(experiment.scenario)}</td>
            <td>${escapeHtml(experiment.algorithm)}</td>
            <td>${formatNumber(experiment.completed_rounds)} / ${formatNumber(experiment.target_rounds)}</td>
            <td>${accuracy}</td>
            <td><span class="status-pill ${escapeHtml(status)}">${escapeHtml(status.replaceAll("_", " "))}</span></td>
        </tr>`;
    }).join("");
}

function renderAlerts(alerts) {
    const list = byId("alerts-list");
    if (!alerts.length) {
        list.innerHTML = '<div class="alert-item info"><strong>No network notices</strong><span>No inactive links or missing topology data were reported.</span></div>';
        return;
    }
    list.innerHTML = alerts.map((alert) => `<div class="alert-item ${escapeHtml(alert.severity)}">
        <strong>${escapeHtml(alert.title)}</strong><span>${escapeHtml(alert.message)}</span>
    </div>`).join("");
}

function updateFilters(filters = {}) {
    const scenarioSelect = byId("scenario-filter");
    const algorithmSelect = byId("algorithm-filter");
    const selectedScenario = scenarioSelect.value;
    const selectedAlgorithm = algorithmSelect.value;
    scenarioSelect.innerHTML = '<option value="">All scenarios</option>' + (filters.scenarios || []).map((scenario) =>
        `<option value="${escapeHtml(scenario.id)}">${escapeHtml(scenario.name)}</option>`
    ).join("");
    algorithmSelect.innerHTML = '<option value="">All algorithms</option>' + (filters.algorithms || []).map((algorithm) =>
        `<option value="${escapeHtml(algorithm)}">${escapeHtml(algorithm)}</option>`
    ).join("");
    if ([...scenarioSelect.options].some((option) => option.value === selectedScenario)) scenarioSelect.value = selectedScenario;
    if ([...algorithmSelect.options].some((option) => option.value === selectedAlgorithm)) algorithmSelect.value = selectedAlgorithm;
}

function renderDashboard(data) {
    const topology = data.topology || {};
    const participants = data.participants || {};
    const experiment = data.latest_experiment;

    setText("kpi-total", formatNumber(topology.total));
    setText("kpi-links", formatNumber(topology.links));
    setText("kpi-links-note", `${formatNumber(topology.active_links)} marked active · ${formatNumber(topology.links)} total`);
    setText("kpi-participants", formatNumber(participants.total));
    setText("kpi-participants-note", `${formatNumber(participants.selected)} selected`);
    setText("kpi-space", formatNumber(topology.space));
    setText("kpi-air", formatNumber(topology.air));
    setText("kpi-ground", formatNumber(topology.ground));
    setText("kpi-sea", formatNumber(topology.sea));

    if (experiment) {
        setText("kpi-accuracy", experiment.accuracy === null || experiment.accuracy === undefined
            ? "—" : `${formatNumber(experiment.accuracy, 1)}%`);
        setText("kpi-experiment-note", `${experiment.algorithm} · ${experiment.status.replaceAll("_", " ")}`);
        setText("dashboard-context", `${experiment.scenario} · ${experiment.algorithm} · Experiment #${experiment.id}`);
        setText("experiment-summary", `${formatNumber(experiment.completed_rounds)} of ${formatNumber(experiment.target_rounds)} rounds recorded`);
    } else {
        setText("kpi-accuracy", "—");
        setText("kpi-experiment-note", "No experiment recorded");
        setText("dashboard-context", "Network topology and federated learning overview");
        setText("experiment-summary", "No experiment has been recorded yet");
    }

    renderExperiments(data.recent_experiments || []);
    renderAlerts(data.alerts || []);
    updateFilters(data.filters);

    const updated = data.generated_at ? new Date(data.generated_at) : new Date();
    setText("updated-at", `Updated ${updated.toLocaleString()}`);

    const rounds = data.fl_training || [];
    clearCharts();
    const hasTraining = rounds.length > 0;
    byId("charts-grid").hidden = !hasTraining;
    byId("charts-empty").hidden = hasTraining;
    if (!hasTraining) return true;
    if (typeof Chart === "undefined") {
        byId("charts-grid").hidden = true;
        byId("charts-empty").hidden = false;
        byId("charts-empty").innerHTML = '<div><i class="fa-solid fa-triangle-exclamation"></i><strong>Charts could not be rendered</strong><br>Round data exists, but Chart.js could not be loaded.</div>';
        return false;
    }

    const labels = rounds.map((round) => `Round ${round.round}`);
    const common = { labels };
    const chartReady = [
        renderChart("accuracyChart", "line", "Accuracy (%)", rounds.map((r) => r.accuracy), "#00d98b", { ...common, fill: true, percent: true }),
        renderChart("lossChart", "line", "Loss", rounds.map((r) => r.loss), "#ff626e", { ...common, fill: true }),
        renderChart("latencyChart", "bar", "Latency (ms)", rounds.map((r) => r.latency), "#42b8ff", { ...common }),
        renderChart("energyChart", "line", "Recorded energy", rounds.map((r) => r.energy), "#ffb43c", { ...common, fill: true }),
    ].every(Boolean);
    return chartReady;
}

async function loadDashboard() {
    const requestId = ++dashboardRequestId;
    const button = byId("refresh-dashboard");
    button.disabled = true;
    setConnection("loading", "Connecting…");
    showNotice("Loading dashboard data…");
    try {
        const query = new URLSearchParams();
        if (byId("scenario-filter").value) query.set("scenario_id", byId("scenario-filter").value);
        if (byId("algorithm-filter").value) query.set("algorithm", byId("algorithm-filter").value);
        const suffix = query.size ? `?${query.toString()}` : "";
        const response = await fetch(`/api/dashboard/stats${suffix}`, { headers: { Accept: "application/json" } });
        if (requestId !== dashboardRequestId) return;
        if (!response.ok) throw new Error(`Dashboard API returned ${response.status}`);
        const result = await response.json();
        if (requestId !== dashboardRequestId) return;
        if (result.status !== "success" || !result.data) throw new Error(result.message || "Dashboard data is unavailable.");
        const chartsAvailable = renderDashboard(result.data);
        setConnection("connected", "Data connected");
        showNotice(chartsAvailable ? "" : "Dashboard data loaded, but charts could not load. Check access to the Chart.js CDN.", chartsAvailable ? "info" : "error");
    } catch (error) {
        if (requestId !== dashboardRequestId) return;
        console.error("Unable to load dashboard:", error);
        setConnection("error", "Data unavailable");
        showNotice("Could not load dashboard data. Check that the backend and database are reachable, then refresh.", "error");
        byId("experiment-rows").innerHTML = '<tr><td class="empty-row" colspan="5">Experiment data could not be loaded.</td></tr>';
        byId("alerts-list").innerHTML = '<div class="alert-item warning"><strong>Dashboard data unavailable</strong><span>Backend or database connection failed.</span></div>';
    } finally {
        if (requestId === dashboardRequestId) button.disabled = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    byId("refresh-dashboard").addEventListener("click", loadDashboard);
    byId("scenario-filter").addEventListener("change", loadDashboard);
    byId("algorithm-filter").addEventListener("change", loadDashboard);
    loadDashboard();
});
