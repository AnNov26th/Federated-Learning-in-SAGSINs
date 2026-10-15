import * as THREE from "three";
import { createScene } from "./3d/scene.js?v=20261013d";
import { fetchNodes, fetchLinks } from "./api.js";
import { latLngToVector3 } from "./3d/coordinates.js";

const container = document.getElementById("earth-container");

const scene3D = createScene(container);
const selectedNodeSummary = document.getElementById('selected-node-summary');

function resetGlobeView() {
    cameraFlightToken += 1;
    scene3D.controls.enabled = true;
    scene3D.earth.userData.rotationPaused = false;
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

document.getElementById('earth-speed-options')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-earth-speed]');
    if (!button) return;
    const multiplier = Number(button.dataset.earthSpeed);
    scene3D.earth.userData.rotationSpeedMultiplier = multiplier;
    document.querySelectorAll('[data-earth-speed]').forEach((option) => {
        option.setAttribute('aria-pressed', String(option === button));
    });
    document.getElementById('earth-speed-status').textContent = `Đang xoay ở tốc độ ${multiplier}×`;
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
        const response = await fetch('/api/links/generate-nearby?neighbors_per_node=2&max_distance_km=1500', { method: 'POST' });
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
let networkLinks = [];
const routeLines = new Map();
const movingDevices = [];
const orbitLineMaterial = new THREE.LineBasicMaterial({ color: 0xffbd69, transparent: true, opacity: 0.75 });
let selectedOrbitLine = null;

