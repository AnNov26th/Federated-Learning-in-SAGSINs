const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let nodes = [];
let participants = [];
function notice(message, kind = "") { const el = $("participant-notice"); el.textContent = message; el.className = `notice${kind ? ` ${kind}` : ""}`; }
async function request(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok || payload.status !== "success") throw new Error(payload.detail || payload.message || `Request failed (${response.status}).`);
    return payload.data;
}
function render() {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const query = $("participant-search").value.trim().toLowerCase();
    const visible = participants.filter((participant) => {
        const node = nodeById.get(participant.node_id) || {};
        return [participant.node_id,node.country_name,node.country_code,node.type,node.platform].some((value) => String(value ?? "").toLowerCase().includes(query));
    });
    $("participants-body").innerHTML = visible.length ? visible.map((participant) => {
        const node = nodeById.get(participant.node_id) || {};
        const active = String(node.status).toUpperCase() === "ACTIVE";
        return `<tr><td><input type="checkbox" data-id="${participant.id}" data-field="selected" ${participant.selected ? "checked" : ""} ${active ? "" : "disabled"} aria-label="Select ${esc(participant.node_id)}"></td><td><strong>${esc(participant.node_id)}</strong><small>${esc(node.country_name || node.country_code)}</small></td><td>${esc(node.type)}<small>${esc(node.platform)}</small></td><td><span class="status ${esc(String(node.status || "unknown").toLowerCase())}">${esc(node.status)}</span></td><td><input type="number" min="1" max="20" value="${Number(participant.local_epochs) || 1}" data-id="${participant.id}" data-field="local_epochs" aria-label="Local epochs for ${esc(participant.node_id)}"></td><td>${Number(participant.dataset_size || 0).toLocaleString()}<small>Assigned at latest run</small></td></tr>`;
    }).join("") : '<tr><td colspan="6" class="empty">No participant records match this search.</td></tr>';
    $("participant-total").textContent = participants.length;
    $("participant-selected").textContent = participants.filter((p) => p.selected).length;
    $("participant-eligible").textContent = participants.filter((p) => p.selected && String(nodeById.get(p.node_id)?.status).toUpperCase() === "ACTIVE").length;
    $("participant-unregistered").textContent = nodes.filter((n) => !participants.some((p) => p.node_id === n.id)).length;
    const registered = new Set(participants.map((p) => p.node_id));
    const available = nodes.filter((node) => !registered.has(node.id));
    $("node-picker").innerHTML = available.length ? `<option value="">Choose a node…</option>${available.map((node) => `<option value="${esc(node.id)}">${esc(node.id)} · ${esc(node.country_name || node.type)} · ${esc(node.status)}</option>`).join("")}` : '<option value="">All nodes already have participant records</option>';
    $("participant-create").querySelector("button").disabled = !available.length;
}
async function load() {
    notice("Loading nodes and participant records…");
    try {
        [nodes, participants] = await Promise.all([request("/api/nodes"), request("/api/participants/")]);
        render();
        notice(`${participants.length} participant records loaded.`);
    } catch (error) {
        notice(error.message || "Participant API is unavailable.", "error");
        $("participants-body").innerHTML = '<tr><td colspan="6" class="empty">Participant data could not be loaded.</td></tr>';
        $("node-picker").innerHTML = '<option value="">Node data unavailable</option>';
        $("participant-create").querySelector("button").disabled = true;
    }
}
$("participant-search").addEventListener("input", render);
$("refresh-participants").addEventListener("click", load);
$("participants-body").addEventListener("change", async (event) => {
    const input = event.target.closest("[data-field]");
    if (!input) return;
    const field = input.dataset.field;
    const value = field === "selected" ? input.checked : Number(input.value);
    if (field === "local_epochs" && (!Number.isInteger(value) || value < 1 || value > 20)) { notice("Local epochs must be between 1 and 20.", "error"); render(); return; }
    input.disabled = true;
    try { await request(`/api/participants/${input.dataset.id}`, {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({[field]:value})}); notice("Participant settings saved.", "success"); await load(); }
    catch (error) { notice(error.message || "Could not save participant settings.", "error"); await load(); }
});
$("participant-create").addEventListener("submit", async (event) => {
    event.preventDefault();
    const nodeId = $("node-picker").value;
    if (!nodeId) return;
    try {
        await request("/api/participants/", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({node_id:nodeId,dataset_size:0,local_epochs:Number($("new-local-epochs").value),selected:false})});
        notice(`Participant ${nodeId} added to the pool.`, "success");
        await load();
    } catch (error) { notice(error.message || "Could not add participant.", "error"); }
});
load();
