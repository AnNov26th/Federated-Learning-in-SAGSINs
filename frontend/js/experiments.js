const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let experiments = [];
let scenarios = new Map();
function notice(message, kind = "") { const el = $("experiments-notice"); el.textContent = message; el.className = `notice${kind ? ` ${kind}` : ""}`; }
function render() {
    const query = $("experiment-search").value.trim().toLowerCase();
    const algorithm = $("experiment-algorithm").value;
    const status = $("experiment-status").value;
    const rows = experiments.filter((run) => {
        const scenario = scenarios.get(run.scenario_id) || `Scenario ${run.scenario_id}`;
        return (!algorithm || run.algorithm === algorithm) && (!status || run.status === status) && (!query || `${run.id} ${scenario} ${run.algorithm}`.toLowerCase().includes(query));
    });
    $("experiments-body").innerHTML = rows.length ? rows.map((run) => `<tr><td><strong>#${run.id}</strong></td><td>${esc(scenarios.get(run.scenario_id) || `Scenario ${run.scenario_id}`)}</td><td>${esc(run.algorithm)}<small>${esc(run.task)}</small></td><td>${run.completed_rounds}/${run.target_rounds} rounds</td><td>${run.task === "network_delay" ? (run.latest_mae_ms == null ? "—" : `${run.latest_mae_ms.toFixed(2)} ms MAE`) : run.latest_accuracy == null ? "—" : `${(run.latest_accuracy*100).toFixed(1)}%`}<small>future / test set</small></td><td><span class="status ${esc(String(run.status).toLowerCase())}">${esc(run.status)}</span>${run.error_message ? `<small>${esc(run.error_message)}</small>` : ""}</td><td><a href="/results.html?experiment_id=${encodeURIComponent(run.id)}">Analyze <i class="fa-solid fa-arrow-up-right-from-square"></i></a></td></tr>`).join("") : '<tr><td colspan="7" class="empty">No experiments match these filters.</td></tr>';
    $("runs-total").textContent = experiments.length;
    $("runs-completed").textContent = experiments.filter((run) => run.status === "COMPLETED").length;
    $("runs-active").textContent = experiments.filter((run) => ["QUEUED","RUNNING"].includes(run.status)).length;
    $("runs-unsuccessful").textContent = experiments.filter((run) => ["FAILED","CANCELLED"].includes(run.status)).length;
}
function exportCsv() {
    const quote = (value) => `"${String(value ?? "").replaceAll('"','""')}"`;
    const header = ["experiment_id","scenario","task","algorithm","status","completed_rounds","target_rounds","latest_test_accuracy","latest_mae_ms","latest_rmse_ms","actual_duration_s","error"];
    const lines = [header, ...experiments.map((run) => [run.id,scenarios.get(run.scenario_id) || run.scenario_id,run.task,run.algorithm,run.status,run.completed_rounds,run.target_rounds,run.latest_accuracy,run.latest_mae_ms,run.latest_rmse_ms,run.actual_duration_s,run.error_message])].map((row) => row.map(quote).join(","));
    const blob = new Blob(["\uFEFF",lines.join("\r\n")], {type:"text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const link = Object.assign(document.createElement("a"), {href:url,download:"sagsin-experiments.csv"});
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function load() {
    notice("Loading saved runs…");
    try {
        const [runResponse, scenarioResponse] = await Promise.all([fetch("/api/fl/experiments"), fetch("/api/simulations/scenarios")]);
        const [runPayload, scenarioPayload] = await Promise.all([runResponse.json(), scenarioResponse.json()]);
        if (!runResponse.ok || runPayload.status !== "success") throw new Error(runPayload.detail || "Could not load experiments.");
        if (!scenarioResponse.ok || scenarioPayload.status !== "success") throw new Error(scenarioPayload.detail || "Could not load scenarios.");
        experiments = runPayload.data || [];
        scenarios = new Map((scenarioPayload.data || []).map((scenario) => [scenario.id, scenario.name]));
        const algorithms = [...new Set(experiments.map((run) => run.algorithm))].sort();
        $("experiment-algorithm").innerHTML = '<option value="">All algorithms</option>' + algorithms.map((item) => `<option value="${esc(item)}">${esc(item)}</option>`).join("");
        render();
        notice(`${experiments.length} saved experiment${experiments.length === 1 ? "" : "s"}.`);
    } catch (error) { notice(error.message || "Experiment API is unavailable.", "error"); $("experiments-body").innerHTML = '<tr><td colspan="7" class="empty">Experiment data could not be loaded.</td></tr>'; }
}
$("experiment-search").addEventListener("input", render);
$("experiment-algorithm").addEventListener("change", render);
$("experiment-status").addEventListener("change", render);
$("refresh-experiments").addEventListener("click", load);
$("export-experiments").addEventListener("click", exportCsv);
load();