function createDeviceMotion(node, initialPosition) {
    const radial = initialPosition.clone().normalize();
    const inclination = THREE.MathUtils.degToRad(Number(node.orbit_inclination_deg) || 53);
    const plane = Math.max(0, Number(node.orbit_plane || 1) - 1);
    const raan = plane * Math.PI / 3;
    const orbitNormal = new THREE.Vector3(Math.sin(inclination) * Math.sin(raan), Math.cos(inclination), Math.sin(inclination) * Math.cos(raan));
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
    const [nodes, links] = await Promise.all([fetchNodes(), fetchLinks()]);
    networkLinks = links;
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
let nextDropId = 1;
const dropList = document.getElementById('drop-list');
const dropCount = document.getElementById('drop-count');

const SERVICE_PROFILES = {
    Message: { latencyWeight: 0.55, capacityWeight: 0.1, label: 'ưu tiên tin cậy, chấp nhận trễ vừa' },
    'Video Call': { latencyWeight: 0.45, capacityWeight: 0.4, label: 'cân bằng độ trễ và băng thông' },
    'Watch Video': { latencyWeight: 0.2, capacityWeight: 0.75, label: 'ưu tiên băng thông' },
    Gaming: { latencyWeight: 0.8, capacityWeight: 0.08, label: 'ưu tiên độ trễ thấp' },
    Emergency: { latencyWeight: 1, capacityWeight: 0.15, label: 'ưu tiên cao nhất và độ trễ thấp' },
};

function disposeRoute(dropId) {
    const line = routeLines.get(dropId);
    if (!line) return;
    scene3D.earth.remove(line);
    line.geometry.dispose();
    line.material.dispose();
    routeLines.delete(dropId);
}

function routePathCost(path, adjacency, profile) {
    let latency = 0;
    let bottleneck = Infinity;
    for (let index = 1; index < path.length; index += 1) {
        const edge = adjacency.get(path[index - 1]).get(path[index]);
        latency += Number(edge.latency) || 0;
        bottleneck = Math.min(bottleneck, Number(edge.bandwidth) || 0);
    }
    for (const id of path) {
        const node = nodeMarkers.find((marker) => marker.userData.id === id)?.userData;
        latency += Number(node?.latency) || 0;
    }
    // The bandwidth term penalizes a narrow bottleneck; latency remains in ms.
    const capacityPenalty = bottleneck > 0 ? (100 / bottleneck) * profile.capacityWeight : Infinity;
    return { cost: latency * profile.latencyWeight + capacityPenalty, latency, bottleneck };
}

function findBestRoute(startId, targetIds, profile, links) {
    const active = new Map(nodeMarkers
        .filter((marker) => String(marker.userData.status).toUpperCase() === 'ACTIVE')
        .map((marker) => [marker.userData.id, marker.userData]));
    const adjacency = new Map([...active.keys()].map((id) => [id, new Map()]));
    for (const link of links) {
        if (String(link.status).toUpperCase() !== 'ACTIVE' || !active.has(link.source) || !active.has(link.target)) continue;
        adjacency.get(link.source).set(link.target, link);
        adjacency.get(link.target).set(link.source, link);
    }

    const distances = new Map([[startId, 0]]);
    const previous = new Map();
    const remaining = new Set(active.keys());
    while (remaining.size) {
        let current = null;
        for (const id of remaining) {
            if (current === null || (distances.get(id) ?? Infinity) < (distances.get(current) ?? Infinity)) current = id;
        }
        if (current === null || !Number.isFinite(distances.get(current))) break;
        remaining.delete(current);
        if (targetIds.includes(current)) {
            const path = [current];
            while (previous.has(path[0])) path.unshift(previous.get(path[0]));
            return { path, ...routePathCost(path, adjacency, profile) };
        }
        for (const [neighbor, link] of adjacency.get(current) || []) {
            if (!remaining.has(neighbor)) continue;
            const nodeLatency = Number(active.get(neighbor)?.latency) || 0;
            const edgeCost = (Number(link.latency) + nodeLatency) * profile.latencyWeight
                + (100 / Math.max(Number(link.bandwidth), 0.001)) * profile.capacityWeight;
            const next = distances.get(current) + edgeCost;
            if (next < (distances.get(neighbor) ?? Infinity)) {
                distances.set(neighbor, next);
                previous.set(neighbor, current);
            }
        }
    }
    return null;
}

function virtualDistanceKm(first, second) {
    const toCartesian = (node) => {
        const lat = THREE.MathUtils.degToRad(Number(node.lat));
        const lng = THREE.MathUtils.degToRad(Number(node.lng));
        const radius = 6371 + Math.max(0, Number(node.alt) || 0);
        return new THREE.Vector3(
            radius * Math.cos(lat) * Math.cos(lng),
            radius * Math.sin(lat),
            -radius * Math.cos(lat) * Math.sin(lng)
        );
    };
    return toCartesian(first).distanceTo(toCartesian(second));
}

function buildVirtualLinks(activeMarkers) {
    const nodes = activeMarkers.map((marker) => marker.userData);
    const candidates = [];
    for (let first = 0; first < nodes.length; first += 1) {
        for (let second = first + 1; second < nodes.length; second += 1) {
            candidates.push({ first, second, distance: virtualDistanceKm(nodes[first], nodes[second]) });
        }
    }
    candidates.sort((a, b) => a.distance - b.distance);

    const parent = nodes.map((_, index) => index);
    const find = (index) => {
        while (parent[index] !== index) {
            parent[index] = parent[parent[index]];
            index = parent[index];
        }
        return index;
    };
    const links = [];
    const connectedPairs = new Set();
    const addLink = (candidate) => {
        const source = nodes[candidate.first];
        const target = nodes[candidate.second];
        const pairKey = `${source.id}\u0000${target.id}`;
        if (connectedPairs.has(pairKey)) return;
        connectedPairs.add(pairKey);
        links.push({
            source: source.id,
            target: target.id,
            distance: candidate.distance,
            bandwidth: Math.max(0.1, Math.min(Number(source.bandwidth) || 0.1, Number(target.bandwidth) || 0.1)),
            latency: Math.max(1, candidate.distance / 299.792458),
            status: 'ACTIVE',
            synthetic: true,
        });
        const firstRoot = find(candidate.first);
        const secondRoot = find(candidate.second);
        if (firstRoot !== secondRoot) parent[secondRoot] = firstRoot;
    };

    // Give every node its two nearest neighbors, then bridge any remaining components.
    nodes.forEach((_, index) => {
        candidates.filter((edge) => edge.first === index || edge.second === index)
            .slice(0, 2)
            .forEach(addLink);
    });
    for (const candidate of candidates) {
        if (find(candidate.first) !== find(candidate.second)) addLink(candidate);
    }
    return links;
}

function drawRoute(drop) {
    disposeRoute(drop.id);
    if (!drop.route?.path?.length) return;
    const routePositions = [drop.marker.position.clone()];
    for (const id of drop.route.path) {
        const marker = nodeMarkers.find((item) => item.userData.id === id);
        if (marker) routePositions.push(marker.position.clone());
    }
    if (routePositions.length < 2) return;

    const points = [];
    for (let segment = 0; segment < routePositions.length - 1; segment += 1) {
        const from = routePositions[segment];
        const to = routePositions[segment + 1];
        const fromDirection = from.clone().normalize();
        const toDirection = to.clone().normalize();
        const angle = fromDirection.angleTo(toDirection);
        const steps = Math.max(8, Math.ceil(angle * 20));
        for (let step = segment === 0 ? 0 : 1; step <= steps; step += 1) {
            const t = step / steps;
            const direction = fromDirection.clone().lerp(toDirection, t).normalize();
            const radius = THREE.MathUtils.lerp(from.length(), to.length(), t) + 0.055;
            points.push(direction.multiplyScalar(radius));
        }
    }
    const emergency = drop.action === 'Emergency';
    const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: emergency ? 0xff596d : 0x63d9ff, transparent: true, opacity: 0.95 })
    );
    line.userData.isEventRoute = true;
    scene3D.earth.add(line);
    routeLines.set(drop.id, line);
}

