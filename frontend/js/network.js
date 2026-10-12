const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const statusLabel = (status) => ({ACTIVE:"Đang hoạt động",INACTIVE:"Tạm dừng",OFFLINE:"Ngoại tuyến",FAILED:"Lỗi"}[String(status || "").toUpperCase()] || status || "Không rõ");
const layerColors = {SPACE:"#f4b85f",AIR:"#72d9ee",GROUND:"#83dfa8",SEA:"#8db5ff"};
let nodes = [];
let links = [];
let scenarios = [];
let selectedNodeIds = new Set();
let editingNode = null;
let detailNodeId = null;
let loadId = 0;

function notice(message, kind = "") {
    const element = $("network-notice");
    element.textContent = message;
    element.className = `notice${kind ? ` ${kind}` : ""}`;
}

async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: { Accept:"application/json", ...(options.body ? {"Content-Type":"application/json"} : {}), ...options.headers },
    });
    let payload;
    try { payload = await response.json(); } catch { payload = {}; }
    if (!response.ok || payload.status === "error") {
        const detail = payload.detail || payload.message || `Yêu cầu thất bại (${response.status}).`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return payload.data;
}

function visibleNodes() {
    const query = $("node-search").value.trim().toLocaleLowerCase();
    const type = $("node-type").value;
    const status = $("node-status").value;
    const scenario = $("node-scenario").value;
    return nodes.filter((node) =>
        (!type || node.type === type) &&
        (!status || String(node.status).toUpperCase() === status) &&
        (!scenario || String(node.scenario_id ?? "") === scenario) &&
        (!query || [node.id,node.country_name,node.country_code,node.platform,node.location_name,node.continent]
            .some((value) => String(value ?? "").toLocaleLowerCase().includes(query)))
    );
}

function updateSelectionControls(visible) {
    const count = selectedNodeIds.size;
    $("selection-count").textContent = `${count} node được chọn`;
    $("apply-bulk-status").disabled = count === 0 || !$("bulk-status").value;
    const selectVisible = $("select-visible");
    const selectedVisible = visible.filter((node) => selectedNodeIds.has(node.id)).length;
    selectVisible.checked = visible.length > 0 && selectedVisible === visible.length;
    selectVisible.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
}

function renderNodes() {
    const visible = visibleNodes();
    $("visible-node-count").textContent = visible.length;
    $("nodes-body").innerHTML = visible.length ? visible.map((node) => {
        const color = layerColors[node.type] || "#b5bdca";
        const country = node.country_name || node.country_code || "Chưa khai báo quốc gia";
        const location = [node.location_name,node.continent].filter(Boolean).join(" · ") || "—";
        const coordinate = `${Number(node.lat).toFixed(4)}, ${Number(node.lng).toFixed(4)}`;
        return `<tr>
            <td class="check-cell"><input type="checkbox" data-select-node="${esc(node.id)}" aria-label="Chọn node ${esc(node.id)}" ${selectedNodeIds.has(node.id) ? "checked" : ""}></td>
            <td><button type="button" class="node-open" data-inspect-node="${esc(node.id)}">${esc(node.id)}</button>${node.is_simulated ? '<small>Vị trí mô phỏng</small>' : ""}</td>
            <td><span class="node-layer"><span class="layer-dot" style="--layer-color:${color}"></span>${esc(node.type)}</span><small>${esc(node.platform || "Chưa khai báo platform")}</small></td>
            <td>${esc(country)}<small>${esc(location)}</small></td>
            <td>${coordinate}<small>${Number(node.alt).toLocaleString()} km độ cao</small></td>
            <td>${Number(node.bandwidth).toLocaleString()} Mbps<small>${Number(node.latency).toLocaleString()} ms · pin ${Number(node.battery_percent).toLocaleString()}%</small></td>
            <td><span class="status ${esc(String(node.status).toLowerCase())}" title="${esc(statusLabel(node.status))}">${esc(statusLabel(node.status))}</span></td>
            <td><div class="row-actions"><button type="button" class="secondary" data-edit-node="${esc(node.id)}" aria-label="Sửa ${esc(node.id)}" title="Chỉnh sửa"><i class="fa-solid fa-pen"></i></button></div></td>
        </tr>`;
    }).join("") : '<tr><td colspan="8" class="empty">Không có node khớp bộ lọc.</td></tr>';
    updateSelectionControls(visible);
}

