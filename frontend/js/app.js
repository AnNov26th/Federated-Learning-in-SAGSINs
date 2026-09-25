import * as THREE from "three";
import { createScene } from "./3d/scene.js";
import { fetchNodes } from "./api.js";

const container = document.getElementById("earth-container");

const scene3D = createScene(container);

// --- ACTION PANEL EVENT LISTENERS ---

// System Actions
document.getElementById('btn-toggle-3d').addEventListener('click', () => {
    alert('Chức năng chuyển đổi 3D / 2D đang được phát triển!');
});

document.getElementById('btn-reset-cam').addEventListener('click', () => {
    if (scene3D.camera && scene3D.controls) {
        scene3D.camera.position.set(0, 0, 6);
        scene3D.controls.target.set(0, 0, 0);
        scene3D.controls.update();
    }
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

// Hàm chuyển đổi Toạ độ (Lat, Lng, Alt) sang Vector3 trên mặt cầu 3D
function latLngToVector3(lat, lng, altKm) {
    const EARTH_RADIUS = 2; // from earth.js
    
    // Scale down altitude (Mô phỏng khoảng cách xa hơn cho dễ nhìn)
    let altUnits = 0;
    if (altKm > 0) {
        if (altKm < 50) { // Tầng Air (UAV, HAP, Aircraft...)
            altUnits = 0.05 + (altKm / 50) * 0.15; // Nổi nhẹ (0.05 -> 0.2 units)
        } else if (altKm <= 2000) { // LEO
            altUnits = 0.3 + (altKm / 2000) * 0.3; // Nổi vừa phải (0.3 -> 0.6 units)
        } else if (altKm <= 20000) { // MEO
            altUnits = 0.7 + (altKm / 20000) * 0.5; // Xa hơn (0.7 -> 1.2 units)
        } else { // GEO
            altUnits = 1.3 + (altKm / 40000) * 1.5; // Rất xa (> 1.3 units)
        }
    }
    
    const r = EARTH_RADIUS + altUnits + 0.01; // Thêm 0.01 để nổi lên trên bề mặt trái đất
    
    const phi = (90 - lat) * (Math.PI / 180);
    const theta = (lng + 180) * (Math.PI / 180);
    
    const x = - (r) * Math.sin(phi) * Math.cos(theta);
    const y = (r) * Math.cos(phi);
    const z = (r) * Math.sin(phi) * Math.sin(theta);
    
    return new THREE.Vector3(x, y, z);
}

// Lấy danh sách nodes từ backend và vẽ lên bản đồ
const nodeMarkers = []; // Mảng chứa các marker thiết bị để raycast hover
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
        
        scene3D.earth.add(marker);
        nodeMarkers.push(marker);
    });
}

// Khởi chạy vẽ nodes
plotDatabaseNodes();

// --- TOOLTIP LOGIC ---
const tooltip = document.getElementById('node-tooltip');

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
    const intersects = raycaster.intersectObjects(nodeMarkers, true);
    
    if (intersects.length > 0) {
        // Tìm marker cha chứa userData (vì intersect trúng mesh con)
        let object = intersects[0].object;
        while (object.parent && !object.userData.id) {
            object = object.parent;
        }

        if (object.userData && object.userData.id) {
            const data = object.userData;
            tooltip.innerHTML = `
                <h4>${data.id}</h4>
                <p><span>Type:</span> <span class="tt-val">${data.type}</span></p>
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

// Tạo mảng chứa các điểm drop
const droppedMarkers = [];

container.addEventListener('click', (event) => {
    if (actionSelect.value === "") return; // Nếu chưa chọn chức năng thì không làm gì

    // Tính toán tọa độ chuột
    const rect = container.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    // Bắn tia raycaster từ camera
    raycaster.setFromCamera(mouse, scene3D.camera);
    const intersects = raycaster.intersectObject(scene3D.earth);

    if (intersects.length > 0) {
        const point = intersects[0].point;
        
        // Tạo Marker mới (Màu Hồng Magenta: 0xff00ff, 255, 0, 255)
        const newMarker = createMarker(0xff00ff, 255, 0, 255, 1.2);
        
        // Convert world coordinates to local coordinates of the earth
        const localPoint = scene3D.earth.worldToLocal(point.clone());
        newMarker.position.copy(localPoint);
        
        scene3D.earth.add(newMarker);
        droppedMarkers.push(newMarker);

        const actionName = actionSelect.value;
        alert(`Bạn đã chọn vị trí cho sự kiện: ${actionName}\nHệ thống bắt đầu tính toán tuyến đường truyền dẫn...`);
        
        const statusEl = document.getElementById('backend-status');
        if (statusEl) {
            statusEl.innerText = `Calculating route for: ${actionName}...`;
            statusEl.style.color = "#ffaa00";
        }
        
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

const sidebarLinks = document.querySelectorAll('.sidebar-link');
sidebarLinks.forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        // Remove active class from all
        sidebarLinks.forEach(l => l.classList.remove('active'));
        // Add to clicked
        const currentLink = e.currentTarget;
        currentLink.classList.add('active');
        
        const menuName = currentLink.querySelector('.link-text').innerText.trim();
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
            
        } else if (menuName === "Dashboard") {
            // Hide 3D globe and panels
            if(simulationDiv) simulationDiv.style.display = 'none';
            if(actionPanel) actionPanel.style.display = 'none';
            if(nodeLegend) nodeLegend.style.display = 'none';
            if(topHeader) topHeader.style.display = 'none';
            
            // Show iframe
            if(pageFrame) {
                pageFrame.src = "/dashboard.html";
                pageFrame.style.display = 'block';
            }
        } else {
            alert(`Sắp tới sẽ load giao diện chức năng: ${menuName}`);
        }
    });
});

// Xóa tất cả điểm Drop
const btnClearDrops = document.getElementById('btn-clear-drops');
if (btnClearDrops) {
    btnClearDrops.addEventListener('click', () => {
        droppedMarkers.forEach(marker => {
            scene3D.earth.remove(marker);
            // Giải phóng bộ nhớ (optional nhưng tốt cho Three.js)
            marker.children.forEach(child => {
                if (child.geometry) child.geometry.dispose();
                if (child.material) child.material.dispose();
            });
        });
        droppedMarkers.length = 0; // Xóa mảng
    });
}