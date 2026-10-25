import * as THREE from "three";
import { createScene } from "./3d/scene.js?v=20261023g";
import { fetchNodes } from "./api.js";
import { latLngToVector3 } from "./3d/coordinates.js";
import { setupRouting } from "./routing.js?v=20261023g";
import { setupTrainingGlobe } from "./training-globe.js?v=20261025";
import { setupShellNavigation } from './shell-navigation.js';

const container = document.getElementById("earth-container");

const scene3D = createScene(container);
const selectedNodeSummary = document.getElementById('selected-node-summary');

function resetGlobeView() {
    cameraFlightToken += 1;
    scene3D.controls.enabled = true;
    scene3D.earth.userData.rotationPaused = false;
    syncRotationControl();
    scene3D.camera.position.set(0, 0, 6);
    scene3D.controls.target.set(0, 0, 0);
    scene3D.controls.update();
    clearDeviceSelection();
    if (selectedNodeSummary) selectedNodeSummary.textContent = 'Nhấn vào node trên địa cầu để xem gần hơn.';
}

// --- ACTION PANEL EVENT LISTENERS ---

// System Actions
document.getElementById('btn-reset-cam').addEventListener('click', () => {
    if (scene3D.camera && scene3D.controls) resetGlobeView();
});

document.getElementById('earth-speed').addEventListener('change', event => {
    scene3D.earth.userData.rotationSpeedMultiplier = Number(event.target.value);
});

function syncRotationControl() {
    const paused = Boolean(scene3D.earth.userData.rotationPaused);
    const button = document.getElementById('btn-toggle-rotation');
    button.setAttribute('aria-pressed', String(paused));
    button.setAttribute('aria-label', paused ? 'Tiếp tục xoay địa cầu' : 'Tạm dừng xoay địa cầu');
    button.title = button.getAttribute('aria-label');
    button.querySelector('i').className = `fa-solid fa-${paused ? 'play' : 'pause'}`;
}
document.getElementById('btn-toggle-rotation').addEventListener('click', () => {
    scene3D.earth.userData.rotationPaused = !scene3D.earth.userData.rotationPaused;
    syncRotationControl();
});

// Select Action Combobox
const actionSelect = document.getElementById('action-select');
const actionHint = document.getElementById('action-hint');
const generateLinksButton = document.getElementById('btn-generate-links');
const generateLinksStatus = document.getElementById('generate-links-status');

generateLinksButton?.addEventListener('click', async () => {
    generateLinksButton.disabled = true;
    generateLinksStatus.textContent = 'Đang tìm node ACTIVE lân cận…';
    try {
        const scenarioId = document.getElementById('routing-scenario').value;
        if (!scenarioId) throw new Error('Chọn scenario trước khi tạo link.');
        const response = await fetch(`/api/links/generate-nearby?neighbors_per_node=2&max_distance_km=1500&scenario_id=${encodeURIComponent(scenarioId)}`, { method: 'POST' });
        const payload = await response.json();
        if (!response.ok || payload.status !== 'success') {
            throw new Error(payload.detail || payload.message || 'Không thể tạo link lân cận.');
        }
        const count = payload.data?.created_count || 0;
        generateLinksStatus.textContent = count
            ? `Đã lưu ${count} link ACTIVE. Các điểm thả đang được tính lại tuyến.`
            : 'Link lân cận đã tồn tại hoặc không có cặp node trong phạm vi.';
        await refreshDroppedRoutes();
    } catch (error) {
        generateLinksStatus.textContent = error.message || 'Không thể tạo link lân cận.';
    } finally {
        generateLinksButton.disabled = false;
    }
});

actionSelect.addEventListener('change', (e) => {
    clearDeviceSelection();
    if (e.target.value !== "") {
        actionHint.style.display = 'block';
        container.style.cursor = 'crosshair';
    } else {
        actionHint.style.display = 'none';
        container.style.cursor = 'default';
    }
});

// 3D Click Intersect (Raycaster)
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