function renderLinks() {
    $("link-total").textContent = links.length;
    const activeCount = links.filter((link) => String(link.status).toUpperCase() === "ACTIVE").length;
    $("link-active").textContent = activeCount;
    $("link-health-note").textContent = links.length ? `${links.length - activeCount} liên kết đang tạm dừng` : "Chưa có liên kết được lưu";
    $("links-body").innerHTML = links.length ? links.map((link) => `
        <tr>
            <td><strong>${esc(link.source)}</strong></td><td><strong>${esc(link.target)}</strong></td>
            <td>${Number(link.distance).toLocaleString(undefined,{maximumFractionDigits:1})} km</td>
            <td>${Number(link.bandwidth).toLocaleString()} Mbps</td><td>${Number(link.latency).toLocaleString()} ms</td>
            <td><span class="status ${esc(String(link.status).toLowerCase())}">${esc(statusLabel(link.status))}</span></td>
            <td><div class="row-actions"><button type="button" class="secondary" data-toggle-link="${link.id}" data-next-status="${String(link.status).toUpperCase() === "ACTIVE" ? "INACTIVE" : "ACTIVE"}">${String(link.status).toUpperCase() === "ACTIVE" ? "Tạm dừng" : "Kích hoạt"}</button><button type="button" class="danger" data-delete-link="${link.id}" aria-label="Xóa liên kết ${esc(link.source)}–${esc(link.target)}" title="Xóa liên kết"><i class="fa-solid fa-trash-can"></i></button></div></td>
        </tr>`).join("") : '<tr><td colspan="7" class="empty">Chưa có liên kết nào được lưu. Tạo liên kết để quản lý topology tường minh.</td></tr>';
}

function fillScenarioSelects() {
    const options = scenarios.map((scenario) => `<option value="${scenario.id}">${esc(scenario.name)}</option>`).join("");
    const selectedScenario = $("node-scenario").value;
    $("node-scenario").innerHTML = '<option value="">Tất cả scenario</option>' + options;
    if ([...$("node-scenario").options].some((option) => option.value === selectedScenario)) $("node-scenario").value = selectedScenario;
    $("form-node-scenario").innerHTML = '<option value="">Không gắn scenario</option>' + options;
    const currentSource = $("form-link-source").value;
    const currentTarget = $("form-link-target").value;
    const nodeOptions = nodes.map((node) => `<option value="${esc(node.id)}">${esc(node.id)} · ${esc(node.type)} · ${esc(node.country_name || node.location_name || "")}</option>`).join("");
    $("form-link-source").innerHTML = nodeOptions;
    $("form-link-target").innerHTML = nodeOptions;
    if ([...$("form-link-source").options].some((option) => option.value === currentSource)) $("form-link-source").value = currentSource;
    if ([...$("form-link-target").options].some((option) => option.value === currentTarget)) $("form-link-target").value = currentTarget;
}

async function load(showLoading = true) {
    const request = ++loadId;
    if (showLoading) notice("Đang đồng bộ node và liên kết…");
    $("refresh-network").disabled = true;
    try {
        const [nodeData, linkData, scenarioData] = await Promise.all([
            apiRequest("/api/nodes"),
            apiRequest("/api/links"),
            apiRequest("/api/simulations/scenarios").catch(() => []),
        ]);
        if (request !== loadId) return;
        nodes = Array.isArray(nodeData) ? nodeData : [];
        links = Array.isArray(linkData) ? linkData : [];
        scenarios = Array.isArray(scenarioData) ? scenarioData : [];
        const nodeIds = new Set(nodes.map((node) => node.id));
        selectedNodeIds = new Set([...selectedNodeIds].filter((id) => nodeIds.has(id)));
        fillScenarioSelects();
        $("node-total").textContent = nodes.length;
        const activeNodes = nodes.filter((node) => String(node.status).toUpperCase() === "ACTIVE").length;
        $("node-active").textContent = activeNodes;
        $("node-health-note").textContent = `${nodes.length - activeNodes} node không hoạt động`;
        renderNodes();
        renderLinks();
        notice(`Đã tải ${nodes.length} node và ${links.length} liên kết đã lưu.`, "success");
    } catch (error) {
        if (request !== loadId) return;
        notice(error.message || "Không thể tải dữ liệu network.", "error");
        $("nodes-body").innerHTML = '<tr><td colspan="8" class="empty">Không tải được dữ liệu node.</td></tr>';
        $("links-body").innerHTML = '<tr><td colspan="7" class="empty">Không tải được dữ liệu liên kết.</td></tr>';
    } finally {
        if (request === loadId) $("refresh-network").disabled = false;
    }
}

