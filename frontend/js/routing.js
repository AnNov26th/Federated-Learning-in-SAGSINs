import * as THREE from 'three';
import { latLngToVector3 } from './3d/coordinates.js';

const $ = id => document.getElementById(id);
const html = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const number = value => Number.isFinite(value) ? value.toFixed(1) : '—';
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const MOBILITY_PLAYBACK_RATE = 20;

async function api(path, options) {
    const response = await fetch(path, options);
    let payload;
    try { payload = await response.json(); }
    catch { throw new Error(`Máy chủ trả về phản hồi không hợp lệ (HTTP ${response.status}).`); }
    if (!response.ok || payload.status !== 'success') throw new Error(typeof payload.detail === 'string' ? payload.detail : payload.message || `Không thể tải dữ liệu định tuyến (HTTP ${response.status}).`);
    return payload.data;
}

export function setupRouting({ scene3D, nodeMarkers, droppedMarkers, createMarker, flyGlobeToMarker,
    resetGlobeView, selectedNodeSummary, actionSelect, actionHint, container, topologyReady, refreshNodes }) {
    let nextId = 1, selectedId = null, generation = 0, context = { scenarios: [], models: [] }, refreshing = false;
    let showBaseline = false;
    let inspectorView = 'list', routeListScroll = 0, inspectorAnimation;
    let deletingAll = false;
    let topologyDrawing=null, baseTopology=null, topologyRequest=0;
    const drawings = new Map();
    const routeColors = [0x73dcf0, 0xa99aff, 0x7ee2b8, 0xffb878, 0xf48fc8, 0x8fbaff];
    const colorFor = drop => routeColors[Math.abs(drop.id) % routeColors.length];
    const status = message => { $('routing-status').textContent = message; };
    const activeDrop = () => droppedMarkers.find(d => d.id === selectedId);
    const config = () => ({ scenario_id: Number($('routing-scenario').value), policy: $('routing-policy').value,
        experiment_id: Number($('routing-model').value) || null, target_id: $('routing-target').value || null,
        topology: $('routing-topology').value,
        access_radius_km: $('routing-global').checked ? null : Number($('routing-radius').value),
        required_bandwidth_mbps: $('routing-demand').value === '' ? null : Number($('routing-demand').value),
        load_ratio: Number($('routing-load').value) / 100,
        allow_load_reduction: $('routing-reduce-load').checked,
        allow_reposition: true, mobility_boost: Number($('routing-mobility-boost').value),
        auto_train: $('routing-auto-train').checked });

    function validConfig() {
        return Boolean($('routing-scenario').value) && $('routing-radius').checkValidity() && $('routing-demand').checkValidity() && $('routing-mobility-boost').checkValidity();
    }

    $('routing-global').addEventListener('change', () => {
        $('routing-radius').disabled = $('routing-global').checked;
        $('routing-radius').required = !$('routing-global').checked;
    });

    function updateOptions() {
        const scenario = Number($('routing-scenario').value);
        const modelId = $('routing-model').value, targetId = $('routing-target').value;
        const models = context.models.filter(m => m.scenario_id === scenario);
        $('routing-model').innerHTML = '<option value="">Tự chọn checkpoint mới nhất</option>' + models.map(m => `<option value="${m.experiment_id}">#${m.experiment_id} · ${html(m.algorithm)} · round ${m.round}</option>`).join('');
        if (models.some(m => String(m.experiment_id) === modelId)) $('routing-model').value = modelId;
        $('routing-model').disabled = $('routing-policy').value === 'static';
        const model = models.find(m => String(m.experiment_id) === $('routing-model').value) || models[0];
        $('routing-readiness').textContent = $('routing-policy').value === 'static' ? 'Đang dùng công thức tĩnh.' : model ? `FL #${model.experiment_id} sẵn sàng chấm tuyến.` : $('routing-auto-train').checked ? 'Chưa có model FL. Sẽ tự huấn luyện khi đặt điểm.' : 'Chưa có model FL. Mở huấn luyện hoặc chọn công thức tĩnh.';
        $('routing-model-status').textContent = $('routing-policy').value === 'static' ? 'Đối chứng bằng công thức truyền FL, không suy luận model.' : model
            ? `Model #${model.experiment_id} · MAE ${number(model.mae_ms)} ms${model.beats_persistence ? '' : ' · Chưa tốt hơn persistence trên tập test'}`
            : 'Chưa có model phù hợp. Huấn luyện Network delay trong FL Training cho scenario này.';
        const targets = nodeMarkers.filter(m => m.userData.scenario_id === scenario && m.userData.type === 'GROUND' && m.userData.status?.toUpperCase() === 'ACTIVE');
        $('routing-target').innerHTML = '<option value="">Tự chọn GROUND có chi phí thấp nhất</option>' + targets.map(m => `<option value="${html(m.userData.id)}">${html(m.userData.id)}</option>`).join('');
        if (targets.some(m => m.userData.id === targetId)) $('routing-target').value = targetId;
        for (const marker of nodeMarkers) marker.visible = marker.userData.scenario_id === scenario;
        refreshTopology();
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

    async function refreshTopology(force=false) {
        const scenario=$('routing-scenario').value, topology=$('routing-topology').value;
        if (!scenario) return;
        const key=`${scenario}:${topology}`;
        if (!force && baseTopology?.key===key) return;
        const request=++topologyRequest;
        try {
            const snapshot=await api(`/api/routing/topology?scenario_id=${encodeURIComponent(scenario)}&topology=${encodeURIComponent(topology)}`);
            if (request!==topologyRequest || key!==`${$('routing-scenario').value}:${$('routing-topology').value}`) return;
            baseTopology={key,snapshot}; syncSelection();
        } catch (error) { if (request===topologyRequest) $('topology-caption').textContent=`Không tải được liên kết: ${error.message}`; }
    }

    function drawTopology(snapshot,key) {
        if (topologyDrawing?.key===key) return;
        if (topologyDrawing) disposeObject(topologyDrawing.group);
        const positions=new Map(snapshot.nodes.map(n=>[n.id,latLngToVector3(n.lat,n.lng,n.alt)]));
        const group=new THREE.Group();
        for (const link of snapshot.links) {
            const a=positions.get(link.source), b=positions.get(link.target); if (!a || !b) continue;
            const material=link.estimated ? new THREE.LineDashedMaterial({color:0x6b94b9,dashSize:.025,gapSize:.045,transparent:true,opacity:.12,depthWrite:false})
                : new THREE.LineBasicMaterial({color:0x86b5c5,transparent:true,opacity:.22,depthWrite:false});
            const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(arc(a,b)),material);
            if (link.estimated) line.computeLineDistances(); group.add(line);
        }
        scene3D.earth.add(group); topologyDrawing={key,group};
        $('topology-caption').textContent=`${snapshot.links.length}/${snapshot.total_links} link · liền: đã lưu · đứt: ước tính.`;
        $('topology-caption').title=`Hiện một phần topology để dễ quan sát, chọn ${snapshot.neighbors_shown} lân cận gần nhất cho mỗi node. Định tuyến vẫn xét toàn bộ liên kết hợp lệ.`;
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
        if (drop.mobility && !drop.mobility.completed) { drawMobility(drop); return; }
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
        addLine(points.backbone, colorFor(drop), drop.route.estimated_hops > 0);
        const baseline = new THREE.Group();
        if (drop.result.baseline && !drop.result.comparison?.same_path && drop.result.policy === 'predictive') {
            const baselinePoints = routePoints(drop, drop.result.baseline);
            const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(baselinePoints.all), new THREE.LineDashedMaterial({ color:0xb4a0ef, dashSize:.045, gapSize:.03, transparent:true, opacity:.6 }));
            line.computeLineDistances(); baseline.add(line);
        }
        group.add(baseline);
        const packet = new THREE.Mesh(new THREE.SphereGeometry(.022, 10, 10), new THREE.MeshBasicMaterial({ color:colorFor(drop), transparent:true }));
        group.add(packet);
        scene3D.earth.add(group);
        drawings.set(drop.id, { group, baseline, packet, points:points.all, replayStart:performance.now() - (drop.id % 7) * 650 });
        syncSelection();
    }

    function drawMobility(drop) {
        const group = new THREE.Group();
        for (const move of drop.mobility.moves) {
            const start = latLngToVector3(move.from.lat,move.from.lng,move.from.alt);
            const end = latLngToVector3(move.to.lat,move.to.lng,move.to.alt);
            const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(arc(start,end)),
                new THREE.LineDashedMaterial({color:0xffc16b,dashSize:.04,gapSize:.025,transparent:true,opacity:.9}));
            line.computeLineDistances(); group.add(line);
            const destination = new THREE.Mesh(new THREE.SphereGeometry(.025,12,12),new THREE.MeshBasicMaterial({color:0xffc16b}));
            destination.position.copy(end); group.add(destination);
        }
        scene3D.earth.add(group);
        drawings.set(drop.id,{group,moving:true});
        syncSelection();
    }

    function placeMovingNodes(drop) {
        const moving = drop.mobility;
        if (!moving) return;
        const markers = new Map(nodeMarkers.map(marker => [marker.userData.id,marker]));
        for (const move of moving.moves) {
            const marker = markers.get(move.node_id); if (!marker) continue;
            const start=latLngToVector3(move.from.lat,move.from.lng,move.from.alt);
            const end=latLngToVector3(move.to.lat,move.to.lng,move.to.alt);
            const fraction=move.eta_s > 0 ? Math.min(1,moving.elapsed_s/move.eta_s) : 1;
            const rotation=new THREE.Quaternion().setFromUnitVectors(start.clone().normalize(),end.clone().normalize());
            marker.position.copy(start).applyQuaternion(new THREE.Quaternion().slerp(rotation,fraction));
        }
    }

    function finishMobility(drop) {
        drop.mobility.elapsed_s=drop.mobility.eta_s;
        drop.mobility.completed=true;
        drop.status='Đã tới vùng phủ · bắt đầu truyền dữ liệu.';
        drawRoute(drop); renderDroppedMarkers();
        savePlayback(drop);
    }

    function syncSelection() {
        const drop = activeDrop();
        const scenarioId = Number($('routing-scenario').value);
        const snapshot=drop?.result?.topology_preview && drop.config.scenario_id===scenarioId
            ? {snapshot:drop.route && drop.result.topology_preview,key:`event:${drop.id}:${drop.result.snapshot_at}`}
            : baseTopology?.key===`${scenarioId}:${$('routing-topology').value}` ? baseTopology : null;
        if (snapshot?.snapshot) drawTopology(snapshot.snapshot,snapshot.key);
        if (topologyDrawing) topologyDrawing.group.visible=visible && $('show-topology').checked && !(drop?.mobility && !drop.mobility.completed);
        scene3D.earth.userData.routingSnapshot = droppedMarkers.some(event => event.route && event.config.scenario_id === scenarioId);
        for (const event of droppedMarkers) event.marker.visible = event.config.scenario_id === scenarioId;
        for (const [id, drawing] of drawings) {
            const selected = openPanel === 'route' && inspectorView === 'detail' && id === selectedId;
            drawing.group.visible = droppedMarkers.find(d => d.id === id)?.config.scenario_id === Number($('routing-scenario').value);
            drawing.group.traverse(child => { if (child.material) child.material.opacity = child === drawing.packet ? (selected ? 1 : .85) : selected ? 1 : .62; });
            if (drawing.baseline) drawing.baseline.visible = selected && showBaseline;
            if (drawing.packet) drawing.packet.visible = !reducedMotion.matches;
        }
        for (const marker of nodeMarkers) {
            const n = marker.userData;
            marker.position.copy(latLngToVector3(n.lat, n.lng, n.alt));
            const flows = droppedMarkers.filter(event => event.route?.path.includes(n.id));
            n.reserved_bandwidth_mbps = flows.reduce((sum,event) => sum + event.result.profile.min_bandwidth, 0);
            n.remaining_bandwidth_mbps = Math.max(0, n.bandwidth - n.reserved_bandwidth_mbps);
            n.event_connections = flows.length;
        }
        const markersById = new Map(nodeMarkers.map(marker => [marker.userData.id, marker]));
        for (const event of droppedMarkers) {
            if (!event.route || event.config.scenario_id !== scenarioId) continue;
            for (const node of event.route.positions) markersById.get(node.id)?.position.copy(latLngToVector3(node.lat,node.lng,node.alt));
            if (event.mobility) placeMovingNodes(event);
        }
    }

    scene3D.earth.userData.advanceRoutes = elapsedSeconds => {
        if (!visible) return;
        const now=performance.now();
        for (const drop of droppedMarkers) {
            if (drop.config.scenario_id !== Number($('routing-scenario').value)) continue;
            const drawing = drawings.get(drop.id);
            if (drop?.mobility && !drop.mobility.completed) {
                const moving=drop.mobility;
                const delta=Math.min(.1,elapsedSeconds); moving.last_frame=now;
                if (!moving.paused) moving.elapsed_s=Math.min(moving.eta_s,moving.elapsed_s+delta*MOBILITY_PLAYBACK_RATE);
                placeMovingNodes(drop);
                if (now-(moving.last_update || 0)>250) {
                    moving.last_update=now;
                    if (drop.id === selectedId) {
                        if ($('mobility-progress')) $('mobility-progress').value=moving.elapsed_s;
                        if ($('mobility-remaining')) $('mobility-remaining').textContent=`${number(Math.max(0,moving.eta_s-moving.elapsed_s))} giây mô phỏng còn lại`;
                        $('route-summary').textContent=`${drop.name} · ${moving.moves.length} phương tiện đang tiếp cận · còn ${number(moving.eta_s-moving.elapsed_s)} giây mô phỏng`;
                    }
                }
                if (now-(moving.last_saved || 0)>5000) { moving.last_saved=now; savePlayback(drop); }
                if (moving.elapsed_s>=moving.eta_s) finishMobility(drop);
                continue;
            }
            if (!drawing?.packet || reducedMotion.matches) continue;
            const t = ((now - drawing.replayStart) % 5000) / 5000;
            const scaled = t * (drawing.points.length - 1), index = Math.floor(scaled);
            if (drawing.points[index]) drawing.packet.position.copy(drawing.points[index]).lerp(drawing.points[Math.min(index+1,drawing.points.length-1)], scaled-index);
        }
    };

    async function savePlayback(drop, keepalive = false) {
        if (!drop.saved || !drop.mobility || drop.deleting) return;
        try {
            await api(`/api/routing/events/${drop.id}/playback`, { method:'PATCH', keepalive,
                headers:{'Content-Type':'application/json'}, body:JSON.stringify({
                    snapshot_at:drop.result.snapshot_at, elapsed_s:drop.mobility.elapsed_s, paused:drop.mobility.paused }) });
        } catch (error) { status(`Chưa lưu được tiến độ ${drop.name}: ${error.message}`); }
    }
    window.addEventListener('pagehide', () => droppedMarkers.forEach(drop => savePlayback(drop, true)));

    function applySaved(drop, saved) {
        const oldId = drop.id;
        if (oldId !== saved.id) { disposeRoute(oldId); if (selectedId === oldId) selectedId = saved.id; }
        Object.assign(drop, { id:saved.id, name:saved.name, action:saved.service, lat:saved.lat, lng:saved.lng,
            config:saved.config, result:saved.result, route:saved.result?.route, status:saved.result?.reason, saved:true, mobility:null });
        drop.marker.position.copy(latLngToVector3(saved.lat,saved.lng));
        const mobility = saved.result?.mobility;
        if (drop.route && mobility?.moves?.length) {
            const elapsed = Math.min(mobility.eta_s, saved.playback?.elapsed_s || 0);
            drop.mobility = {...mobility, elapsed_s:elapsed, completed:elapsed >= mobility.eta_s,
                paused:reducedMotion.matches || Boolean(saved.playback?.paused), last_frame:performance.now(), last_saved:performance.now()};
        }
        drawRoute(drop);
    }

    async function restoreEvents() {
        const saved = await api('/api/routing/events');
        const ids = new Set(saved.map(event => event.id));
        for (const drop of [...droppedMarkers]) {
            if (drop.saved && !ids.has(drop.id) && !drop.computing) {
                disposeRoute(drop.id); disposeObject(drop.marker); droppedMarkers.splice(droppedMarkers.indexOf(drop),1);
            }
        }
        for (const event of saved) {
            const existing = droppedMarkers.find(drop => drop.id === event.id);
            if (existing) {
                if (existing.computing || existing.deleting) continue;
                if (existing.result?.snapshot_at === event.result?.snapshot_at && existing.mobility) {
                    event.playback = {elapsed_s:Math.max(event.playback?.elapsed_s || 0,existing.mobility.elapsed_s),paused:existing.mobility.paused};
                }
                applySaved(existing,event); continue;
            }
            const marker = createMarker(0xff00ff,255,0,255,1.2);
            marker.position.copy(latLngToVector3(event.lat,event.lng)); scene3D.earth.add(marker);
            const drop = {id:event.id, marker, pending:false, focused:false};
            droppedMarkers.push(drop); applySaved(drop,event);
        }
        renderDroppedMarkers();
        // Resume saved training requests without changing admitted routes.
        for (const drop of droppedMarkers.filter(event => event.result?.code === 'training')) compute(drop,generation);
    }

    function renderInspector() {
        const drop = activeDrop();
        $('route-state').dataset.state = drop?.result?.status || 'pending';
        const moving=drop?.mobility && !drop.mobility.completed;
        $('route-state').textContent = !drop ? 'Chờ điểm đặt' : drop.pending ? 'Đang tính' : moving ? 'Đang điều động · chưa truyền' : drop.result?.code === 'no_model' ? 'Thiếu checkpoint FL' : drop.route ? (drop.route.application.latency_budget_met ? 'Có tuyến · trong ngân sách' : 'Có tuyến · vượt ngân sách') : 'Chưa có tuyến';
        $('route-summary').dataset.state=drop && !drop.pending && !drop.route ? 'unavailable' : 'idle';
        $('route-summary').textContent = !drop ? 'Chọn sự kiện rồi nhấn lên địa cầu để bắt đầu.'
            : drop.pending ? `${drop.name} · ${drop.status || 'Đang tính tuyến…'}`
            : drop.route ? `${drop.name} · ${drop.action} · ${drop.route.hop_count} hop · ${number(drop.route.application.estimated_one_way_ms)} ms một chiều ước tính · Xem Phân tích tuyến`
            : `${drop.name} · ${drop.action} · ${drop.status}`;
        $('route-back').hidden = inspectorView !== 'detail';
        const deleteButton = $('route-delete');
        deleteButton.hidden = inspectorView !== 'detail' || !drop;
        deleteButton.disabled = deletingAll || Boolean(drop?.deleting || (drop?.pending && !drop?.saved));
        deleteButton.setAttribute('aria-label', drop ? `Xóa ${drop.name}` : 'Xóa điểm');
        deleteButton.querySelector('span').textContent = drop?.deleting ? 'Đang xóa…' : 'Xóa điểm';
        if (inspectorView === 'list') {
            const events = droppedMarkers.filter(event => event.config.scenario_id === Number($('routing-scenario').value));
            $('route-inspector-title').textContent = 'Danh sách tuyến';
            $('route-state').dataset.state = 'idle';
            $('route-state').textContent = `${events.filter(event => event.route).length}/${events.length} điểm có tuyến`;
            $('route-inspector-content').innerHTML = events.length ? `<div class="route-list-actions"><p class="route-caption">Chọn một điểm để xem tuyến truyền và kết quả phân tích.</p><button class="toolbar-button route-delete-action" type="button" data-delete-all ${deletingAll || refreshing || events.some(event => (event.pending && !event.saved) || event.deleting) ? 'disabled' : ''}><i class="fa-solid fa-trash-can" aria-hidden="true"></i>${deletingAll ? 'Đang xóa…' : 'Xóa tất cả điểm'}</button></div><ul class="route-browser">${events.map(event => {
                const label = event.pending ? 'Đang tính tuyến…' : event.mobility && !event.mobility.completed ? 'Đang điều động' : event.route ? `${event.route.hop_count} hop · ${number(event.route.application.estimated_one_way_ms)} ms` : 'Chưa có tuyến';
                return `<li><button class="route-card" type="button" data-view-route="${event.id}" style="--flow-color:#${colorFor(event).toString(16).padStart(6,'0')}"><span class="route-card-heading"><strong>${html(event.name)} · ${html(event.action)}</strong><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></span><span class="route-card-status">${label}${event.result?.allocation ? ` · Giữ ${number(event.result.allocation.reserved_mbps)} Mbps` : ''}</span><span class="route-card-path">${event.route ? event.route.path.map(html).join(' → ') : html(event.status || 'Chờ kết quả phân tích')}</span><small>${event.lat.toFixed(2)}°, ${event.lng.toFixed(2)}°</small></button><button class="toolbar-button route-card-delete" type="button" data-delete-drop="${event.id}" aria-label="Xóa ${html(event.name)}" ${(event.pending && !event.saved) || event.deleting || deletingAll ? 'disabled' : ''}><i class="fa-solid fa-trash-can" aria-hidden="true"></i>${event.deleting ? 'Đang xóa…' : 'Xóa điểm'}</button></li>`;
            }).join('')}</ul>` : '<div class="routing-empty"><i class="fa-solid fa-route" aria-hidden="true"></i><h3>Chưa có tuyến để xem</h3><p>Chọn sự kiện rồi đặt điểm trên địa cầu, hoặc nhập tọa độ trong Thiết lập.</p></div>';
            return;
        }
        $('route-inspector-title').textContent = drop ? `${drop.name} · ${drop.action}` : 'Từ sự kiện đến GROUND';
        if (!drop) {
            $('route-inspector-content').innerHTML = '<div class="routing-empty"><i class="fa-solid fa-route" aria-hidden="true"></i><h3>Quan sát cách mạng chọn đường</h3><p>Chọn sự kiện rồi đặt điểm trên địa cầu, hoặc nhập tọa độ trong cấu hình.</p></div>';
            return;
        }
        const result = drop.result, route = drop.route;
        if (!route) {
            $('route-inspector-content').innerHTML = `<p class="route-caption ${drop.pending ? '' : 'routing-error'}">${html(drop.status)}</p>${result?.access_search ? `<p class="route-caption">${result.access_search.mode === 'global' ? 'Tìm trên toàn scenario, không giới hạn bán kính.' : `Tìm trong bán kính ${number(result.access_search.used_radius_km)} km.`}</p>` : ''}${result?.access ? `<p class="route-caption">Node tiếp cận gần nhất: <strong>${html(result.access.source_id)}</strong> · ${number(result.access.distance_km)} km</p>` : ''}${result?.diagnostics ? `<p class="route-caption">${result.diagnostics.active_nodes} node ACTIVE · ${result.diagnostics.links} link · ${result.diagnostics.eligible_directions} hướng truyền thỏa điều kiện.</p>` : ''}${result?.code === 'no_model' ? '<div class="routing-error-actions"><button id="routing-train" class="action-btn" type="button">Mở FL Training</button><button id="routing-use-static" class="action-btn" type="button">Xem tuyến công thức cho điểm này</button></div>' : ''}${drop.pending ? '' : '<p class="route-caption">Kiểm tra node ACTIVE, nhu cầu băng thông và checkpoint; sau đó nhấn “Cập nhật mạng & tính lại” nếu vừa đổi cấu hình mạng.</p>'}`;
            return;
        }
        const model = result.model, predictive = result.policy === 'predictive', baseline = result.baseline;
        $('route-inspector-content').innerHTML = `
            ${drop.mobility ? `<section class="mobility-outcome"><h3>${moving ? 'Điều động để tạo kết nối' : 'Phương tiện đã tới vùng phủ'}</h3><p>Thời gian tiếp cận ${number(drop.mobility.eta_s)} giây mô phỏng · so sánh ${result.mobility.candidate_count} phương án vị trí. Tuyến dưới đây ${moving ? 'chỉ hoạt động sau khi phương tiện tới nơi' : 'đã bắt đầu truyền'}.</p><progress id="mobility-progress" max="${drop.mobility.eta_s || 1}" value="${drop.mobility.elapsed_s}" aria-label="Tiến độ điều động"></progress><p><output id="mobility-remaining">${number(Math.max(0,drop.mobility.eta_s-drop.mobility.elapsed_s))} giây mô phỏng còn lại</output></p><ul>${drop.mobility.moves.map(move=>`<li><strong>${html(move.node_id)} · ${html(move.type)}</strong> · ${number(move.distance_km)} km · ${number(move.speed_km_s*3600)} km/h (${move.boost}× tốc độ cơ sở) · ETA ${number(move.eta_s)} giây</li>`).join('')}</ul>${moving ? `<div class="mobility-actions"><button id="mobility-pause" class="toolbar-button" type="button">${drop.mobility.paused ? 'Tiếp tục' : 'Tạm dừng'}</button><button id="mobility-finish" class="toolbar-button" type="button">Tua tới khi kết nối</button></div>` : ''}<details><summary>Giả định di chuyển</summary><p>${html(result.mobility.note)}</p><p>Điểm so sánh: thời gian chờ + điểm tuyến / 1.000. Trọng số RTT, băng thông và khoảng cách áp dụng cho tuyến sau điều động; FL không dự đoán thời gian bay.</p></details></section>` : ''}
            <section class="service-outcome" aria-label="Kết quả ứng dụng">
                <span class="outcome-eyebrow">${moving ? 'DỰ KIẾN SAU KHI KẾT NỐI' : 'KẾT QUẢ ỨNG DỤNG · ƯỚC TÍNH'}</span>
                <h3>${number(route.application.estimated_one_way_ms)} <small>ms một chiều</small></h3>
                <span class="qos-state ${route.application.latency_budget_met ? 'qos-pass' : 'qos-fail'}">${route.application.latency_budget_met ? 'Trong ngân sách độ trễ' : 'Vượt ngân sách độ trễ'}</span>
                <p>Ngưỡng demo ${route.application.latency_budget_ms} ms · ${result.profile.min_bandwidth} Mbps yêu cầu · ${number(route.application.bandwidth_headroom_mbps)} Mbps dư tại nút thắt.</p>
                <p>Gồm tiếp cận và ${route.hop_count} hop, payload ứng dụng ${route.application.payload_bytes} byte. ${result.load_reduced ? 'Đã hạ tải theo lựa chọn của bạn; đây là phương án ở tải mới.' : 'Giữ nguyên tải yêu cầu.'}</p>
                <details><summary>Giả định tính toán</summary><p>${html(route.application.note)}</p><p>Độ trễ kênh ${number(route.application.channel_latency_ms)} ms + tuần tự hóa ${number(route.application.serialization_ms)} ms. Chỉ số này dùng công thức mô phỏng, chưa là đo lường hiệu quả model FL.</p></details>
            </section>
            <p class="route-caption">${predictive ? `<strong>FL #${model.experiment_id} · ${html(model.algorithm)} · round ${model.round}</strong>` : '<strong>Công thức tĩnh · đối chứng</strong>'}<br>${result.topology === 'adaptive' ? `Tuyến thích ứng · ${route.estimated_hops} chặng ước tính, không lưu` : result.topology === 'estimated' ? 'Topology ước tính · không lưu link' : 'Link ACTIVE đã lưu'} · scenario #${result.scenario_id}</p>
            <dl class="route-metrics"><div><dt>${predictive ? 'RTT proxy FL + tiếp cận' : 'RTT công thức FL + tiếp cận'}</dt><dd>${number(predictive ? route.total_predicted_transfer_ms : route.total_static_transfer_ms)} <small>ms*</small></dd></div><div><dt>Băng thông nút thắt</dt><dd>${number(route.bottleneck)} <small>Mbps</small></dd></div><div><dt>Chặng mạng</dt><dd>${route.hop_count} <small>hop + 1 tiếp cận</small></dd></div><div><dt>Tiếp cận ước tính</dt><dd>${number(route.accessDistanceKm)} <small>km</small></dd></div></dl>
            <p class="route-caption">Điểm → node ACTIVE phù hợp → GROUND tối ưu. Ngưỡng dịch vụ: ≥ ${result.profile.min_bandwidth} Mbps; tải áp dụng ${Math.round(result.applied_load_ratio*100)}%${result.applied_load_ratio < result.requested_load_ratio - .001 ? ` (giảm tự động từ ${Math.round(result.requested_load_ratio*100)}%)` : ''}.</p>
            <p class="route-caption">Điểm kết nối: <strong>${html(result.ingress_selection.chosen_node)} · ${html(result.ingress_selection.chosen_type)}</strong><br>Tiếp cận ${number(result.ingress_selection.access_distance_km)} km · RTT tiếp cận ${number(result.ingress_selection.access_rtt_ms)} ms · băng thông đầu vào ${number(result.ingress_selection.access_bandwidth_mbps)} Mbps · tổng điểm tuyến ${number(result.ingress_selection.total_cost)} · phạt sở thích thiết bị ${number(result.ingress_selection.preference_penalty)}.<br>${html(result.ingress_selection.reason)}</p>
            <details class="routing-explanation" open><summary>Cách chấm điểm · thấp hơn là tốt hơn</summary>
                <p>Nhu cầu ${result.profile.min_bandwidth} Mbps · trọng số: độ trễ ${result.profile.latency_weight}, băng thông ${result.profile.capacity_weight}, khoảng cách ${result.profile.distance_weight}.</p>
                <p>Mỗi chặng: w_trễ × RTT ${predictive ? 'dự đoán' : 'công thức'} + w_băng_thông × 100 / Mbps + w_khoảng_cách × km / 100. Cộng phạt sở thích thiết bị ở đầu vào.</p>
                <dl class="route-metrics"><div><dt>Điểm độ trễ</dt><dd>${number(route.score_breakdown.delay)}</dd></div><div><dt>Điểm băng thông</dt><dd>${number(route.score_breakdown.capacity)}</dd></div><div><dt>Điểm khoảng cách</dt><dd>${number(route.score_breakdown.distance)}</dd></div><div><dt>Tổng điểm (+ ${number(route.score_breakdown.preference)} sở thích)</dt><dd>${number(route.score_breakdown.total)}</dd></div></dl>
                <p>Tổng quãng đường ${number(route.distance_km)} km. ${html(route.access.note)} ${predictive ? `RTT proxy tiếp cận dự đoán ${number(route.predicted_access_rtt_ms)} ms; công thức ${number(route.access_rtt_ms)} ms.` : ''}</p>
            </details>
            <ol class="route-hop-list"><li><span class="hop-number">•</span><div><strong>Điểm sự kiện</strong><small>${drop.lat.toFixed(3)}°, ${drop.lng.toFixed(3)}° · tiếp cận được chấm theo chính sách đã chọn</small></div></li>${route.positions.map((node, index) => { const hop = route.hops[index-1]; return `<li><span class="hop-number">${index+1}</span><div><strong>${html(node.id)} · ${html(node.type)}</strong><small>${index === 0 ? `Điểm kết nối ${html(result.ingress_selection.chosen_type)} · được chọn theo tổng điểm tuyến` : `${number(hop.predicted_ms ?? hop.static_ms)} ms RTT/hop · ${number(hop.bandwidth_mbps)} Mbps · ${hop.estimated ? 'link ước tính' : 'link ACTIVE'}`}${index === route.positions.length-1 ? ' · đích' : ''}</small></div></li>`; }).join('')}</ol>
            ${predictive ? `<div class="route-comparison"><h3>Đối chiếu trên cùng topology & tải</h3><p>Chênh lệch ước tính ứng dụng: <strong>${number(result.comparison.application_estimate_change_ms)} ms</strong> (đối chứng − tuyến chọn; âm nghĩa là tuyến chọn chậm hơn theo công thức).</p><p>Tuyến công thức: ${baseline.path.map(html).join(' → ')}</p><p>Model chấm tuyến công thức: <strong>${number(baseline.total_predicted_transfer_ms)} ms*</strong><br>Model chấm tuyến được chọn: <strong>${number(route.total_predicted_transfer_ms)} ms*</strong></p><p>${result.comparison.same_path ? 'Hai chính sách chọn cùng tuyến.' : `Hai chính sách chọn khác tuyến. Chênh lệch RTT proxy gồm tiếp cận: ${number(result.comparison.predicted_cost_change)} ms (điểm tối ưu còn có thành phần băng thông).`}</p>${!result.comparison.same_path ? `<label><input id="routing-show-baseline" type="checkbox" ${showBaseline ? 'checked' : ''}> Hiện tuyến công thức trên địa cầu</label>` : ''}<p>MAE test ${number(model.mae_ms)} ms · validation ${number(model.validation_mae_ms)} ms<br>${model.beats_persistence ? 'Model tốt hơn persistence trên tập test.' : 'Model chưa tốt hơn persistence trên tập test.'}</p></div>` : ''}
            <div class="route-legend"><span>Tiếp cận</span><span>${route.estimated_hops ? 'Tuyến chọn (nét đứt = ước tính)' : 'Tuyến chọn'}</span><span>Đối chứng</span></div>
            ${result.allocation ? `<section class="route-comparison"><h3>Băng thông đã cấp cho điểm này</h3><p><strong>${number(result.allocation.reserved_mbps)} Mbps</strong> trên mỗi node và link của tuyến. Đã xét ${result.allocation.other_event_count} điểm có tuyến trước khi cấp.</p><ul class="allocation-list">${result.allocation.nodes.map(node => `<li><strong>${html(node.node_id)}</strong><span>Đã dùng trước: ${number(node.reserved_before_mbps)} Mbps · Còn trước khi cấp: ${number(node.available_before_mbps)} Mbps · Còn sau khi cấp: ${number(node.remaining_after_mbps)} Mbps</span></li>`).join('')}</ul><p>${html(result.allocation.policy)}</p><p>Số liệu tại thời điểm cấp tuyến. Điểm mới sẽ tính lại phần còn lại từ tất cả điểm đang lưu; xóa điểm sẽ giải phóng băng thông.</p></section>` : ''}
            ${moving ? '' : '<button class="action-btn routing-replay" id="routing-replay" type="button"><i class="fa-solid fa-play" aria-hidden="true"></i> Xem lại luồng truyền minh họa</button>'}
            <button class="action-btn" id="routing-export" type="button"><i class="fa-solid fa-download" aria-hidden="true"></i> Xuất kết quả & cấu hình JSON</button>
            <p class="route-caption">Luồng truyền minh họa 5 giây/lượt sau khi kết nối. Vị trí lấy theo snapshot và phương án điều động của lượt này.<br>Cập nhật: ${html(new Date(result.snapshot_at).toLocaleTimeString('vi-VN'))}</p>
            <p class="route-note">* ${html(result.note)} Payload ${result.payload_bytes} byte. Tổng RTT proxy gồm cả tiếp cận và từng hop, dùng dự đoán với chính sách FL; không phải độ trễ ứng dụng đo thực tế. ${result.unseen_layers?.length ? `Lớp chưa có trong dữ liệu huấn luyện: ${result.unseen_layers.map(html).join(', ')}.` : ''}</p>
            <details class="routing-explanation"><summary>Công thức & dữ liệu quyết định</summary><p>${html(result.objective)}<br>w_delay = ${result.profile.latency_weight}; w_capacity = ${result.profile.capacity_weight}; w_distance = ${result.profile.distance_weight}. Điểm tuyến: ${number(route.cost)}.<br>${result.diagnostics.active_nodes} node · ${result.diagnostics.links} link · ${result.diagnostics.eligible_directions} hướng truyền hợp lệ.</p><p>Input mỗi hop: lớp node nhận, latency, bandwidth, khoảng cách, tải, loss, jitter, payload và RTT công thức. Dự đoán batch một lần; không dùng nhãn tương lai của dataset.</p></details>`;
    }

    function renderDroppedMarkers() {
        if (!activeDrop()) inspectorView = 'list';
        $('drop-count').textContent = `${droppedMarkers.length} điểm · ${droppedMarkers.filter(d => d.route).length} có tuyến`;
        $('drop-list').innerHTML = droppedMarkers.length ? droppedMarkers.map(drop => `
            <article class="drop-item${drop.id === selectedId ? ' selected' : ''}" role="listitem">
                <button class="drop-info" type="button" data-inspect-drop="${drop.id}" aria-pressed="${drop.id === selectedId}"><span class="drop-name-row"><span class="drop-name">${html(drop.name)} · ${html(drop.action)}</span><span class="drop-status">${drop.pending ? 'Đang tính' : drop.route ? `${drop.route.hop_count} hop` : 'Chưa có tuyến'}</span></span><span class="drop-detail">${drop.lat.toFixed(2)}°, ${drop.lng.toFixed(2)}° · scenario #${drop.config.scenario_id}</span></button>
                <button class="drop-delete" type="button" data-delete-drop="${drop.id}" ${(drop.pending && !drop.saved) || drop.deleting || deletingAll ? 'disabled' : ''} aria-label="Xóa ${html(drop.name)}"><i class="fa-solid fa-trash-can" aria-hidden="true"></i></button>
            </article>`).join('') : '<div class="drop-empty"><i class="fa-solid fa-location-dot" aria-hidden="true"></i><span>Chưa có sự kiện</span><small>Chọn sự kiện và đặt điểm trên địa cầu</small></div>';
        renderInspector();
        syncSelection();
    }

    async function compute(drop, token) {
        if (drop.computing || drop.deleting) return;
        drop.computing = true;
        const requestId = drop.requestId = (drop.requestId || 0) + 1;
        drop.pending = true; drop.status = 'Đang tính tuyến…';
        renderDroppedMarkers();
        try {
            const requestOptions = { method:drop.saved ? 'PUT' : 'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ ...drop.config, lat:drop.lat, lng:drop.lng, service:drop.action, client_key:drop.clientKey }) };
            let saved = await api(drop.saved ? `/api/routing/events/${drop.id}` : '/api/routing/events', requestOptions);
            if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
            applySaved(drop,saved);
            let result = saved.result;
            if (result.code === 'training') {
                const experimentId = result.training.experiment_id;
                drop.status = `Đang tự huấn luyện Network delay (#${experimentId})…`;
                renderDroppedMarkers(); status(`${drop.name}: ${drop.status}`);
                const started = Date.now();
                while (Date.now() - started < 10 * 60 * 1000) {
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
                    const experiment = await api(`/api/fl/experiments/${experimentId}`);
                    if (experiment.status === 'FAILED' || experiment.status === 'CANCELLED') {
                        throw new Error(`Huấn luyện thất bại: ${experiment.error_message || experiment.status}`);
                    }
                    if (experiment.status === 'COMPLETED') break;
                    drop.status = `Đang huấn luyện Network delay (#${experimentId}) · ${experiment.completed_rounds || 0}/${experiment.target_rounds || 10} vòng…`;
                    renderDroppedMarkers(); status(`${drop.name}: ${drop.status}`);
                }
                if (Date.now() - started >= 10 * 60 * 1000) throw new Error('Huấn luyện quá thời gian chờ; có thể kiểm tra tiến độ trong FL Training.');
                await loadContext();
                if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
                saved = await api(`/api/routing/events/${drop.id}`, {...requestOptions, method:'PUT'});
                if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
                applySaved(drop,saved);
                result = saved.result;
            }
        } catch (error) {
            if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
            drop.status = `${drop.saved ? 'Chưa cập nhật được điểm' : 'Chưa lưu được điểm, hãy thử cập nhật lại'}: ${error.message}`;
        } finally { drop.computing = false; }
        if (token !== generation || requestId !== drop.requestId || !droppedMarkers.includes(drop)) return;
        drop.pending = false; renderDroppedMarkers();
        status(`${drop.name}: ${drop.status}`);
    }

    async function addEvent(lat, lng, service, marker) {
        if (refreshing || deletingAll) { if (marker) disposeObject(marker); status('Chờ cập nhật hoặc xóa điểm hoàn tất trước khi thêm sự kiện.'); return; }
        if (!validConfig()) { if (marker) disposeObject(marker); status('Chọn scenario, nhu cầu băng thông và bán kính hợp lệ.'); return; }
        if (!service) { if (marker) disposeObject(marker); status('Chọn loại sự kiện trước khi đặt điểm.'); return; }
        if (!marker) { marker = createMarker(0xff00ff,255,0,255,1.2); marker.position.copy(latLngToVector3(lat,lng)); scene3D.earth.add(marker); }
        const id = -(nextId++);
        const drop = { id, clientKey:crypto.randomUUID(), saved:false, name:'Điểm mới · đang lưu', action:service, lat, lng, marker,
            config:config(), pending:true, status:'Đang tính tuyến…', route:null, focused:true };
        droppedMarkers.forEach(d => { d.focused = false; }); droppedMarkers.push(drop); selectedId = id;
        inspectorView = 'detail';
        actionSelect.value = ''; actionHint.style.display = 'none'; container.style.cursor = 'default';
        renderDroppedMarkers();
        setPanel('route');
        flyGlobeToMarker(drop.marker,6);
        await compute(drop, generation);
    }

    async function refreshDroppedRoutes() {
        if (refreshing || deletingAll) return;
        if (droppedMarkers.some(drop => drop.computing || drop.deleting)) { status('Chờ lưu hoặc tính tuyến hiện tại hoàn tất trước khi cập nhật mạng.'); return; }
        if (!validConfig()) { status('Chọn scenario, nhu cầu băng thông và bán kính hợp lệ trước khi tính lại.'); return; }
        refreshing = true; $('routing-refresh').disabled = true;
        const token = ++generation;
        const appliedConfig = config();
        const events = droppedMarkers.filter(drop => drop.config.scenario_id === appliedConfig.scenario_id);
        renderDroppedMarkers(); status('Đang cập nhật topology, checkpoint và tính lại tuyến…');
        try {
            await refreshNodes(); await loadContext(); await refreshTopology(true);
            $('backend-status').textContent = 'Connected';
            for (const drop of events) {
                // Recompute this scenario sequentially; other saved reservations remain held.
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
        if (inspectorView === 'list') routeListScroll = $('route-inspector').scrollTop;
        inspectorView = 'detail';
        selectedId = drop.id;
        droppedMarkers.forEach(d => { d.focused = d === drop; });
        renderDroppedMarkers(); setPanel('route');
        $('route-inspector').scrollTop = 0;
        animateInspector();
        $('route-back').focus({ preventScroll:true });
    }
    function focusDroppedMarker(drop) {
        select(drop); flyGlobeToMarker(drop.marker, 4.75);
        if (selectedNodeSummary) selectedNodeSummary.textContent = `${drop.name} · ${drop.action}`;
    }
    function removeDrop(drop) {
        const index = droppedMarkers.indexOf(drop);
        if (index < 0) return;
        disposeRoute(drop.id); disposeObject(drop.marker); droppedMarkers.splice(index,1);
        if (selectedId === drop.id) { selectedId = null; inspectorView = 'list'; }
        if (!droppedMarkers.length) nextId = 1;
    }
    async function deleteDrop(drop) {
        if (!drop || (drop.pending && !drop.saved) || drop.deleting || deletingAll) return;
        drop.deleting = true; renderDroppedMarkers();
        try {
            if (drop.saved) await api(`/api/routing/events/${drop.id}`, {method:'DELETE'});
        } catch (error) { drop.deleting=false; status(`Không xóa được ${drop.name}: ${error.message}`); renderDroppedMarkers(); return; }
        removeDrop(drop); renderDroppedMarkers();
        status(`Đã xóa ${drop.name} và giải phóng băng thông của tuyến.`);
        if (openPanel === 'route') $('route-inspector-content').querySelector('[data-view-route]')?.focus({preventScroll:true});
    }
    async function deleteAllDrops() {
        if (deletingAll || refreshing) return;
        const scenario = Number($('routing-scenario').value);
        const events = droppedMarkers.filter(drop => drop.config.scenario_id === scenario);
        if (!events.length || events.some(drop => (drop.pending && !drop.saved) || drop.deleting)) return;
        deletingAll = true; renderDroppedMarkers();
        try {
            await api(`/api/routing/events?scenario_id=${scenario}`, {method:'DELETE'});
            for (const drop of events) removeDrop(drop);
            inspectorView = 'list';
            status('Đã xóa tất cả điểm và giải phóng băng thông. Điểm mới sẽ bắt đầu từ Điểm 1.');
        } catch (error) { status(`Không xóa được các điểm: ${error.message}`); }
        finally { deletingAll = false; renderDroppedMarkers(); }
    }
    $('route-delete').addEventListener('click', () => deleteDrop(activeDrop()));
    $('drop-list').addEventListener('click', event => {
        const button = event.target.closest('button'); if (!button) return;
        const id = Number(button.dataset.deleteDrop || button.dataset.focusDrop || button.dataset.inspectDrop);
        const drop = droppedMarkers.find(d => d.id === id); if (!drop) return;
        if (button.dataset.deleteDrop) {
            deleteDrop(drop);
        } else if (button.dataset.focusDrop) focusDroppedMarker(drop);
        else focusDroppedMarker(drop);
    });
    $('route-inspector-content').addEventListener('change', event => {
        if (event.target.id === 'routing-show-baseline') { showBaseline = event.target.checked; syncSelection(); }
    });
    $('route-inspector-content').addEventListener('click', event => {
        const deleteButton = event.target.closest('[data-delete-drop]');
        if (deleteButton) { deleteDrop(droppedMarkers.find(drop => drop.id === Number(deleteButton.dataset.deleteDrop))); return; }
        if (event.target.closest('[data-delete-all]')) { deleteAllDrops(); return; }
        const routeButton = event.target.closest('[data-view-route]');
        if (routeButton) {
            const drop = droppedMarkers.find(item => item.id === Number(routeButton.dataset.viewRoute));
            if (drop) focusDroppedMarker(drop);
            return;
        }
        const active=activeDrop();
        if (event.target.closest('#mobility-pause') && active?.mobility) { active.mobility.paused=!active.mobility.paused; savePlayback(active); renderInspector(); }
        if (event.target.closest('#mobility-finish') && active?.mobility) finishMobility(active);
        if (event.target.closest('#routing-use-static') && active) {
            $('routing-policy').value='static'; updateOptions();
            active.config={...active.config,policy:'static',experiment_id:null,auto_train:false}; compute(active,generation);
        }
        if (event.target.closest('#routing-export')) {
            const drop = activeDrop();
            if (drop?.result) {
                const url = URL.createObjectURL(new Blob([JSON.stringify({event:{service:drop.action,lat:drop.lat,lng:drop.lng},request:drop.config,result:drop.result},null,2)],{type:'application/json'}));
                Object.assign(document.createElement('a'),{href:url,download:`sagsin-event-${drop.id}.json`}).click();
                setTimeout(() => URL.revokeObjectURL(url),1000);
            }
        }
        if (event.target.closest('#routing-train')) window.postMessage({ type:'sagsin:navigate',href:'/fl.html' },window.location.origin);
        if (event.target.closest('#routing-replay')) { const drop = activeDrop(); const drawing = drawings.get(drop?.id); if (drawing) drawing.replayStart = performance.now(); if (drop) flyGlobeToMarker(drop.marker,5.4); }
    });
    function animateInspector(back = false) {
        inspectorAnimation?.cancel();
        if (reducedMotion.matches) return;
        inspectorAnimation = $('route-inspector-content').animate([
            { opacity:0, transform:`translateX(${back ? '-12px' : '16px'})` },
            { opacity:1, transform:'translateX(0)' }
        ], { duration:480, easing:'cubic-bezier(.22,1,.36,1)' });
    }
    $('route-back').addEventListener('click', () => {
        const previousId = selectedId;
        inspectorView = 'list'; renderInspector(); syncSelection(); animateInspector(true);
        $('route-inspector').scrollTop = routeListScroll;
        $('route-inspector-content').querySelector(`[data-view-route="${previousId}"]`)?.focus({ preventScroll:true });
    });
    $('routing-refresh').addEventListener('click', refreshDroppedRoutes);
    $('show-topology').addEventListener('change',syncSelection);
    for (const id of ['routing-scenario','routing-policy','routing-model','routing-target','routing-topology','routing-radius','routing-load','routing-reduce-load','routing-auto-train','routing-mobility-boost','routing-demand','routing-global']) {
        $(id).addEventListener('change', () => {
            if (['routing-scenario','routing-policy','routing-model','routing-auto-train'].includes(id)) updateOptions();
            if (id==='routing-topology') refreshTopology();
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
            else if (openPanel === 'route' && inspectorView === 'detail') $('route-back').click();
            else setPanel(null, true);
        }
    });
    let openPanel = null, visible = true;
    let dockAnimation, panelAnimation, panelTransition = 0;
    function setPanel(panel, restoreFocus = false) {
        const previous = openPanel;
        openPanel = panel;
        const transition = ++panelTransition;
        const dock = $('simulation-dock');
        const wasHidden = dock.hidden;
        dockAnimation?.cancel(); panelAnimation?.cancel();
        dock.inert = !panel || !visible;
        if (panel && visible) dock.hidden = false;
        $('simulation-workspace').dataset.panel = panel || '';
        if (panel || reducedMotion.matches || !visible) {
            $('action-panel').hidden = panel !== 'config';
            $('route-inspector').hidden = panel !== 'route';
        }
        if (!panel || !visible) {
            if (wasHidden || reducedMotion.matches || !visible) dock.hidden = true;
            else {
                const offset = window.matchMedia('(max-width:760px)').matches ? 'translateY(24px)' : 'translateX(24px)';
                dockAnimation = dock.animate([{ opacity:1, transform:'translate(0)' }, { opacity:0, transform:offset }], { duration:360, easing:'ease-out', fill:'forwards' });
                setTimeout(() => { if (transition === panelTransition) dock.hidden = true; }, 360);
            }
        } else if (panel !== previous && !reducedMotion.matches) {
            const offset = window.matchMedia('(max-width:760px)').matches ? 'translateY(24px)' : 'translateX(24px)';
            dockAnimation = dock.animate([{ opacity:0, transform:offset }, { opacity:1, transform:'translate(0)' }], { duration:580, easing:'cubic-bezier(.22,1,.36,1)' });
            panelAnimation = $(panel === 'route' ? 'route-inspector' : 'action-panel').animate([
                { opacity:0, transform:'translateY(14px)' }, { opacity:1, transform:'translateY(0)' }
            ], { duration:560, easing:'cubic-bezier(.22,1,.36,1)' });
        }
        if (panel && panel !== previous) $(panel === 'route' ? 'route-inspector' : 'action-panel').scrollTop = 0;
        document.querySelectorAll('[data-simulation-panel]').forEach(button => {
            button.setAttribute('aria-expanded', String(button.dataset.simulationPanel === panel && visible));
        });
        syncSelection();
        if (panel) $('btn-close-panel').focus({ preventScroll:true });
        else if (restoreFocus && previous) document.querySelector(`[data-simulation-panel="${previous}"]`).focus({ preventScroll:true });
    }
    document.querySelectorAll('[data-simulation-panel]').forEach(button => button.addEventListener('click', () => {
        const panel = button.dataset.simulationPanel;
        if (panel === 'route' && (openPanel !== 'route' || inspectorView === 'detail')) {
            inspectorView = 'list'; renderInspector(); animateInspector(true);
            setPanel('route', true);
        } else setPanel(openPanel === panel ? null : panel, true);
    }));
    $('btn-close-panel').addEventListener('click', () => setPanel(null, true));
    setPanel(null);
    function setVisible(value) {
        visible = value;
        // Returning to Simulation starts with the full globe again.
        setPanel(null);
    }
    const ready = topologyReady.then(loadContext).then(restoreEvents).then(() => { $('backend-status').textContent = 'Connected'; status(`Đã tải ${droppedMarkers.length} điểm đã lưu. Chọn sự kiện để thêm điểm mới.`); })
        .catch(error => { $('backend-status').textContent = 'Không tải được mạng'; status(`Không tải được topology: ${error.message}. Nhấn cập nhật để thử lại.`); });
    return { addEvent:async (...args) => { await ready; return addEvent(...args); }, reloadSavedEvents:async () => { await ready; return restoreEvents(); }, disposeRoute, renderDroppedMarkers, refreshDroppedRoutes, focusDroppedMarker, setVisible };
}