// Tạo Group chứa marker và hiệu ứng viền phát sáng (glow)
let markerGroup = null;

// Hàm tạo texture hình tròn mờ dần (radial gradient) theo màu
function createGlowTexture(r, g, b) {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    
    const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 1)`);
    gradient.addColorStop(0.3, `rgba(${r}, ${g}, ${b}, 0.8)`);
    gradient.addColorStop(0.6, `rgba(${r}, ${g}, ${b}, 0.2)`);
    gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
    
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 64, 64);
    
    return new THREE.CanvasTexture(canvas);
}

// Hàm tạo 1 marker hoàn chỉnh với màu sắc tùy chỉnh
function createMarker(colorHex, r, g, b, sizeScale = 1.0) {
    const group = new THREE.Group();
    
    const markerGeo = new THREE.SphereGeometry(0.015 * sizeScale, 16, 16); 
    // Yêu cầu: điểm sáng phía trong cùng màu với bên ngoài thay vì màu trắng
    const markerMat = new THREE.MeshBasicMaterial({ color: colorHex });
    const innerDot = new THREE.Mesh(markerGeo, markerMat);
    
    const glowMat = new THREE.SpriteMaterial({ 
        map: createGlowTexture(r, g, b),
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false
    });
    const outerGlow = new THREE.Sprite(glowMat);
    outerGlow.scale.set(0.15 * sizeScale, 0.15 * sizeScale, 0.15 * sizeScale);
    
    group.add(innerDot);
    group.add(outerGlow);
    return group;
}

// Lấy danh sách nodes từ backend và vẽ lên bản đồ
const nodeMarkers = [];
const movingDevices = [];
const orbitLineMaterial = new THREE.LineBasicMaterial({ color: 0xffbd69, transparent: true, opacity: 0.75 });
let selectedOrbitLine = null;

function createDeviceMotion(node, initialPosition) {
    if(node.platform==='RESEARCH_STATIC')return null;
    const radial = initialPosition.clone().normalize();
    const inclination = THREE.MathUtils.degToRad(node.orbit_inclination_deg == null ? 53 : Number(node.orbit_inclination_deg));
    const plane = Math.max(0, Number(node.orbit_plane || 1) - 1);
    const raan = node.orbit_raan_deg == null ? plane * Math.PI / 3 : THREE.MathUtils.degToRad(Number(node.orbit_raan_deg));
    // Orbit metadata is inertial; the seed lat/lng is Earth-fixed at epoch.
    const epoch = Date.parse(node.epoch_utc || '2026-10-11T00:00:00Z');
    const jd = epoch / 86400000 + 2440587.5, centuries = (jd - 2451545) / 36525;
    const gmst = THREE.MathUtils.degToRad((280.46061837 + 360.98564736629 * (jd - 2451545) + .000387933 * centuries**2 - centuries**3 / 38710000) % 360);
    const nx = Math.sin(inclination) * Math.sin(raan), ny = -Math.sin(inclination) * Math.cos(raan);
    const orbitNormal = new THREE.Vector3(Math.cos(gmst)*nx + Math.sin(gmst)*ny, Math.cos(inclination), Math.sin(gmst)*nx - Math.cos(gmst)*ny);
    let tangent = new THREE.Vector3().crossVectors(orbitNormal, radial);
    if (tangent.lengthSq() < 1e-8) tangent = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), radial);
    tangent.normalize();

    if (node.type === 'SPACE') {
        const altitudeKm = Math.max(100, Number(node.alt) || 550);
        const orbitalPeriodSeconds = 2 * Math.PI * Math.sqrt(((6371 + altitudeKm) ** 3) / 398600.4418);
        return { type: 'SPACE', radial, tangent, radius: initialPosition.length(), orbitalPeriodSeconds, angularSpeed: (2 * Math.PI) / orbitalPeriodSeconds };
    }
    if (node.type === 'SEA' || node.type === 'AIR') {
        const pathRadiusMeters = node.type === 'SEA' ? 120000 : 20000;
        const speedMetersPerSecond = node.type === 'SEA' ? 8 : 15;
        const crossTrack = new THREE.Vector3().crossVectors(radial, tangent).normalize();
        return { type: node.type, radial, tangent, crossTrack, radius: initialPosition.length(), speedMetersPerSecond, pathRadiusMeters, pathAngle: Math.min(0.035, pathRadiusMeters / 6371e3), angularSpeed: speedMetersPerSecond / pathRadiusMeters };
    }
    return null;
}

function advanceMovingDevices(elapsedSeconds) {
    for (const device of movingDevices) {
        device.phase = (device.phase || 0) + elapsedSeconds * device.angularSpeed;
        // Deployed resources follow their saved deployment/playback instead.
        if (scene3D.earth.userData.deployedNodePositions?.has(device.marker.userData.id)) continue;
        if (device.type === 'SPACE') {
            device.marker.position.copy(device.radial).multiplyScalar(Math.cos(device.phase))
                .addScaledVector(device.tangent, Math.sin(device.phase)).multiplyScalar(device.radius);
        } else {
            const around = device.tangent.clone().multiplyScalar(Math.cos(device.phase)).addScaledVector(device.crossTrack, Math.sin(device.phase));
            device.marker.position.copy(device.radial).multiplyScalar(Math.cos(device.pathAngle))
                .addScaledVector(around, Math.sin(device.pathAngle)).multiplyScalar(device.radius);
        }
    }
}

scene3D.earth.userData.advanceDevices = advanceMovingDevices;

function removeSelectedOrbit() {
    if (!selectedOrbitLine) return;
    scene3D.earth.remove(selectedOrbitLine);
    selectedOrbitLine.geometry.dispose();
    selectedOrbitLine = null;
}

function orbitBasis(marker) {
    const motion = marker.userData.motion, radial = marker.position.clone().normalize();
    const normal = new THREE.Vector3().crossVectors(motion.radial,motion.tangent);
    const tangent = new THREE.Vector3().crossVectors(normal,radial);
    if (tangent.lengthSq() < 1e-8) tangent.copy(motion.tangent).addScaledVector(radial,-motion.tangent.dot(radial));
    return { radial,tangent:tangent.normalize() };
}

function showSatelliteOrbit(marker) {
    if(marker.userData.platform==='RESEARCH_STATIC')return;
    removeSelectedOrbit();
    if (marker?.userData?.type !== 'SPACE' || !marker.userData.motion) return;
    const {radial,tangent} = orbitBasis(marker);
    const points = [];
    for (let step = 0; step < 180; step += 1) {
        const angle = (step / 180) * Math.PI * 2;
        points.push(radial.clone().multiplyScalar(Math.cos(angle)).addScaledVector(tangent, Math.sin(angle)).multiplyScalar(marker.position.length()));
    }
    selectedOrbitLine = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points), orbitLineMaterial);
    scene3D.earth.add(selectedOrbitLine);
}

async function plotDatabaseNodes() {
    const nodes = await fetchNodes({ strict: true });
    nodes.forEach(node => {
        let colorHex, r, g, b;
        switch(node.type) {
            case "SPACE":
                colorHex = 0xffa500; r = 255; g = 165; b = 0; // Orange
                break;
            case "AIR":
                colorHex = 0x00ffff; r = 0; g = 255; b = 255; // Cyan
                break;
            case "GROUND":
                colorHex = 0x00ff00; r = 0; g = 255; b = 0; // Green
                break;
            case "SEA":
                colorHex = 0x0000ff; r = 0; g = 0; b = 255; // Blue
                break;
            default:
                colorHex = 0xffffff; r = 255; g = 255; b = 255;
        }
        
        const marker = createMarker(colorHex, r, g, b, 1.2);
        
        // Gắn dữ liệu node vào marker để hiển thị tooltip
        marker.userData = node;
        
        const pos = latLngToVector3(node.lat, node.lng, node.alt);
        marker.position.copy(pos);
        const motion = createDeviceMotion(node, pos);
        marker.userData.motion = motion;
        if (motion) movingDevices.push({ marker, ...motion, phase: 0 });
        
        scene3D.earth.add(marker);
        nodeMarkers.push(marker);
    });
}

// Khởi chạy vẽ nodes
const topologyReady = plotDatabaseNodes();
async function syncDatabaseNodes() {
    const nodes = await fetchNodes({ strict: true });
    const byId = new Map(nodeMarkers.map(marker => [marker.userData.id, marker]));
    movingDevices.length = 0;
    for (const node of nodes) {
        let marker = byId.get(node.id);
        if (!marker) {
            const colors = { SPACE: [0xffa500,255,165,0], AIR: [0x00ffff,0,255,255], GROUND: [0x00ff00,0,255,0], SEA: [0x6688ff,102,136,255] };
            marker = createMarker(...(colors[node.type] || [0xffffff,255,255,255]), 1.2);
            scene3D.earth.add(marker);
            nodeMarkers.push(marker);
        }
        marker.userData = node;
        const position = latLngToVector3(node.lat, node.lng, node.alt);
        marker.position.copy(position);
        const motion = createDeviceMotion(node, position);
        marker.userData.motion = motion;
        if (motion) movingDevices.push({ marker, ...motion, phase: 0 });
        byId.delete(node.id);
    }
    for (const marker of byId.values()) {
        scene3D.earth.remove(marker);
        marker.traverse(object => { object.geometry?.dispose(); object.material?.map?.dispose(); object.material?.dispose(); });
        nodeMarkers.splice(nodeMarkers.indexOf(marker), 1);
    }
    clearDeviceSelection();
}

// Click-only device information. Keep the card stable while live coordinates update.
const tooltip = document.getElementById('node-tooltip');
const infoContent = document.getElementById('node-info-content');
let selectedDevice = null, annotationElapsed = 0, infoAnimation;
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
})[character]);

function clearDeviceSelection() {
    const hadSelection = Boolean(selectedDevice || selectedOrbitLine);
    if (selectedDevice) {
        cameraFlightToken += 1;
        scene3D.controls.enabled = true;
    }
    selectedDevice = null;
    infoAnimation?.cancel();
    tooltip.hidden = true;
    removeSelectedOrbit();
    if (hadSelection && selectedNodeSummary) selectedNodeSummary.textContent = 'Nhấn thiết bị hoặc điểm sự kiện để xem thông tin.';
}

function renderDeviceInfo(marker) {
    const data = marker.userData;
    const layers = { SPACE:['Vệ tinh','satellite','#ffbd69'], AIR:['Thiết bị trên không','plane','#73dcf0'],
        GROUND:['Trạm mặt đất','tower-broadcast','#7ee2b8'], SEA:['Thiết bị trên biển','ship','#9baeff'] };
    const [label,icon,color] = layers[data.type] || ['Thiết bị','microchip','#b5caff'];
    const format = value => Number.isFinite(Number(value)) && value != null ? Number(value).toFixed(1) : '—';
    const row = (name,value) => value == null || value === '' ? '' : `<div><dt>${name}</dt><dd>${escapeHtml(value)}</dd></div>`;
    const remaining = Math.max(0, Number(data.remaining_bandwidth_mbps ?? data.bandwidth) || 0);
    const reserved = Math.max(0, Number(data.reserved_bandwidth_mbps) || 0);
    const used = data.bandwidth > 0 ? Math.min(100, reserved / data.bandwidth * 100) : 0;
    tooltip.style.setProperty('--device-accent',color);
    infoContent.innerHTML = `
        <header class="device-info-heading"><span class="device-info-icon"><i class="fa-solid fa-${icon}" aria-hidden="true"></i></span><div><span class="device-info-eyebrow">${label} · ${escapeHtml(data.type)}</span><h2 id="node-info-title">${escapeHtml(data.id)}</h2></div></header>
        <div class="device-info-status"><span data-active="${data.status?.toUpperCase() === 'ACTIVE'}">${escapeHtml(data.status || 'Chưa rõ trạng thái')}</span><span>${data.event_connections || 0} điểm kết nối</span></div>
        <div class="device-info-location"><i class="fa-solid fa-location-dot" aria-hidden="true"></i><div><strong>${escapeHtml(data.location_name || data.country_name || 'Vị trí mô phỏng')}</strong><span id="node-info-coordinates"></span></div></div>
        <dl class="device-info-metrics"><div><dt>Băng thông còn lại*</dt><dd>${format(remaining)} <small>Mbps</small></dd></div><div><dt>Độ trễ cấu hình</dt><dd>${format(data.latency)} <small>ms</small></dd></div></dl>
        <section class="device-info-capacity"><div><span>Đã giữ ${format(reserved)} Mbps</span><strong>${format(data.bandwidth)} Mbps tổng</strong></div><div class="device-capacity-track" role="meter" aria-label="Băng thông đã giữ" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${used.toFixed(1)}"><span style="width:${used}%"></span></div><p>* Phần còn lại trước khi tính tải nền.</p></section>
        <dl class="device-info-details">${row('Nền tảng',data.platform)}${row('Quốc gia',data.country_name)}${row('Châu lục',data.continent)}${row('Độ cao cấu hình',`${format(data.alt)} km`)}${row('Chu kỳ quỹ đạo',data.motion?.type === 'SPACE' ? `${format(data.motion.orbitalPeriodSeconds / 60)} phút` : null)}${row('Độ nghiêng',data.orbit_inclination_deg != null ? `${format(data.orbit_inclination_deg)}°` : null)}${row('Mặt phẳng quỹ đạo',data.orbit_plane)}${row('Tốc độ mô phỏng',data.motion?.speedMetersPerSecond != null ? `${data.motion.speedMetersPerSecond} m/s` : null)}${row('Mốc quỹ đạo UTC',data.epoch_utc)}</dl>
        <footer class="device-info-footer">${data.type === 'SPACE' ? 'Đang hiển thị quỹ đạo minh họa.' : 'Vị trí cập nhật theo mô phỏng.'} Nhấn Esc hoặc nhấn ra ngoài để đóng.</footer>`;
    updateDeviceCoordinates();
}

function updateDeviceCoordinates() {
    if (!selectedDevice) return;
    const position = selectedDevice.position;
    const lat = THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(position.y / position.length(),-1,1)));
    const lng = THREE.MathUtils.radToDeg(Math.atan2(-position.z,position.x));
    document.getElementById('node-info-coordinates').textContent = `${lat.toFixed(4)}°, ${lng.toFixed(4)}° · hiện tại`;
}

scene3D.earth.userData.advanceAnnotations = elapsed => {
    if (!selectedDevice) return;
    if (!selectedDevice.visible || !nodeMarkers.includes(selectedDevice)) { clearDeviceSelection(); return; }
    annotationElapsed += elapsed;
    if (annotationElapsed < .25) return;
    annotationElapsed = 0;
    updateDeviceCoordinates();
    if (selectedOrbitLine && scene3D.earth.userData.deployedNodePositions?.has(selectedDevice.userData.id)) {
        const {radial,tangent} = orbitBasis(selectedDevice);
        const positions = selectedOrbitLine.geometry.getAttribute('position'), point = new THREE.Vector3();
        for (let index=0; index<positions.count; index++) {
            const angle = index / positions.count * Math.PI * 2;
            point.copy(radial).multiplyScalar(Math.cos(angle)).addScaledVector(tangent,Math.sin(angle)).multiplyScalar(selectedDevice.position.length());
            positions.setXYZ(index,point.x,point.y,point.z);
        }
        positions.needsUpdate = true;
        selectedOrbitLine.geometry.computeBoundingSphere();
    }
};

document.getElementById('node-info-close').addEventListener('click', () => {
    clearDeviceSelection(); scene3D.renderer.domElement.focus({preventScroll:true});
});
scene3D.renderer.domElement.tabIndex = 0;
scene3D.renderer.domElement.setAttribute('aria-label','Địa cầu mô phỏng SAGSINs');
document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !selectedDevice) return;
    clearDeviceSelection();
    event.preventDefault(); event.stopImmediatePropagation();
    scene3D.renderer.domElement.focus({preventScroll:true});
}, true);
document.addEventListener('click', event => {
    if (!tooltip.contains(event.target) && !container.contains(event.target)) clearDeviceSelection();
});

container.addEventListener('mousemove', (event) => {
    if (actionSelect.value !== '') return;
    const rect = container.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, scene3D.camera);
    
    const targets = [...nodeMarkers.filter(marker => marker.visible), ...droppedMarkers.filter(drop => drop.marker.visible).map(drop => drop.marker)];
    container.style.cursor = raycaster.intersectObjects(targets,true).some(isNodeHitVisible) ? 'pointer' : 'default';
});

// Mỗi điểm được lưu cùng marker và thông tin hiển thị trên sidebar.
const droppedMarkers = [];

// Routing decisions are computed server-side against a single DB snapshot.
const routing = setupRouting({ scene3D, nodeMarkers, droppedMarkers, createMarker,
    flyGlobeToMarker, resetGlobeView, selectedNodeSummary, actionSelect, actionHint,
    container, topologyReady, refreshNodes: syncDatabaseNodes });
const { disposeRoute, renderDroppedMarkers, refreshDroppedRoutes, focusDroppedMarker } = routing;
topologyReady.then(() => setupTrainingGlobe({ scene3D, nodeMarkers, container,
    scenarioSelect: document.getElementById('routing-scenario') }));

let cameraFlightToken = 0;
function flyGlobeToMarker(marker, distance = 4.65) {
    if (!marker) return Promise.resolve(false);
    const token = ++cameraFlightToken;
    scene3D.earth.updateMatrixWorld(true);
    scene3D.camera.updateMatrixWorld(true);
    const center = scene3D.controls.target.clone();
    const markerWorld = marker.getWorldPosition(new THREE.Vector3());
    const startDirection = scene3D.camera.position.clone().sub(center).normalize();
    const targetDirection = markerWorld.clone().sub(center).normalize();
    const flightRotation = new THREE.Quaternion().setFromUnitVectors(startDirection, targetDirection);
    const startDistance = scene3D.camera.position.distanceTo(center);
    const startedAt = performance.now();
    const duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 1 : 1350;
    scene3D.controls.enabled = false;

    return new Promise((resolve) => {
        const frame = (now) => {
            if (token !== cameraFlightToken) { resolve(false); return; }
            const rawProgress = Math.min(1, (now - startedAt) / duration);
            const eased = rawProgress < 0.5 ? 4 * rawProgress ** 3 : 1 - ((-2 * rawProgress + 2) ** 3) / 2;
            const direction = startDirection.clone().applyQuaternion(new THREE.Quaternion().slerp(flightRotation, eased));
            const cameraDistance = THREE.MathUtils.lerp(startDistance, distance, eased);
            scene3D.camera.position.copy(center).addScaledVector(direction, cameraDistance);
            scene3D.camera.lookAt(center);
            if (rawProgress < 1) {
                requestAnimationFrame(frame);
                return;
            }
            scene3D.controls.target.copy(center);
            scene3D.controls.enabled = true;
            scene3D.controls.update();
            resolve(true);
        };
        requestAnimationFrame(frame);
    });
}

function markerRoot(object, roots) {
    let current = object;
    while (current && !roots.has(current)) current = current.parent;
    return current;
}

function isNodeHitVisible(hit) {
    const globeHit = raycaster.intersectObject(scene3D.earth.userData.earth, false)[0];
    return !globeHit || hit.distance <= globeHit.distance + 0.035;
}

let pointerStart = null;
container.addEventListener('pointerdown', event => { pointerStart = { x: event.clientX, y: event.clientY }; });
container.addEventListener('click', async (event) => {
    if (pointerStart && Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 6) return;
    if (actionSelect.value === "") {
        const rect = container.getBoundingClientRect();
        mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(mouse, scene3D.camera);
        const eventsByMarker = new Map(droppedMarkers.filter(drop => drop.marker.visible).map(drop => [drop.marker,drop]));
        const roots = new Set([...nodeMarkers.filter(marker => marker.visible), ...eventsByMarker.keys()]);
        const nodeHit = raycaster.intersectObjects(nodeMarkers.filter(marker => marker.visible),true).find(isNodeHitVisible);
        const eventHit = raycaster.intersectObjects([...eventsByMarker.keys()],true).find(isNodeHitVisible);
        // A visible event takes priority when it overlaps a device in screen space.
        const hit = eventHit || nodeHit;
        const marker = hit ? markerRoot(hit.object,roots) : null;
        if (!marker) { clearDeviceSelection(); return; }
        const drop = eventsByMarker.get(marker);
        if (drop) {
            clearDeviceSelection();
            focusDroppedMarker(drop);
            return;
        }
        routing.closePanels();
        selectedDevice = marker;
        annotationElapsed = 0;
        showSatelliteOrbit(marker);
        renderDeviceInfo(marker);
        tooltip.hidden = false;
        infoAnimation?.cancel();
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) infoAnimation = tooltip.animate([
            {opacity:0,transform:'translateY(14px)'},{opacity:1,transform:'translateY(0)'}
        ],{duration:480,easing:'cubic-bezier(.22,1,.36,1)'});
        if (selectedNodeSummary) selectedNodeSummary.textContent = `${marker.userData.id} · ${marker.userData.type} · ${marker.userData.country_name || marker.userData.location_name || 'Vị trí mô phỏng'}${marker.userData.type === 'SPACE' ? ' · Đang hiển thị quỹ đạo' : ''}`;
        droppedMarkers.forEach((drop) => { drop.focused = false; });
        renderDroppedMarkers();
        flyGlobeToMarker(marker);
        return;
    }

    clearDeviceSelection();
    // Tính toán tọa độ chuột
    const rect = container.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    // Bắn tia raycaster từ camera
    raycaster.setFromCamera(mouse, scene3D.camera);
    const intersects = raycaster.intersectObject(scene3D.earth.userData.earth, false);

    if (intersects.length > 0) {
        const point = intersects[0].point;
        
        // Tạo Marker mới (Màu Hồng Magenta: 0xff00ff, 255, 0, 255)
        const newMarker = createMarker(0xff00ff, 255, 0, 255, 1.2);
        
        // Convert world coordinates to local coordinates of the earth
        const localPoint = scene3D.earth.worldToLocal(point.clone());
        newMarker.position.copy(localPoint);
        
        scene3D.earth.add(newMarker);
        const actionName = actionSelect.value;
        const radius = localPoint.length();
        const latitude = THREE.MathUtils.radToDeg(Math.asin(localPoint.y / radius));
        const longitude = THREE.MathUtils.radToDeg(Math.atan2(-localPoint.z, localPoint.x));
        await routing.addEvent(latitude, longitude, actionName, newMarker);
    }
});

// Main Sidebar Menu interaction
const pageFrame = document.getElementById('page-frame');
const simulationDiv = document.getElementById('simulation-workspace');
const nodeLegend = document.getElementById('node-legend');
const topHeader = document.getElementById('top-header');
const sidebarLinks = [...document.querySelectorAll('.sidebar-link')];
setupShellNavigation({frame:pageFrame,links:sidebarLinks,
    onSimulation:()=>{
        simulationDiv.hidden=false;
        if(nodeLegend)nodeLegend.style.display='block';
        if(topHeader)topHeader.style.display='flex';
        routing.setVisible(true);
        routing.reloadSavedEvents().catch(error=>console.error('Could not reload saved events:',error));
    },
    onPage:()=>{
        simulationDiv.hidden=true;
        if(nodeLegend)nodeLegend.style.display='none';
        if(topHeader)topHeader.style.display='none';
        routing.setVisible(false);
    }
});
