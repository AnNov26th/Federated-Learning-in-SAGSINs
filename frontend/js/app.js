import * as THREE from "three";
import { createScene } from "./3d/scene.js?v=20261023f";
import { fetchNodes } from "./api.js";
import { latLngToVector3 } from "./3d/coordinates.js";
import { setupRouting } from "./routing.js?v=20261023f";

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
    removeSelectedOrbit();
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
const nodeMarkers = []; // Mảng chứa các marker thiết bị để raycast hover
const movingDevices = [];
const orbitLineMaterial = new THREE.LineBasicMaterial({ color: 0xffbd69, transparent: true, opacity: 0.75 });
let selectedOrbitLine = null;

function createDeviceMotion(node, initialPosition) {
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
    if (scene3D.earth.userData.routingSnapshot) return;
    for (const device of movingDevices) {
        device.phase = (device.phase || 0) + elapsedSeconds * device.angularSpeed;
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

function showSatelliteOrbit(marker) {
    removeSelectedOrbit();
    if (marker?.userData?.type !== 'SPACE' || !marker.userData.motion) return;
    const motion = marker.userData.motion;
    const points = [];
    for (let step = 0; step < 180; step += 1) {
        const angle = (step / 180) * Math.PI * 2;
        points.push(motion.radial.clone().multiplyScalar(Math.cos(angle)).addScaledVector(motion.tangent, Math.sin(angle)).multiplyScalar(motion.radius));
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
    removeSelectedOrbit();
}

// --- TOOLTIP LOGIC ---
const tooltip = document.getElementById('node-tooltip');
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
})[character]);

container.addEventListener('mousemove', (event) => {
    // Chỉ check hover nếu không đang chọn action
    if (actionSelect.value !== "") {
        tooltip.style.opacity = 0;
        return;
    }

    const rect = container.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, scene3D.camera);
    
    // Check giao cắt với các thiết bị
    const intersects = raycaster.intersectObjects(nodeMarkers, true).filter(isNodeHitVisible);
    
    if (intersects.length > 0) {
        // Tìm marker cha chứa userData (vì intersect trúng mesh con)
        let object = intersects[0].object;
        while (object.parent && !object.userData.id) {
            object = object.parent;
        }

        if (object.userData && object.userData.id) {
            const data = object.userData;
            tooltip.innerHTML = `
                <h4>${escapeHtml(data.id)}</h4>
                <p><span>Type:</span> <span class="tt-val">${escapeHtml(data.type)}</span></p>
                ${data.platform ? `<p><span>Platform:</span> <span class="tt-val">${escapeHtml(data.platform)}</span></p>` : ""}
                ${data.country_name ? `<p><span>Country:</span> <span class="tt-val">${escapeHtml(data.country_name)}</span></p>` : ""}
                ${data.continent ? `<p><span>Continent:</span> <span class="tt-val">${escapeHtml(data.continent)}</span></p>` : ""}
                ${data.location_name ? `<p><span>Representative location:</span> <span class="tt-val">${escapeHtml(data.location_name)}</span></p>` : ""}
                <p><span>Coordinates:</span> <span class="tt-val">${Number(data.lat).toFixed(4)}, ${Number(data.lng).toFixed(4)}</span></p>
                ${data.is_simulated ? `<p><span>Location type:</span> <span class="tt-val">${data.type === "GROUND" ? "Simulated city representative" : "Simulated position"}</span></p>` : ""}
                ${data.orbit_inclination_deg != null ? `<p><span>Inclination:</span> <span class="tt-val">${data.orbit_inclination_deg}°</span></p>` : ""}
                ${data.orbit_plane != null ? `<p><span>Orbit plane:</span> <span class="tt-val">${data.orbit_plane}</span></p>` : ""}
                ${data.orbit_phase_deg != null ? `<p><span>Orbit phase:</span> <span class="tt-val">${data.orbit_phase_deg}°</span></p>` : ""}
                ${data.motion?.type === "SPACE" ? `<p><span>Orbital period:</span> <span class="tt-val">${(data.motion.orbitalPeriodSeconds / 60).toFixed(1)} min</span></p>` : ""}
                ${data.motion?.type === "SEA" || data.motion?.type === "AIR" ? `<p><span>Simulated speed:</span> <span class="tt-val">${data.motion.speedMetersPerSecond} m/s · waypoint path</span></p>` : ""}
                ${data.epoch_utc ? `<p><span>Epoch (UTC):</span> <span class="tt-val">${escapeHtml(data.epoch_utc)}</span></p>` : ""}
                <p><span>Alt:</span> <span class="tt-val">${data.alt} km</span></p>
                <p><span>Bandwidth:</span> <span class="tt-val">${data.bandwidth} Mbps</span></p>
                <p><span>Điểm đang dùng:</span> <span class="tt-val">${data.event_connections || 0}</span></p>
                <p><span>Đã giữ:</span> <span class="tt-val">${Number(data.reserved_bandwidth_mbps || 0).toFixed(1)} Mbps</span></p>
                <p><span>Còn trước tải nền:</span> <span class="tt-val">${Number(data.remaining_bandwidth_mbps ?? data.bandwidth).toFixed(1)} Mbps</span></p>
                <p><span>Latency:</span> <span class="tt-val">${data.latency} ms</span></p>
            `;
            
            tooltip.style.left = event.clientX + 'px';
            tooltip.style.top = event.clientY + 'px';
            tooltip.style.opacity = 1;
            container.style.cursor = 'pointer';
        }
    } else {
        tooltip.style.opacity = 0;
        container.style.cursor = 'default';
    }
});