function showError(id, message) {
    const element = $(id);
    element.textContent = message;
    element.hidden = !message;
}

function setNodeFormMode(node = null) {
    editingNode = node;
    const form = $("node-form");
    form.reset();
    $("node-form-error").hidden = true;
    $("node-dialog-title").textContent = node ? `Chỉnh sửa ${node.id}` : "Thêm node";
    $("node-dialog-eyebrow").textContent = node ? "NODE CONFIGURATION" : "NETWORK INVENTORY";
    $("node-form-hint").textContent = node
        ? "Có thể cập nhật trạng thái và network profile. Vị trí node được giữ nguyên."
        : "Nhập vị trí WGS84 và thông số cơ bản để thêm node vào database.";
    $("save-node").innerHTML = node ? '<i class="fa-solid fa-check"></i> Lưu thay đổi' : '<i class="fa-solid fa-plus"></i> Thêm node';

    const editableOnCreateOnly = ["form-node-id","form-node-type","form-node-lat","form-node-lng","form-node-alt","form-node-scenario","form-node-country","form-node-location"];
    for (const id of editableOnCreateOnly) $(id).disabled = Boolean(node);
    if (node) {
        $("form-node-id").value = node.id;
        $("form-node-type").value = node.type;
        $("form-node-lat").value = node.lat;
        $("form-node-lng").value = node.lng;
        $("form-node-alt").value = node.alt;
        $("form-node-scenario").value = node.scenario_id ?? "";
        $("form-node-country").value = node.country_name || "";
        $("form-node-location").value = node.location_name || "";
        $("form-node-bandwidth").value = node.bandwidth;
        $("form-node-latency").value = node.latency;
        $("form-node-battery").value = node.battery_percent;
        $("form-node-status").value = String(node.status).toUpperCase();
    } else {
        $("form-node-status").value = "ACTIVE";
        $("form-node-scenario").value = $("node-scenario").value;
    }
    $("node-dialog").showModal();
}

function openNodeDetails(node) {
    detailNodeId = node.id;
    $("detail-node-title").textContent = node.id;
    const scenario = scenarios.find((item) => item.id === node.scenario_id)?.name || (node.scenario_id ? `#${node.scenario_id}` : "Chưa gắn");
    const fields = [
        ["Trạng thái", `<span class="status ${esc(String(node.status).toLowerCase())}">${esc(statusLabel(node.status))}</span>`],
        ["Layer / platform", `${esc(node.type)} · ${esc(node.platform || "Chưa khai báo")}`],
        ["Quốc gia", esc(node.country_name || node.country_code || "Chưa khai báo")],
        ["Vị trí", esc(node.location_name || "Chưa khai báo")],
        ["Tọa độ WGS84", `${Number(node.lat).toFixed(5)}, ${Number(node.lng).toFixed(5)}`],
        ["Độ cao", `${Number(node.alt).toLocaleString()} km`],
        ["Bandwidth / latency", `${Number(node.bandwidth).toLocaleString()} Mbps · ${Number(node.latency).toLocaleString()} ms`],
        ["Pin", `${Number(node.battery_percent).toLocaleString()}%`],
        ["Scenario", esc(scenario)],
        ["Nguồn vị trí", esc(node.coordinate_source || (node.is_simulated ? "Mô phỏng" : "Chưa khai báo"))],
        ["Heartbeat cuối", esc(node.last_heartbeat ? new Date(node.last_heartbeat).toLocaleString() : "Chưa có")],
    ];
    $("node-detail-content").innerHTML = fields.map(([label,value]) => `<div class="detail-field"><span>${label}</span><strong>${value}</strong></div>`).join("");
    $("node-detail-dialog").showModal();
}

