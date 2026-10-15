const chartInstances = [];
let dashboardRequestId = 0;

document.querySelectorAll(".detail-links a").forEach((link) => {
    link.addEventListener("click", (event) => {
        event.preventDefault();
        window.parent.postMessage({ type: "sagsin:navigate", href: link.getAttribute("href") }, window.location.origin);
    });
});

const byId = (id) => document.getElementById(id);
const setText = (id, value) => { byId(id).textContent = value; };
const formatNumber = (value, digits = 0) => {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(Number(value));
};
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));
const statusLabel = (status) => ({completed:"Hoàn tất",in_progress:"Đang thực hiện",running:"Đang chạy",queued:"Đang chờ",failed:"Thất bại",cancelled:"Đã hủy"}[status] || status.replaceAll("_", " "));

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
        tbody.innerHTML = '<tr><td class="empty-row" colspan="5">Chưa có thí nghiệm nào được ghi nhận.</td></tr>';
        return;
    }
    tbody.innerHTML = experiments.map((experiment) => {
        const status = experiment.status || "not_started";
        const accuracy = experiment.task === "network_delay" ? `${formatNumber(experiment.mae_ms)} ms MAE` : experiment.accuracy === null || experiment.accuracy === undefined
            ? "—" : `${formatNumber(experiment.accuracy * 100, 1)}%`;
        return `<tr>
            <td>${escapeHtml(experiment.scenario)}</td>
            <td>${escapeHtml(experiment.algorithm)}${experiment.metrics_source === "synthetic_seed_data" ? " · demo data" : ""}</td>
            <td>${formatNumber(experiment.completed_rounds)} / ${formatNumber(experiment.target_rounds)}</td>
            <td>${accuracy}</td>
            <td><span class="status-pill ${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span></td>
        </tr>`;
    }).join("");
}

function renderAlerts(alerts) {
    const list = byId("alerts-list");
    if (!alerts.length) {
        list.innerHTML = '<div class="alert-item info"><strong>Không có cảnh báo mới</strong><span>Chưa phát hiện trạng thái cần xử lý.</span></div>';
        return;
    }
    const titles = {"No stored network links":"Chưa có liên kết mạng","Inactive network links":"Liên kết không hoạt động","Nodes need attention":"Node cần kiểm tra","No topology data":"Chưa có topology"};
    const messages = {
        "The topology contains nodes, but no explicit links are stored. Network connectivity is not inferred automatically.":"Topology có node nhưng chưa lưu liên kết tường minh. Hệ thống không tự suy diễn kết nối.",
    };
    list.innerHTML = alerts.map((alert) => `<div class="alert-item ${escapeHtml(alert.severity)}">
        <strong>${escapeHtml(titles[alert.title] || alert.title)}</strong><span>${escapeHtml(messages[alert.message] || alert.message)}</span>
    </div>`).join("");
}