// Mỗi điểm được lưu cùng marker và thông tin hiển thị trên sidebar.
const droppedMarkers = [];

// Routing decisions are computed server-side against a single DB snapshot.
const routing = setupRouting({ scene3D, nodeMarkers, droppedMarkers, createMarker,
    flyGlobeToMarker, resetGlobeView, selectedNodeSummary, actionSelect, actionHint,
    container, topologyReady, refreshNodes: syncDatabaseNodes });
const { disposeRoute, renderDroppedMarkers, refreshDroppedRoutes, focusDroppedMarker } = routing;

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

function markerRoot(object) {
    let current = object;
    while (current && !current.userData?.id) current = current.parent;
    return current?.userData?.id ? current : null;
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
        const hit = raycaster.intersectObjects(nodeMarkers, true).find(isNodeHitVisible);
        const marker = hit ? markerRoot(hit.object) : null;
        if (!marker) return;
        showSatelliteOrbit(marker);
        if (selectedNodeSummary) selectedNodeSummary.textContent = `${marker.userData.id} · ${marker.userData.type} · ${marker.userData.country_name || marker.userData.location_name || 'Vị trí mô phỏng'}${marker.userData.type === 'SPACE' ? ' · Đang hiển thị quỹ đạo' : ''}`;
        droppedMarkers.forEach((drop) => { drop.focused = false; });
        renderDroppedMarkers();
        flyGlobeToMarker(marker);
        return;
    }

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
const uiBuild = '20261013c';

const sidebarLinks = document.querySelectorAll('.sidebar-link');
const pageRoutes = {
    "Dashboard": "/dashboard.html",
    "Network": "/network.html",
    "Participants": "/participants.html",
    "FL Training": "/fl.html",
    "Experiments": "/experiments.html",
    "Results": "/results.html",
};
sidebarLinks.forEach(link => {
    link.setAttribute('aria-label', link.querySelector('.link-text')?.textContent.trim() || link.dataset.tooltip);
    link.addEventListener('click', (e) => {
        e.preventDefault();
        // Remove active class from all
        sidebarLinks.forEach(l => l.classList.remove('active'));
        // Add to clicked
        const currentLink = e.currentTarget;
        currentLink.classList.add('active');
        
        const menuName = currentLink.querySelector('.link-text').textContent.trim();
        console.log(`Chuyển sang trang: ${menuName}`);
        
        if (menuName === "Simulation") {
            // Hide iframe
            if(pageFrame) {
                pageFrame.style.display = 'none';
                pageFrame.src = "";
            }
            // Show 3D globe and panels
            if(simulationDiv) simulationDiv.hidden = false;
            if(nodeLegend) nodeLegend.style.display = 'block';
            if(topHeader) topHeader.style.display = 'flex';
            routing.setVisible(true);
            routing.reloadSavedEvents().catch((error) => {
                console.error('Could not reload saved events:', error);
            });
            
        } else if (pageRoutes[menuName]) {
            // Hide 3D globe and panels
            if(simulationDiv) simulationDiv.hidden = true;
            if(nodeLegend) nodeLegend.style.display = 'none';
            if(topHeader) topHeader.style.display = 'none';
            routing.setVisible(false);
            
            // Show iframe
            if(pageFrame) {
                const route = pageRoutes[menuName];
                pageFrame.src = `${route}${route.includes('?') ? '&' : '?'}ui=${uiBuild}`;
                pageFrame.style.display = 'block';
            }
        } else {
            alert(`Sắp tới sẽ load giao diện chức năng: ${menuName}`);
        }
    });
});

window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin || event.data?.type !== 'sagsin:navigate') return;
    const pageName = Object.keys(pageRoutes).find((name) => pageRoutes[name] === event.data.href);
    const targetLink = [...sidebarLinks].find((link) => link.querySelector('.link-text')?.textContent.trim() === pageName);
    if (targetLink) targetLink.click();
});
