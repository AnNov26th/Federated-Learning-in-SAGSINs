const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let nodes = [];
function notice(message, kind = "") { const el = $("network-notice"); el.textContent = message; el.className = `notice${kind ? ` ${kind}` : ""}`; }
function renderNodes() {
    const query = $("node-search").value.trim().toLowerCase();
    const type = $("node-type").value;
    const status = $("node-status").value;
    const visible = nodes.filter((node) => (!type || node.type === type) && (!status || String(node.status).toUpperCase() === status) && (!query || [node.id,node.country_name,node.country_code,node.platform,node.location_name,node.continent].some((value) => String(value ?? "").toLowerCase().includes(query))));
    $("nodes-body").innerHTML = visible.length ? visible.map((node) => `<tr><td><strong>${esc(node.id)}</strong>${node.is_simulated ? '<small>Simulated location</small>' : ""}</td><td>${esc(node.type)}<small>${esc(node.platform)}</small></td><td>${esc(node.country_name || node.country_code)}<small>${esc(node.location_name || node.continent)}</small></td><td>${Number(node.lat).toFixed(4)}, ${Number(node.lng).toFixed(4)}</td><td>${Number(node.alt).toLocaleString()} km</td><td>${esc(node.bandwidth)} Mbps<small>${esc(node.latency)} ms latency</small></td><td><span class="status ${esc(String(node.status).toLowerCase())}">${esc(node.status)}</span></td></tr>`).join("") : '<tr><td colspan="7" class="empty">No nodes match these filters.</td></tr>';
}
async function load() {
    notice("Loading network data…");
    try {
        const nodeResponse = await fetch("/api/nodes");
        const nodePayload = await nodeResponse.json();
        if (!nodeResponse.ok || nodePayload.status !== "success") throw new Error(nodePayload.detail || "Could not load nodes.");
        nodes = nodePayload.data || [];
        $("node-total").textContent = nodes.length;
        $("node-active").textContent = nodes.filter((node) => String(node.status).toUpperCase() === "ACTIVE").length;
        renderNodes();
        try {
            const linkResponse = await fetch("/api/links");
            const linkPayload = await linkResponse.json();
            if (!linkResponse.ok || linkPayload.status !== "success") throw new Error(linkPayload.detail || "Could not load links.");
            const links = linkPayload.data || [];
            $("link-total").textContent = links.length;
            $("link-active").textContent = links.filter((link) => String(link.status).toUpperCase() === "ACTIVE").length;
            $("links-body").innerHTML = links.length ? links.map((link) => `<tr><td>${esc(link.source)}</td><td>${esc(link.target)}</td><td>${Number(link.distance).toLocaleString()} km</td><td>${esc(link.bandwidth)} Mbps</td><td>${esc(link.latency)} ms</td><td><span class="status ${esc(String(link.status).toLowerCase())}">${esc(link.status)}</span></td></tr>`).join("") : '<tr><td colspan="6" class="empty">No network links are stored for this topology.</td></tr>';
            notice(`Loaded ${nodes.length} nodes and ${links.length} stored links.`);
        } catch (linkError) {
            $("link-total").textContent = "—";
            $("link-active").textContent = "—";
            $("links-body").innerHTML = '<tr><td colspan="6" class="empty">Link data could not be loaded.</td></tr>';
            notice(`Loaded ${nodes.length} nodes; links are unavailable: ${linkError.message}`, "error");
        }
    } catch (error) {
        notice(error.message || "Network API is unavailable.", "error");
        $("nodes-body").innerHTML = '<tr><td colspan="7" class="empty">Node data could not be loaded.</td></tr>';
        $("links-body").innerHTML = '<tr><td colspan="6" class="empty">Link data could not be loaded.</td></tr>';
    }
}
$("node-search").addEventListener("input", renderNodes);
$("node-type").addEventListener("change", renderNodes);
$("node-status").addEventListener("change", renderNodes);
$("refresh-network").addEventListener("click", load);
load();