function formNumber(formData, name) { return Number(formData.get(name)); }

async function saveNode(event) {
    event.preventDefault();
    const button = $("save-node");
    button.disabled = true;
    showError("node-form-error", "");
    try {
        const data = new FormData(event.currentTarget);
        const common = {
            bandwidth: formNumber(data,"bandwidth"), latency: formNumber(data,"latency"),
            battery_percent: formNumber(data,"battery_percent"), status: String(data.get("status")),
        };
        if (editingNode) {
            await apiRequest(`/api/nodes/${encodeURIComponent(editingNode.id)}`, { method:"PATCH", body:JSON.stringify(common) });
            $("node-dialog").close();
            notice(`Đã cập nhật cấu hình node ${editingNode.id}.`, "success");
        } else {
            const scenarioId = String(data.get("scenario_id") || "");
            const body = {
                id:String(data.get("id")).trim(), type:String(data.get("type")),
                lat:formNumber(data,"lat"), lng:formNumber(data,"lng"), alt:formNumber(data,"alt"),
                ...common, scenario_id:scenarioId ? Number(scenarioId) : null,
                country_name:String(data.get("country_name") || "").trim() || null,
                location_name:String(data.get("location_name") || "").trim() || null,
            };
            await apiRequest("/api/nodes", { method:"POST", body:JSON.stringify(body) });
            $("node-dialog").close();
            notice(`Đã thêm node ${body.id} vào topology.`, "success");
        }
        await load(false);
    } catch (error) {
        showError("node-form-error", error.message || "Không thể lưu node.");
    } finally { button.disabled = false; }
}

async function applyBulkStatus() {
    const status = $("bulk-status").value;
    const ids = [...selectedNodeIds];
    if (!status || !ids.length) return;
    $("apply-bulk-status").disabled = true;
    notice(`Đang cập nhật trạng thái cho ${ids.length} node…`);
    const outcomes = await Promise.allSettled(ids.map((id) => apiRequest(`/api/nodes/${encodeURIComponent(id)}`, { method:"PATCH", body:JSON.stringify({status}) })));
    const successes = outcomes.filter((item) => item.status === "fulfilled").length;
    const failures = outcomes.length - successes;
    selectedNodeIds.clear();
    $("bulk-status").value = "";
    await load(false);
    notice(failures ? `Đã cập nhật ${successes} node; ${failures} node lỗi, danh sách đã được làm mới.` : `Đã đổi trạng thái ${successes} node thành ${statusLabel(status)}.`, failures ? "error" : "success");
}

async function saveLink(event) {
    event.preventDefault();
    const button = $("save-link");
    button.disabled = true;
    showError("link-form-error", "");
    try {
        const data = new FormData(event.currentTarget);
        if (data.get("source") === data.get("target")) throw new Error("Source và target phải là hai node khác nhau.");
        const body = {source:data.get("source"),target:data.get("target"),bandwidth:Number(data.get("bandwidth")),latency:Number(data.get("latency")),status:data.get("status")};
        await apiRequest("/api/links", { method:"POST", body:JSON.stringify(body) });
        $("link-dialog").close();
        notice(`Đã tạo liên kết ${body.source} → ${body.target}; khoảng cách được tính từ tọa độ node.`, "success");
        await load(false);
    } catch (error) { showError("link-form-error", error.message || "Không thể tạo liên kết."); }
    finally { button.disabled = false; }
}

async function changeLinkStatus(id, status) {
    try {
        await apiRequest(`/api/links/${id}`, {method:"PATCH",body:JSON.stringify({status})});
        await load(false);
        notice(`Đã chuyển liên kết sang ${statusLabel(status)}.`, "success");
    } catch (error) { notice(error.message || "Không thể cập nhật liên kết.", "error"); }
}