function haversineKm(lat1, lng1, lat2, lng2) {
    const radians = (degrees) => degrees * Math.PI / 180;
    const dLat = radians(lat2 - lat1);
    const dLng = radians(lng2 - lng1);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(radians(lat1)) * Math.cos(radians(lat2)) * Math.sin(dLng / 2) ** 2;
    return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
}

function calculateEventRoute(drop) {
    drop.route = null;
    const activeMarkers = nodeMarkers.filter((marker) => String(marker.userData.status).toUpperCase() === 'ACTIVE');
    if (!activeMarkers.length) {
        drop.status = 'Không có node ACTIVE';
        drop.route = null;
        return;
    }
    const source = activeMarkers.reduce((nearest, marker) => {
        const distance = haversineKm(drop.lat, drop.lng, Number(marker.userData.lat), Number(marker.userData.lng));
        return !nearest || distance < nearest.distance ? { marker, distance } : nearest;
    }, null);
    const groundNodes = activeMarkers.filter((marker) => marker.userData.type === 'GROUND' && marker !== source.marker);
    if (!groundNodes.length) {
        drop.status = 'Cần node GROUND làm đích';
        drop.route = null;
        return;
    }
    const profile = SERVICE_PROFILES[drop.action] || SERVICE_PROFILES.Message;
    const activeLinks = networkLinks.filter((link) => String(link.status).toUpperCase() === 'ACTIVE');
    let routeMode = activeLinks.length ? 'configured' : 'estimated';
    let routingLinks = activeLinks.length ? activeLinks : buildVirtualLinks(activeMarkers);
    const targetIds = groundNodes
        .slice()
        .sort((a, b) => Number(b.userData.bandwidth) - Number(a.userData.bandwidth))
        .map((marker) => marker.userData.id);
    const searchTargets = () => {
        for (const targetId of targetIds) {
            const route = findBestRoute(source.marker.userData.id, [targetId], profile, routingLinks);
            if (route) return route;
        }
        return null;
    };
    let result = searchTargets();
    if (!result && routeMode === 'configured') {
        routeMode = 'estimated';
        routingLinks = buildVirtualLinks(activeMarkers);
        result = searchTargets();
    }
    if (!result) {
        drop.status = `Không tìm thấy tuyến tới GROUND (${source.marker.userData.id})`;
        drop.route = null;
        return;
    }
    drop.route = {
        ...result,
        sourceId: source.marker.userData.id,
        targetId: result.path[result.path.length - 1],
        accessDistanceKm: source.distance,
        profile: profile.label,
        mode: routeMode,
    };
    drop.status = `${routeMode === 'estimated' ? 'Tuyến ước tính · ' : ''}${result.path.length - 1} hop · ${drop.route.targetId}`;
}

