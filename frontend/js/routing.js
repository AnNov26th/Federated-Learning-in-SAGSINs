import * as THREE from 'three';
import { latLngToVector3 } from './3d/coordinates.js';

const $ = id => document.getElementById(id);
const html = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const number = value => Number.isFinite(value) ? value.toFixed(1) : '—';
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

async function api(path, options) {
    const response = await fetch(path, options);
    const payload = await response.json();
    if (!response.ok || payload.status !== 'success') throw new Error(typeof payload.detail === 'string' ? payload.detail : payload.message || 'Không thể tải dữ liệu định tuyến.');
    return payload.data;
}

export function setupRouting({ scene3D, nodeMarkers, droppedMarkers, createMarker, flyGlobeToMarker,
    resetGlobeView, selectedNodeSummary, actionSelect, actionHint, container, topologyReady, refreshNodes }) {
    let nextId = 1, selectedId = null, generation = 0, context = { scenarios: [], models: [] }, refreshing = false;
    let showBaseline = false, replayStart = performance.now();
    const drawings = new Map();
    const status = message => { $('routing-status').textContent = message; };
    const activeDrop = () => droppedMarkers.find(d => d.id === selectedId);
    const config = () => ({ scenario_id: Number($('routing-scenario').value), policy: $('routing-policy').value,
        experiment_id: Number($('routing-model').value) || null, target_id: $('routing-target').value || null,
        topology: $('routing-topology').value, access_radius_km: Number($('routing-radius').value),
        load_ratio: Number($('routing-load').value) / 100 });

    function validConfig() {
        return Boolean($('routing-scenario').value) && $('routing-radius').checkValidity();
    }

    function updateOptions() {
        const scenario = Number($('routing-scenario').value);
        const modelId = $('routing-model').value, targetId = $('routing-target').value;
        const models = context.models.filter(m => m.scenario_id === scenario);
        $('routing-model').innerHTML = '<option value="">Tự chọn checkpoint mới nhất</option>' + models.map(m => `<option value="${m.experiment_id}">#${m.experiment_id} · ${html(m.algorithm)} · round ${m.round}</option>`).join('');
        if (models.some(m => String(m.experiment_id) === modelId)) $('routing-model').value = modelId;
        $('routing-model').disabled = $('routing-policy').value === 'static';
        const model = models.find(m => String(m.experiment_id) === $('routing-model').value) || models[0];
        $('routing-model-status').textContent = $('routing-policy').value === 'static' ? 'Đối chứng bằng công thức truyền FL, không suy luận model.' : model
            ? `Model #${model.experiment_id} · MAE ${number(model.mae_ms)} ms${model.beats_persistence ? '' : ' · Chưa tốt hơn persistence trên tập test'}`
            : 'Chưa có model phù hợp. Huấn luyện Network delay trong FL Training cho scenario này.';
        const targets = nodeMarkers.filter(m => m.userData.scenario_id === scenario && m.userData.type === 'GROUND' && m.userData.status?.toUpperCase() === 'ACTIVE');
        $('routing-target').innerHTML = '<option value="">Tự chọn GROUND có chi phí thấp nhất</option>' + targets.map(m => `<option value="${html(m.userData.id)}">${html(m.userData.id)}</option>`).join('');
        if (targets.some(m => m.userData.id === targetId)) $('routing-target').value = targetId;
        for (const marker of nodeMarkers) marker.visible = marker.userData.scenario_id === scenario;
    }

    async function loadContext() {
        context = await api('/api/routing/context');
        const previous = $('routing-scenario').value;
        $('routing-scenario').innerHTML = context.scenarios.map(s => `<option value="${s.id}">${html(s.name)} (#${s.id})</option>`).join('') || '<option value="">Chưa có scenario</option>';
        if (context.scenarios.some(s => String(s.id) === previous)) $('routing-scenario').value = previous;
        else if (context.models[0]) $('routing-scenario').value = context.models[0].scenario_id;
        updateOptions();
    }

    function disposeObject(object) {
        object.traverse(child => {
            child.geometry?.dispose();
            if (child.material) {
                for (const material of Array.isArray(child.material) ? child.material : [child.material]) {
                    material.map?.dispose(); material.dispose();
                }
            }
        });
        object.removeFromParent();
    }

    function disposeRoute(id) {
        const drawing = drawings.get(id);
        if (drawing) disposeObject(drawing.group);
        drawings.delete(id);
    }

    function arc(from, to) {
        const points = [], a = from.clone().normalize(), b = to.clone().normalize();
        const rotation = new THREE.Quaternion().setFromUnitVectors(a, b);
        const steps = Math.max(12, Math.ceil(a.angleTo(b) * 24));
        for (let step = 0; step <= steps; step++) {
            const t = step / steps;
            points.push(a.clone().applyQuaternion(new THREE.Quaternion().slerp(rotation, t))
                .multiplyScalar(THREE.MathUtils.lerp(from.length(), to.length(), t) + .025 + Math.sin(Math.PI*t)*.06));
        }
        return points;
    }

    function routePoints(drop, route) {
        const positions = [drop.marker.position.clone(), ...route.positions.map(n => latLngToVector3(n.lat, n.lng, n.alt))];
        const segments = positions.slice(1).map((to, i) => arc(positions[i], to));
        return { access: segments[0], backbone: segments.slice(1).flat(), all: segments.flat() };
    }

    function drawRoute(drop) {
        disposeRoute(drop.id);
        if (!drop.route) return;
        const group = new THREE.Group(), points = routePoints(drop, drop.route);
        const addLine = (positions, color, dashed = false) => {
            if (positions.length < 2) return;
            const material = dashed ? new THREE.LineDashedMaterial({ color, dashSize:.035, gapSize:.025, transparent:true, opacity:.9 })
                : new THREE.LineBasicMaterial({ color, transparent:true, opacity:.95 });
            const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(positions), material);
            if (dashed) line.computeLineDistances();
            group.add(line);
        };
        addLine(points.access, 0xe9b670, true);
        addLine(points.backbone, drop.action === 'Emergency' ? 0xff7c91 : 0x73dcf0);
        const baseline = new THREE.Group();
        if (drop.result.baseline && !drop.result.comparison?.same_path && drop.result.policy === 'predictive') {
            const baselinePoints = routePoints(drop, drop.result.baseline);
            const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(baselinePoints.backbone), new THREE.LineDashedMaterial({ color:0xb4a0ef, dashSize:.045, gapSize:.03, transparent:true, opacity:.6 }));
            line.computeLineDistances(); baseline.add(line);
        }
        group.add(baseline);
        const packet = new THREE.Mesh(new THREE.SphereGeometry(.018, 10, 10), new THREE.MeshBasicMaterial({ color:0xffffff }));
        group.add(packet);
        scene3D.earth.add(group);
        drawings.set(drop.id, { group, baseline, packet, points:points.all });
        syncSelection();
    }

    function syncSelection() {
        const drop = activeDrop();
        const scenarioId = Number($('routing-scenario').value);
        scene3D.earth.userData.routingSnapshot = Boolean(drop?.route && drop.config.scenario_id === scenarioId);
        for (const event of droppedMarkers) event.marker.visible = event.config.scenario_id === scenarioId;
        for (const [id, drawing] of drawings) {
            const selected = id === selectedId;
            drawing.group.visible = droppedMarkers.find(d => d.id === id)?.config.scenario_id === Number($('routing-scenario').value);
            drawing.group.traverse(child => { if (child.material) child.material.opacity = selected ? .95 : .18; });
            drawing.baseline.visible = selected && showBaseline;
            drawing.packet.visible = selected && !reducedMotion.matches;
        }
        if (drop?.route) {
            // Route topology and visual endpoints share the same DB snapshot.
            for (const marker of nodeMarkers) {
                const n = marker.userData;
                marker.position.copy(latLngToVector3(n.lat, n.lng, n.alt));
            }
            const markersById = new Map(nodeMarkers.map(marker => [marker.userData.id, marker]));
            for (const node of drop.route.positions) markersById.get(node.id)?.position.copy(latLngToVector3(node.lat,node.lng,node.alt));
        }
    }

    scene3D.earth.userData.advanceRoutes = () => {
        const drawing = drawings.get(selectedId);
        if (!drawing || reducedMotion.matches) return;
        const t = ((performance.now() - replayStart) % 5000) / 5000;
        const scaled = t * (drawing.points.length - 1), index = Math.floor(scaled);
        if (drawing.points[index]) drawing.packet.position.copy(drawing.points[index]).lerp(drawing.points[Math.min(index+1,drawing.points.length-1)], scaled-index);
    };

    function renderInspector() {
        const drop = activeDrop();
        $('route-state').dataset.state = drop?.result?.status || 'pending';
        $('route-state').textContent = !drop ? 'Chờ điểm đặt' : drop.pending ? 'Đang tính' : drop.route ? 'Có tuyến' : 'Chưa có tuyến';
        $('route-summary').textContent = !drop ? 'Chọn sự kiện rồi nhấn lên địa cầu để bắt đầu.'
            : drop.pending ? `${drop.name} · Đang tính tuyến…`
            : drop.route ? `${drop.name} · ${drop.action} · ${drop.route.hop_count} hop · ${number(drop.result.policy === 'predictive' ? drop.route.predicted_transfer_ms : drop.route.static_transfer_ms)} ms · Xem chi tiết trong Phân tích tuyến`
            : `${drop.name} · ${drop.action} · Chưa có tuyến · Mở Phân tích tuyến để xem nguyên nhân.`;
        $('route-inspector-title').textContent = drop ? `${drop.name} · ${drop.action}` : 'Từ sự kiện đến GROUND';
        if (!drop) {
            $('route-inspector-content').innerHTML = '<div class="routing-empty"><i class="fa-solid fa-route" aria-hidden="true"></i><h3>Quan sát cách mạng chọn đường</h3><p>Chọn sự kiện rồi đặt điểm trên địa cầu, hoặc nhập tọa độ trong cấu hình.</p></div>';
            return;
        }
        const result = drop.result, route = drop.route;
        if (!route) {
            $('route-inspector-content').innerHTML = `<p class="route-caption ${drop.pending ? '' : 'routing-error'}">${html(drop.status)}</p>${result?.access ? `<p class="route-caption">Node tiếp cận: <strong>${html(result.access.source_id)}</strong> · ${number(result.access.distance_km)} km</p>` : ''}${result?.diagnostics ? `<p class="route-caption">${result.diagnostics.active_nodes} node ACTIVE · ${result.diagnostics.links} link · ${result.diagnostics.eligible_directions} hướng truyền thỏa điều kiện.</p>` : ''}${result?.code === 'no_model' ? '<button id="routing-train" class="action-btn" type="button">Mở FL Training</button>' : ''}${drop.pending ? '' : '<p class="route-caption">Kiểm tra scenario, checkpoint, vùng tiếp cận và link ACTIVE; sau đó nhấn “Cập nhật mạng & tính lại”.</p>'}`;
            return;
        }
        const model = result.model, predictive = result.policy === 'predictive', baseline = result.baseline;
        $('route-inspector-content').innerHTML = `
            <p class="route-caption">${predictive ? `<strong>FL #${model.experiment_id} · ${html(model.algorithm)} · round ${model.round}</strong>` : '<strong>Công thức tĩnh · đối chứng</strong>'}<br>${result.topology === 'estimated' ? 'Topology ước tính · không lưu link' : 'Link ACTIVE đã lưu'} · scenario #${result.scenario_id}</p>
            <dl class="route-metrics"><div><dt>${predictive ? 'Tổng RTT dự đoán / hop' : 'Tổng RTT công thức / hop'}</dt><dd>${number(predictive ? route.predicted_transfer_ms : route.static_transfer_ms)} <small>ms*</small></dd></div><div><dt>Băng thông nút thắt</dt><dd>${number(route.bottleneck)} <small>Mbps</small></dd></div><div><dt>Chặng mạng</dt><dd>${route.hop_count} <small>hop + 1 tiếp cận</small></dd></div><div><dt>Tiếp cận ước tính</dt><dd>${number(route.accessDistanceKm)} <small>km</small></dd></div></dl>
            <p class="route-caption">Điểm → node ACTIVE gần nhất → GROUND có tổng chi phí nhỏ nhất. Ngưỡng dịch vụ: ≥ ${result.profile.min_bandwidth} Mbps sau khi áp dụng tải ${Math.round(drop.config.load_ratio*100)}%.</p>
            <ol class="route-hop-list"><li><span class="hop-number">•</span><div><strong>Điểm sự kiện</strong><small>${drop.lat.toFixed(3)}°, ${drop.lng.toFixed(3)}° · tiếp cận không tính vào điểm model</small></div></li>${route.positions.map((node, index) => `<li><span class="hop-number">${index+1}</span><div><strong>${html(node.id)} · ${html(node.type)}</strong><small>${index === 0 ? 'Node tiếp cận · chọn theo khoảng cách và đường chân trời' : `${number(route.hops[index-1].predicted_ms ?? route.hops[index-1].static_ms)} ms RTT/hop · ${number(route.hops[index-1].bandwidth_mbps)} Mbps`}${index === route.positions.length-1 ? ' · đích' : ''}</small></div></li>`).join('')}</ol>
            ${predictive ? `<div class="route-comparison"><h3>Đối chiếu trên cùng topology & tải</h3><p>Tuyến công thức: ${baseline.path.map(html).join(' → ')}</p><p>Model chấm tuyến công thức: <strong>${number(baseline.predicted_transfer_ms)} ms*</strong><br>Model chấm tuyến được chọn: <strong>${number(route.predicted_transfer_ms)} ms*</strong></p><p>${result.comparison.same_path ? 'Hai chính sách chọn cùng tuyến.' : `Hai chính sách chọn khác tuyến. Chênh lệch chỉ số RTT dự đoán: ${number(result.comparison.predicted_cost_change)} ms (điểm tối ưu còn có thành phần băng thông).`}</p>${!result.comparison.same_path ? `<label><input id="routing-show-baseline" type="checkbox" ${showBaseline ? 'checked' : ''}> Hiện tuyến công thức trên địa cầu</label>` : ''}<p>MAE test ${number(model.mae_ms)} ms · validation ${number(model.validation_mae_ms)} ms<br>${model.beats_persistence ? 'Model tốt hơn persistence trên tập test.' : 'Model chưa tốt hơn persistence trên tập test.'}</p></div>` : ''}
            <div class="route-legend"><span>Tiếp cận</span><span>Tuyến chọn</span><span>Đối chứng</span></div>
            <button class="action-btn routing-replay" id="routing-replay" type="button"><i class="fa-solid fa-play" aria-hidden="true"></i> Xem lại luồng truyền minh họa</button>
            <p class="route-caption">Hoạt ảnh 5 giây/lượt. Vị trí thiết bị tạm dừng theo snapshot DB khi xem tuyến.<br>Cập nhật: ${html(new Date(result.snapshot_at).toLocaleTimeString('vi-VN'))}</p>
            <p class="route-note">* ${html(result.note)} Payload ${result.payload_bytes} byte. Chặng tiếp cận chưa có telemetry nên không đưa vào tổng RTT. ${result.unseen_layers?.length ? `Lớp chưa có trong dữ liệu huấn luyện: ${result.unseen_layers.map(html).join(', ')}.` : ''}</p>
            <details class="routing-explanation"><summary>Công thức & dữ liệu quyết định</summary><p>${html(result.objective)}<br>w_delay = ${result.profile.latency_weight}; w_capacity = ${result.profile.capacity_weight}. Điểm tuyến: ${number(route.cost)}.<br>${result.diagnostics.active_nodes} node · ${result.diagnostics.links} link · ${result.diagnostics.eligible_directions} hướng truyền hợp lệ.</p><p>Input mỗi hop: lớp node nhận, latency, bandwidth, khoảng cách, tải, loss, jitter, payload và RTT công thức. Dự đoán batch một lần; không dùng nhãn tương lai của dataset.</p></details>`;
    }

    function renderDroppedMarkers() {
        $('drop-count').textContent = `${droppedMarkers.length} điểm · ${droppedMarkers.filter(d => d.route).length} có tuyến`;
        $('drop-list').innerHTML = droppedMarkers.length ? droppedMarkers.map(drop => `
            <article class="drop-item${drop.id === selectedId ? ' selected' : ''}" role="listitem">
                <button class="drop-info" type="button" data-inspect-drop="${drop.id}" aria-pressed="${drop.id === selectedId}"><span class="drop-name-row"><span class="drop-name">${html(drop.name)} · ${html(drop.action)}</span><span class="drop-status">${drop.pending ? 'Đang tính' : drop.route ? `${drop.route.hop_count} hop` : 'Chưa có tuyến'}</span></span><span class="drop-detail">${drop.lat.toFixed(2)}°, ${drop.lng.toFixed(2)}° · scenario #${drop.config.scenario_id}</span></button>
                <button class="drop-delete" type="button" data-delete-drop="${drop.id}" aria-label="Xóa ${html(drop.name)}"><i class="fa-solid fa-trash-can" aria-hidden="true"></i></button>
            </article>`).join('') : '<div class="drop-empty"><i class="fa-solid fa-location-dot" aria-hidden="true"></i><span>Chưa có sự kiện</span><small>Chọn sự kiện và đặt điểm trên địa cầu</small></div>';
        renderInspector();
        syncSelection();
    }

    async function compute(drop, token) {
        const requestId = drop.requestId = (drop.requestId || 0) + 1;
        drop.pending = true; drop.status = 'Đang tính tuyến…'; drop.route = null; drop.result = null;
        disposeRoute(drop.id); renderDroppedMarkers();
        try {
            const result = await api('/api/routing/event', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ ...drop.config, lat:drop.lat, lng:drop.lng, service:drop.action }) });
            if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
            drop.result = result; drop.route = result.route; drop.status = result.reason;
            drawRoute(drop);
        } catch (error) {
            if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
            drop.status = `Lỗi tính tuyến: ${error.message}`;
        }
        if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
        drop.pending = false; renderDroppedMarkers();
        status(`${drop.name}: ${drop.status}`);
    }

    async function addEvent(lat, lng, service, marker) {
        if (refreshing) { if (marker) disposeObject(marker); status('Đang cập nhật mạng. Chờ tính lại xong trước khi thêm sự kiện.'); return; }
        if (!validConfig()) { if (marker) disposeObject(marker); status('Chọn scenario và bán kính tiếp cận hợp lệ.'); return; }
        if (!service) { if (marker) disposeObject(marker); status('Chọn loại sự kiện trước khi đặt điểm.'); return; }
        if (!marker) { marker = createMarker(0xff00ff,255,0,255,1.2); marker.position.copy(latLngToVector3(lat,lng)); scene3D.earth.add(marker); }
        const id = nextId++;
        const drop = { id, name:`Điểm ${String(id).padStart(2,'0')}`, action:service, lat, lng, marker,
            config:config(), pending:true, status:'Đang tính tuyến…', route:null, focused:true };
        droppedMarkers.forEach(d => { d.focused = false; }); droppedMarkers.push(drop); selectedId = id;
        actionSelect.value = ''; actionHint.style.display = 'none'; container.style.cursor = 'default';
        // Keep the globe visible while routes are computed; analysis is opt-in.
        renderDroppedMarkers();
        await compute(drop, generation);
    }

    async function refreshDroppedRoutes() {
        if (refreshing) return;
        if (!validConfig()) { status('Chọn scenario và bán kính tiếp cận hợp lệ trước khi tính lại.'); return; }
        refreshing = true; $('routing-refresh').disabled = true;
        const token = ++generation;
        const appliedConfig = config();
        for (const drop of droppedMarkers) { drop.route = null; drop.pending = true; disposeRoute(drop.id); }
        renderDroppedMarkers(); status('Đang cập nhật topology, checkpoint và tính lại tuyến…');
        try {
            await refreshNodes(); await loadContext();
            $('backend-status').textContent = 'Connected';
            for (const drop of [...droppedMarkers]) {
                // Controls apply to all events when the user explicitly recomputes.
                drop.config = appliedConfig;
                await compute(drop, token);
            }
            status(`Đã cập nhật: ${droppedMarkers.filter(d => d.route).length}/${droppedMarkers.length} điểm có tuyến.`);
        } catch (error) {
            for (const drop of droppedMarkers) { drop.pending = false; drop.status = `Không cập nhật được mạng: ${error.message}`; }
            status(`Không cập nhật được mạng: ${error.message}`); renderDroppedMarkers();
        } finally { refreshing = false; $('routing-refresh').disabled = false; }
    }

    function select(drop) {
        selectedId = drop.id; replayStart = performance.now();
        droppedMarkers.forEach(d => { d.focused = d === drop; });
        renderDroppedMarkers(); setPanel('route');
    }
    function focusDroppedMarker(drop) {
        select(drop); flyGlobeToMarker(drop.marker, 4.75);
        if (selectedNodeSummary) selectedNodeSummary.textContent = `${drop.name} · ${drop.action}`;
    }
    $('drop-list').addEventListener('click', event => {
        const button = event.target.closest('button'); if (!button) return;
        const id = Number(button.dataset.deleteDrop || button.dataset.focusDrop || button.dataset.inspectDrop);
        const drop = droppedMarkers.find(d => d.id === id); if (!drop) return;
        if (button.dataset.deleteDrop) {
            disposeRoute(id); disposeObject(drop.marker); droppedMarkers.splice(droppedMarkers.indexOf(drop),1);
            if (selectedId === id) selectedId = droppedMarkers.at(-1)?.id ?? null;
            renderDroppedMarkers();
        } else if (button.dataset.focusDrop) focusDroppedMarker(drop);
        else focusDroppedMarker(drop);
    });
    $('route-inspector-content').addEventListener('change', event => {
        if (event.target.id === 'routing-show-baseline') { showBaseline = event.target.checked; syncSelection(); }
    });
    $('route-inspector-content').addEventListener('click', event => {
        if (event.target.closest('#routing-train')) window.postMessage({ type:'sagsin:navigate',href:'/fl.html' },window.location.origin);
        if (event.target.closest('#routing-replay')) { replayStart = performance.now(); const drop = activeDrop(); if (drop) flyGlobeToMarker(drop.marker,5.4); }
    });
    $('routing-refresh').addEventListener('click', refreshDroppedRoutes);
    for (const id of ['routing-scenario','routing-policy','routing-model','routing-target','routing-topology','routing-radius','routing-load']) {
        $(id).addEventListener('change', () => {
            if (['routing-scenario','routing-policy','routing-model'].includes(id)) updateOptions();
            if (id === 'routing-scenario' && activeDrop()?.config.scenario_id !== Number($('routing-scenario').value)) {
                selectedId = null; renderDroppedMarkers();
            }
            status('Cấu hình áp dụng cho điểm mới. Nhấn cập nhật để tính lại các điểm hiện có.');
            syncSelection();
        });
    }
    $('routing-load').addEventListener('input', () => { $('routing-load-value').textContent = `${$('routing-load').value}%`; });
    $('routing-coordinate-form').addEventListener('submit', event => {
        event.preventDefault(); addEvent(Number($('event-lat').value),Number($('event-lng').value),actionSelect.value);
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            if (actionSelect.value) { actionSelect.value = ''; actionHint.style.display = 'none'; container.style.cursor = 'default'; }
            else setPanel(null, true);
        }
    });
    let openPanel = null, visible = true;
    function setPanel(panel, restoreFocus = false) {
        const previous = openPanel;
        openPanel = panel;
        $('simulation-workspace').dataset.panel = panel || '';
        $('simulation-dock').hidden = !panel || !visible;
        $('action-panel').hidden = panel !== 'config';
        $('route-inspector').hidden = panel !== 'route';
        document.querySelectorAll('[data-simulation-panel]').forEach(button => {
            button.setAttribute('aria-expanded', String(button.dataset.simulationPanel === panel && visible));
        });
        if (panel) $('btn-close-panel').focus({ preventScroll:true });
        else if (restoreFocus && previous) document.querySelector(`[data-simulation-panel="${previous}"]`).focus({ preventScroll:true });
    }
    document.querySelectorAll('[data-simulation-panel]').forEach(button => button.addEventListener('click', () => {
        setPanel(openPanel === button.dataset.simulationPanel ? null : button.dataset.simulationPanel, true);
    }));
    $('btn-close-panel').addEventListener('click', () => setPanel(null, true));
    setPanel(null);
    function setVisible(value) {
        visible = value;
        // Returning to Simulation starts with the full globe again.
        setPanel(null);
    }
    const ready = topologyReady.then(loadContext).then(() => { $('backend-status').textContent = 'Connected'; status('Sẵn sàng. Chọn sự kiện rồi đặt điểm trên địa cầu.'); })
        .catch(error => { $('backend-status').textContent = 'Không tải được mạng'; status(`Không tải được topology: ${error.message}. Nhấn cập nhật để thử lại.`); });
    return { addEvent:async (...args) => { await ready; return addEvent(...args); }, disposeRoute, renderDroppedMarkers, refreshDroppedRoutes, focusDroppedMarker, setVisible };
}