async function removeLink(id) {
    const link = links.find((item) => Number(item.id) === Number(id));
    if (!link || !window.confirm(`Xóa liên kết ${link.source} ↔ ${link.target}? Node và dữ liệu huấn luyện không bị xóa.`)) return;
    try {
        await apiRequest(`/api/links/${id}`, {method:"DELETE"});
        await load(false);
        notice(`Đã xóa liên kết ${link.source} ↔ ${link.target}.`, "success");
    } catch (error) { notice(error.message || "Không thể xóa liên kết.", "error"); }
}

function exportCsv() {
    const rows = visibleNodes();
    if (!rows.length) { notice("Không có node trong bộ lọc hiện tại để xuất.", "error"); return; }
    const columns = ["id","type","platform","status","country_name","country_code","location_name","lat","lng","alt","bandwidth","latency","battery_percent","scenario_id","is_simulated"];
    const csvValue = (value) => `"${String(value ?? "").replaceAll('"','""')}"`;
    const content = "\uFEFF" + [columns.join(","), ...rows.map((node) => columns.map((column) => csvValue(node[column])).join(","))].join("\r\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], {type:"text/csv;charset=utf-8"}));
    link.download = "sagsins-network-nodes.csv";
    link.click();
    URL.revokeObjectURL(link.href);
    notice(`Đã xuất ${rows.length} node theo bộ lọc hiện tại.`, "success");
}

$("node-search").addEventListener("input", renderNodes);
$("node-type").addEventListener("change", renderNodes);
$("node-status").addEventListener("change", renderNodes);
$("node-scenario").addEventListener("change", renderNodes);
$("bulk-status").addEventListener("change", () => updateSelectionControls(visibleNodes()));
$("refresh-network").addEventListener("click", () => load());
$("export-nodes").addEventListener("click", exportCsv);
$("add-node").addEventListener("click", () => setNodeFormMode());
$("add-link").addEventListener("click", () => {
    $("link-form").reset();
    showError("link-form-error", "");
    fillScenarioSelects();
    if (nodes.length < 2) { notice("Cần ít nhất 2 node trước khi tạo liên kết.", "error"); return; }
    $("form-link-target").selectedIndex = Math.min(1, $("form-link-target").options.length - 1);
    $("link-dialog").showModal();
});
$("node-form").addEventListener("submit", saveNode);
$("link-form").addEventListener("submit", saveLink);
$("apply-bulk-status").addEventListener("click", applyBulkStatus);
$("clear-selection").addEventListener("click", () => { selectedNodeIds.clear();renderNodes(); });
$("select-visible").addEventListener("change", (event) => {
    visibleNodes().forEach((node) => event.target.checked ? selectedNodeIds.add(node.id) : selectedNodeIds.delete(node.id));
    renderNodes();
});
$("nodes-body").addEventListener("change", (event) => {
    const checkbox = event.target.closest("[data-select-node]");
    if (!checkbox) return;
    checkbox.checked ? selectedNodeIds.add(checkbox.dataset.selectNode) : selectedNodeIds.delete(checkbox.dataset.selectNode);
    renderNodes();
});
$("nodes-body").addEventListener("click", (event) => {
    const edit = event.target.closest("[data-edit-node]");
    const inspect = event.target.closest("[data-inspect-node]");
    if (edit) {
        const node = nodes.find((item) => item.id === edit.dataset.editNode);
        if (node) setNodeFormMode(node);
    } else if (inspect) {
        const node = nodes.find((item) => item.id === inspect.dataset.inspectNode);
        if (node) openNodeDetails(node);
    }
});
$("links-body").addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-toggle-link]");
    const remove = event.target.closest("[data-delete-link]");
    if (toggle) changeLinkStatus(toggle.dataset.toggleLink, toggle.dataset.nextStatus);
    if (remove) removeLink(remove.dataset.deleteLink);
});
$("edit-detail-node").addEventListener("click", () => {
    const node = nodes.find((item) => item.id === detailNodeId);
    if (!node) return;
    $("node-detail-dialog").close();
    setNodeFormMode(node);
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => $(button.dataset.closeDialog).close()));

load();