async function refreshDroppedRoutes() {
    await topologyReady;
    networkLinks = await fetchLinks();
    droppedMarkers.forEach((drop) => {
        calculateEventRoute(drop);
        drawRoute(drop);
    });
    renderDroppedMarkers();
}

function renderDroppedMarkers() {
    if (!dropList || !dropCount) return;
    dropCount.textContent = `${droppedMarkers.length} điểm`;
    if (droppedMarkers.length === 0) {
        dropList.innerHTML = '<div class="drop-empty"><i class="fa-solid fa-location-dot"></i><span>Chưa có điểm nào</span><small>Chọn sự kiện rồi nhấn lên địa cầu</small></div>';
        return;
    }

    dropList.innerHTML = droppedMarkers.map((drop) => `
        <article class="drop-item${drop.focused ? ' selected' : ''}" role="listitem" data-drop-id="${drop.id}">
            <button class="drop-focus" type="button" data-focus-drop="${drop.id}" aria-label="Focus ${escapeHtml(drop.name)}"><i class="fa-solid fa-location-crosshairs"></i></button>
            <button class="drop-info" type="button" data-focus-drop="${drop.id}" aria-label="Focus vào ${escapeHtml(drop.name)}">
                <span class="drop-name-row"><span class="drop-name">${escapeHtml(drop.name)} · ${escapeHtml(drop.action)}</span><span class="drop-status">${drop.focused ? 'Đang xem' : 'Đã đặt'}</span></span>
                <span class="drop-detail">${drop.lat.toFixed(4)}°, ${drop.lng.toFixed(4)}° · ${escapeHtml(drop.status)}</span>
                ${drop.route ? `<span class="route-detail"><i class="fa-solid fa-route" aria-hidden="true"></i> ${drop.route.path.map(escapeHtml).join(' → ')}<br>${drop.route.latency.toFixed(1)} ms · ${Number.isFinite(drop.route.bottleneck) ? drop.route.bottleneck.toFixed(1) : '—'} Mbps bottleneck · tiếp cận ${drop.route.accessDistanceKm.toFixed(1)} km<br>${escapeHtml(drop.route.profile)}<small class="route-mode">${drop.route.mode === 'estimated' ? 'Topology ảo ước tính · chưa lưu link' : 'Định tuyến theo link ACTIVE'}</small></span>` : `<span class="route-detail route-unavailable">${escapeHtml(drop.status)}</span>`}
            </button>
            <button class="drop-delete" type="button" data-delete-drop="${drop.id}" aria-label="Xóa ${escapeHtml(drop.name)}"><i class="fa-solid fa-trash-can"></i></button>
        </article>
    `).join('');
}

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
    const duration = 1350;
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

