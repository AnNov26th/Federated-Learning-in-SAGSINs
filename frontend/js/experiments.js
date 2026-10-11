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
    $("experiments-body").innerHTML = rows.length ? rows.map((run) => `<tr><td><strong>#${run.id}</strong></td><td>${esc(scenarios.get(run.scenario_id) || `Scenario ${run.scenario_id}`)}</td><td>${esc(run.algorithm)}</td><td>${run.completed_rounds}/${run.target_rounds} rounds</td><td>${run.latest_accuracy == null ? "—" : `${(run.latest_accuracy*100).toFixed(1)}%`}<small>test set</small></td><td><span class="status ${esc(String(run.status).toLowerCase())}">${esc(run.status)}</span>${run.error_message ? `<small>${esc(run.error_message)}</small>` : ""}</td><td><a href="/results.html?experiment_id=${encodeURIComponent(run.id)}">Analyze <i class="fa-solid fa-arrow-up-right-from-square"></i></a></td></tr>`).join("") : '<tr><td colspan="7" class="empty">No experiments match these filters.</td></tr>';
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
load();