function updateFilters(filters = {}) {
    const scenarioSelect = byId("scenario-filter");
    const algorithmSelect = byId("algorithm-filter");
    const selectedScenario = scenarioSelect.value;
    const selectedAlgorithm = algorithmSelect.value;
    scenarioSelect.innerHTML = '<option value="">Tất cả scenario</option>' + (filters.scenarios || []).map((scenario) =>
        `<option value="${escapeHtml(scenario.id)}">${escapeHtml(scenario.name)}</option>`
    ).join("");
    algorithmSelect.innerHTML = '<option value="">Tất cả thuật toán</option>' + (filters.algorithms || []).map((algorithm) =>
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
    setText("kpi-links-note", `${formatNumber(topology.active_links)} đang hoạt động · ${formatNumber(topology.links)} tổng`);
    setText("kpi-participants", formatNumber(participants.total));
    setText("kpi-participants-note", `${formatNumber(participants.selected)} đã chọn`);
    setText("kpi-space", formatNumber(topology.space));
    setText("kpi-air", formatNumber(topology.air));
    setText("kpi-ground", formatNumber(topology.ground));
    setText("kpi-sea", formatNumber(topology.sea));

    if (experiment) {
        setText("kpi-accuracy", experiment.task === "network_delay" ? `${formatNumber(experiment.mae_ms)} ms MAE` : experiment.accuracy === null || experiment.accuracy === undefined
            ? "—" : `${formatNumber(experiment.accuracy * 100, 1)}%`);
        setText("kpi-experiment-note", `${experiment.algorithm} · ${statusLabel(experiment.status)}`);
        setText("dashboard-context", `${experiment.scenario} · ${experiment.algorithm} · Thí nghiệm #${experiment.id}`);
        setText("experiment-summary", `Đã ghi nhận ${formatNumber(experiment.completed_rounds)} / ${formatNumber(experiment.target_rounds)} round`);
    } else {
        setText("kpi-accuracy", "—");
        setText("kpi-experiment-note", "Chưa có thí nghiệm");
        setText("dashboard-context", "Topology mạng và trạng thái Federated Learning");
        setText("experiment-summary", "Chưa có thí nghiệm nào được ghi nhận");
    }

    renderExperiments(data.recent_experiments || []);
    renderAlerts(data.alerts || []);
    updateFilters(data.filters);

    const updated = data.generated_at ? new Date(data.generated_at) : new Date();
    setText("updated-at", `Cập nhật ${updated.toLocaleString()}`);

    const rounds = data.fl_training || [];
    clearCharts();
    const hasTraining = rounds.length > 0;
    byId("charts-grid").hidden = !hasTraining;
    byId("charts-empty").hidden = hasTraining;
    if (!hasTraining) return true;
    if (typeof Chart === "undefined") {
        byId("charts-grid").hidden = true;
        byId("charts-empty").hidden = false;
        byId("charts-empty").innerHTML = '<div><i class="fa-solid fa-triangle-exclamation"></i><strong>Không thể vẽ biểu đồ</strong><br>Có dữ liệu round nhưng không tải được Chart.js.</div>';
        return false;
    }

    const labels = rounds.map((round) => `Round ${round.round}`);
    const common = { labels };
    const networkTask = experiment?.task === "network_delay";
    byId("accuracyChart").closest("article").querySelector("h3").textContent = networkTask ? "Sai số dự đoán toàn cục MAE (ms)" : "Độ chính xác mô hình toàn cục (%)";
    const chartReady = [
        renderChart("accuracyChart", "line", networkTask ? "MAE (ms)" : "Accuracy (%)", rounds.map((r) => networkTask ? r.mae_ms : r.accuracy * 100), "#00d98b", { ...common, fill: true, percent: !networkTask }),
        renderChart("lossChart", "line", "Loss", rounds.map((r) => r.loss), "#ff626e", { ...common, fill: true }),
        renderChart("latencyChart", "bar", "Latency (ms)", rounds.map((r) => r.latency_ms), "#42b8ff", { ...common }),
        renderChart("energyChart", "line", "Estimated energy (J)", rounds.map((r) => r.energy_j), "#ffb43c", { ...common, fill: true }),
    ].every(Boolean);
    return chartReady;
}

async function loadDashboard() {
    const requestId = ++dashboardRequestId;
    const button = byId("refresh-dashboard");
    button.disabled = true;
        setConnection("loading", "Đang kết nối…");
    showNotice("Đang tải dữ liệu tổng quan…");
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
        setConnection("connected", "Đã kết nối dữ liệu");
        showNotice(chartsAvailable ? "" : "Đã tải dữ liệu nhưng chưa tải được Chart.js để vẽ biểu đồ.", chartsAvailable ? "info" : "error");
    } catch (error) {
        if (requestId !== dashboardRequestId) return;
        console.error("Unable to load dashboard:", error);
        setConnection("error", "Không có dữ liệu");
        showNotice("Không tải được dữ liệu. Hãy kiểm tra backend/database rồi thử làm mới.", "error");
        byId("experiment-rows").innerHTML = '<tr><td class="empty-row" colspan="5">Không tải được dữ liệu thí nghiệm.</td></tr>';
        byId("alerts-list").innerHTML = '<div class="alert-item warning"><strong>Không kết nối được dashboard</strong><span>Backend hoặc database không phản hồi.</span></div>';
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