function focusDroppedMarker(drop) {
    droppedMarkers.forEach((item) => { item.focused = item.id === drop.id; });
    if (selectedNodeSummary) selectedNodeSummary.textContent = `${drop.name} · ${drop.action} · ${drop.lat.toFixed(3)}°, ${drop.lng.toFixed(3)}°`;
    flyGlobeToMarker(drop.marker, 4.75);
    renderDroppedMarkers();
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

const attackButton = document.getElementById('btn-simulate-attack');
const attackTargetLayer = document.getElementById('attack-target-layer');
const attackStatus = document.getElementById('attack-status');
let attackRunToken = 0;
let attackEffects = [];

function syntheticExposureScore(node) {
    // Stable demo score to make the simulation repeatable; it is not a security assessment.
    let hash = 0;
    for (const character of String(node.id)) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
    return 55 + (hash % 45);
}

function clearAttackEffects() {
    for (const effect of attackEffects) {
        effect.geometry?.dispose();
        effect.material?.dispose();
        scene3D.scene.remove(effect);
    }
    attackEffects = [];
}

function animateAttackPulse(start, end, color, duration, runToken) {
    const pulse = new THREE.Mesh(
        new THREE.SphereGeometry(0.035, 12, 12),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 })
    );
    scene3D.scene.add(pulse);
    attackEffects.push(pulse);
    const began = performance.now();
    return new Promise((resolve) => {
        const frame = (now) => {
            if (runToken !== attackRunToken) { resolve(false); return; }
            const progress = Math.min(1, (now - began) / duration);
            const eased = 1 - (1 - progress) ** 3;
            pulse.position.lerpVectors(start, end, eased);
            if (progress < 1) requestAnimationFrame(frame);
            else resolve(true);
        };
        requestAnimationFrame(frame);
    });
}

async function runAttackSimulation() {
    const requestedLayer = attackTargetLayer.value;
    const candidates = nodeMarkers
        .filter((marker) => requestedLayer === 'ANY' || String(marker.userData.type).toUpperCase() === requestedLayer)
        .sort((a, b) => syntheticExposureScore(b.userData) - syntheticExposureScore(a.userData));
    if (!candidates.length) {
        attackStatus.textContent = 'Không có node phù hợp để mô phỏng trong lớp đã chọn.';
        return;
    }

    const runToken = ++attackRunToken;
    clearAttackEffects();
    attackButton.disabled = true;
    const target = candidates[0];
    const targetData = target.userData;
    const score = syntheticExposureScore(targetData);
    attackStatus.textContent = `AI đang chọn mục tiêu mô phỏng… ${targetData.id} · điểm phơi nhiễm giả lập ${score}/100.`;
    if (selectedNodeSummary) selectedNodeSummary.textContent = `Mục tiêu mô phỏng: ${targetData.id} · ${targetData.type}`;
    const arrived = await flyGlobeToMarker(target);
    if (!arrived || runToken !== attackRunToken) {
        if (runToken === attackRunToken) attackButton.disabled = false;
        return;
    }

    scene3D.earth.updateMatrixWorld(true);
    const targetPosition = target.getWorldPosition(new THREE.Vector3());
    const externalPosition = targetPosition.clone().normalize().multiplyScalar(targetPosition.length() + 1.15);
    const route = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([externalPosition, targetPosition]),
        new THREE.LineBasicMaterial({ color: 0xff5470, transparent: true, opacity: 0.88 })
    );
    scene3D.scene.add(route);
    attackEffects.push(route);

    attackStatus.textContent = `Đang mô phỏng AI truy cập node ${targetData.id}…`;
    if (!await animateAttackPulse(externalPosition, targetPosition, 0xff5470, 900, runToken)) return;
    attackStatus.textContent = `Đang mô phỏng đánh cắp dữ liệu thử nghiệm từ ${targetData.id}…`;
    if (!await animateAttackPulse(targetPosition, externalPosition, 0xffb45e, 1500, runToken)) return;

    const syntheticMb = (2.4 + (score % 17) * 0.35).toFixed(1);
    attackStatus.textContent = `Mô phỏng hoàn tất: ${syntheticMb} MB dữ liệu giả lập được đánh cắp từ ${targetData.id}. Đây là sự kiện minh họa, không phải dữ liệu thật.`;
    attackButton.disabled = false;
    window.setTimeout(() => {
        if (runToken === attackRunToken) clearAttackEffects();
    }, 2200);
}

