const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = (value, digits = 2) => value == null ? "—" : Number(value).toFixed(digits);
let experiment, rawRows = [], chart, requestId = 0, currentRound;
async function api(url, options) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok || result.status !== "success") throw new Error(typeof result.detail === "string" ? result.detail : "The request failed. Please retry.");
    return result.data;
}
async function loadRaw() {
    if (!experiment?.dataset_id) return;
    const request = ++requestId;
    rawRows = []; $("predict-sample").disabled = true; $("inference-result").textContent = "";
    try {
        const params = new URLSearchParams({client_id:$("raw-client").value,split:$("raw-split").value,limit:20});
        const data = await api(`/api/fl/datasets/${experiment.dataset_id}/observations?${params}`);
        if (request !== requestId) return;
        rawRows = data.rows;
        $("raw-data").innerHTML = rawRows.map((r) => `<tr><td>${r.sequence}</td><td>${num(r.features.observed_delay_ms)}</td><td>${num(r.features.bandwidth_mbps)}</td><td>${num(r.features.load_ratio*100,1)}%</td><td>${num(r.features.packet_loss_ratio*100,2)}%</td><td>${num(r.target_delay_ms)}</td></tr>`).join("") || '<tr><td colspan="6">No samples in this partition.</td></tr>';
        $("predict-sample").disabled = !rawRows.length || !experiment.rounds.length;
    } catch (error) { if (request === requestId) $("inference-result").textContent = error.message; }
}
export async function renderNetworkDataset(run) {
    experiment = run;
    ++requestId;
    $("dataset-panel").hidden = run.task !== "network_delay";
    if (run.task !== "network_delay") return;
    try {
        const data = await api(`/api/fl/datasets/${run.dataset_id}`);
        if (experiment.id !== run.id) return;
        $("dataset-summary").textContent = `Generated dataset #${data.id} · ${data.generator_version} · seed ${data.seed} · ${data.client_count} clients · ${Object.entries(data.counts).map(([key,count]) => `${key}: ${count}`).join(" / ")}. Client partitions share one database. Test data occurs after online training. Snapshot: ${data.fingerprint.slice(0,16)}.`;
        $("raw-client").innerHTML = run.config.candidate_pool.map((id) => `<option>${esc(id)}</option>`).join("");
        await loadRaw();
    } catch (error) { $("dataset-summary").textContent = error.message; }
}
export function renderNetworkPredictions(run, round) {
    currentRound = round;
    $("prediction-panel").hidden = run?.task !== "network_delay";
    chart?.destroy(); chart = null;
    if (run?.task !== "network_delay") return;
    const m = round?.prediction_metrics, predictions = round?.predictions || [];
    $("prediction-summary").textContent = m ? `Selection: ${m.selection_source}. Future test MAE ${num(m.mae_ms)} ms; RMSE ${num(m.rmse_ms)} ms; R² ${num(m.r2,4)}. Persistence baseline MAE ${num(m.persistence_mae_ms)} ms. Test samples: ${m.test_samples}. Predictions used the previous model before local training. Unselected next-tick labels are hidden.` : "No prediction round saved yet.";
    $("prediction-results").innerHTML = predictions.map((p) => `<tr><td>${esc(p.client_id)}</td><td>${p.selected ? "Yes" : "No"}</td><td>${num(p.predicted_delay_ms)}</td><td>${p.observed_delay_ms == null ? "Not selected" : num(p.observed_delay_ms)}</td><td>${num(p.rule_delay_ms)}</td><td>${p.model_round}${p.model_round === 0 ? " (initialization)" : ""}</td><td>${p.observation_id}</td></tr>`).join("");
    if (typeof Chart !== "undefined" && predictions.length) chart = new Chart($("prediction-chart"), {
        type:"line",data:{labels:predictions.map((p) => p.client_id),datasets:[
            {label:"Predicted delay (ms)",data:predictions.map((p) => p.predicted_delay_ms),borderColor:"#ffb43c",borderDash:[6,4],pointStyle:"triangle"},
            {label:"Observed after selection (ms)",data:predictions.map((p) => p.observed_delay_ms),borderColor:"#48d9ff",spanGaps:false},
        ]},options:{responsive:true,maintainAspectRatio:false,animation:!matchMedia("(prefers-reduced-motion: reduce)").matches,scales:{y:{beginAtZero:true}}},
    });
}
$("raw-client").addEventListener("change",loadRaw);
$("raw-split").addEventListener("change",loadRaw);
$("predict-sample").addEventListener("click", async () => {
    if (!rawRows.length) return;
    $("predict-sample").disabled = true;
    try {
        const result = await api(`/api/fl/experiments/${experiment.id}/predict`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(rawRows[0].features)});
        $("inference-result").textContent = `Saved model round ${result.model_round}: predicted ${num(result.predicted_delay_ms)} ms; sample target ${num(rawRows[0].target_delay_ms)} ms. This preview does not train the model.`;
    } catch (error) { $("inference-result").textContent = error.message; }
    finally { $("predict-sample").disabled = false; }
});
$("export-predictions").addEventListener("click", () => {
    if (!currentRound) return;
    const rows = [["round","client_id","selected","predicted_delay_ms","observed_delay_ms","rule_delay_ms","model_round","observation_id"],...currentRound.predictions.map((p) => [currentRound.round,p.client_id,p.selected,p.predicted_delay_ms,p.observed_delay_ms,p.rule_delay_ms,p.model_round,p.observation_id])];
    const csv = rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"','""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF",csv],{type:"text/csv;charset=utf-8"}));
    Object.assign(document.createElement("a"),{href:url,download:`experiment-${experiment.id}-decisions.csv`}).click();
    setTimeout(() => URL.revokeObjectURL(url),1000);
});
