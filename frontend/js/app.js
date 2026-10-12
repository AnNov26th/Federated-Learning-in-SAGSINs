import * as THREE from "three";
import { createScene } from "./3d/scene.js?v=20261013c";
import { fetchNodes } from "./api.js";
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

// Select Action Combobox
const actionSelect = document.getElementById('action-select');
const actionHint = document.getElementById('action-hint');

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
    const nodes = await fetchNodes();
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
plotDatabaseNodes();

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

container.addEventListener('click', (event) => {
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
        droppedMarkers.push({
            id: nextDropId,
            name: `Điểm ${String(nextDropId).padStart(2, '0')}`,
            action: actionName,
            lat: latitude,
            lng: longitude,
            status: 'Đã đặt trên mô hình',
            marker: newMarker,
            focused: false,
        });
        nextDropId += 1;
        renderDroppedMarkers();
        
        // Reset sau khi chọn
        actionSelect.value = "";
        actionHint.style.display = 'none';
        container.style.cursor = 'default';
    }
});

// Main Sidebar Menu interaction
const pageFrame = document.getElementById('page-frame');
const simulationDiv = document.getElementById('simulation');
const actionPanel = document.getElementById('action-panel');
const nodeLegend = document.getElementById('node-legend');
const topHeader = document.getElementById('top-header');
const uiBuild = '20261013b';

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
            
        } else if (pageRoutes[menuName]) {
            // Hide 3D globe and panels
            if(simulationDiv) simulationDiv.style.display = 'none';
            if(actionPanel) actionPanel.style.display = 'none';
            if(nodeLegend) nodeLegend.style.display = 'none';
            if(topHeader) topHeader.style.display = 'none';
            
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