attackButton?.addEventListener('click', () => {
    runAttackSimulation().catch((error) => {
        attackStatus.textContent = `Không thể chạy mô phỏng: ${error.message}`;
        attackButton.disabled = false;
    });
});

function disposeDroppedMarker(drop) {
    scene3D.earth.remove(drop.marker);
    drop.marker.traverse((object) => {
        object.geometry?.dispose();
        if (Array.isArray(object.material)) object.material.forEach((material) => {
            material.map?.dispose();
            material.dispose();
        });
        else if (object.material) {
            object.material.map?.dispose();
            object.material.dispose();
        }
    });
}

dropList?.addEventListener('click', (event) => {
    const deleteButton = event.target.closest('[data-delete-drop]');
    if (deleteButton) {
        const index = droppedMarkers.findIndex((drop) => drop.id === Number(deleteButton.dataset.deleteDrop));
        if (index < 0) return;
        const wasFocused = droppedMarkers[index].focused;
        disposeRoute(droppedMarkers[index].id);
        disposeDroppedMarker(droppedMarkers[index]);
        droppedMarkers.splice(index, 1);
        if (wasFocused) {
            resetGlobeView();
        }
        renderDroppedMarkers();
        return;
    }

    const focusButton = event.target.closest('[data-focus-drop]');
    if (focusButton) {
        const drop = droppedMarkers.find((item) => item.id === Number(focusButton.dataset.focusDrop));
        if (drop) focusDroppedMarker(drop);
    }
});

container.addEventListener('click', async (event) => {
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
        const dropId = nextDropId++;
        const drop = {
            id: dropId,
            name: `Điểm ${String(dropId).padStart(2, '0')}`,
            action: actionName,
            lat: latitude,
            lng: longitude,
            status: 'Đang tính tuyến…',
            marker: newMarker,
            focused: false,
        };
        droppedMarkers.push(drop);
        actionSelect.value = "";
        actionHint.style.display = 'none';
        container.style.cursor = 'default';
        renderDroppedMarkers();
        await topologyReady;
        networkLinks = await fetchLinks();
        calculateEventRoute(drop);
        drawRoute(drop);
        renderDroppedMarkers();
    }
});

// Main Sidebar Menu interaction
const pageFrame = document.getElementById('page-frame');
const simulationDiv = document.getElementById('simulation');
const actionPanel = document.getElementById('action-panel');
const nodeLegend = document.getElementById('node-legend');
const topHeader = document.getElementById('top-header');
const earthSpeedPanel = document.getElementById('earth-speed-panel');
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
            if(simulationDiv) simulationDiv.style.display = 'block';
            if(actionPanel) actionPanel.style.display = 'block';
            if(nodeLegend) nodeLegend.style.display = 'block';
            if(topHeader) topHeader.style.display = 'block';
            if(earthSpeedPanel) earthSpeedPanel.style.display = 'block';
            refreshDroppedRoutes().catch((error) => {
                console.error('Could not refresh event routes:', error);
            });
            
        } else if (pageRoutes[menuName]) {
            // Hide 3D globe and panels
            if(simulationDiv) simulationDiv.style.display = 'none';
            if(actionPanel) actionPanel.style.display = 'none';
            if(nodeLegend) nodeLegend.style.display = 'none';
            if(topHeader) topHeader.style.display = 'none';
            if(earthSpeedPanel) earthSpeedPanel.style.display = 'none';
            
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

window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin || event.data?.type !== 'sagsin:navigate') return;
    const pageName = Object.keys(pageRoutes).find((name) => pageRoutes[name] === event.data.href);
    const targetLink = [...sidebarLinks].find((link) => link.querySelector('.link-text')?.textContent.trim() === pageName);
    if (targetLink) targetLink.click();
});
