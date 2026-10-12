import * as THREE from "three";

import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { createEarth } from "./earth.js";


export function createScene(container) {

    // Scene
    const scene = new THREE.Scene();

    // Background
    const textureLoader = new THREE.TextureLoader();
    scene.background = textureLoader.load("/assets/textures/stars_milky_way.jpg");


    // Camera
    const camera = new THREE.PerspectiveCamera(
        45,
        container.clientWidth / container.clientHeight,
        0.1,
        1000
    );

    camera.position.set(0, 0, 6);


    // Renderer
    const renderer = new THREE.WebGLRenderer({
        antialias: true
    });

    renderer.setSize(
        container.clientWidth,
        container.clientHeight
    );

    renderer.setPixelRatio(
        Math.min(window.devicePixelRatio, 2)
    );

    container.appendChild(renderer.domElement);


    // Controls
    const controls = new OrbitControls(
        camera,
        renderer.domElement
    );

    controls.enableDamping = true;


    // Ambient light (reduced to make the dark side actually dark)
    const ambientLight = new THREE.AmbientLight(
        0xffffff,
        0.02 // Tối hơn một chút
    );

    scene.add(ambientLight);


    // Sun light
    const directionalLight =
        new THREE.DirectionalLight(
            0xffffff,
            1.5 // Ánh sáng mặt trời yếu đi một chút để tổng thể tối hơn
        );

    directionalLight.position.set(
        5,
        3,
        5
    );

    scene.add(directionalLight);


    // Earth
    const earth = createEarth();

    scene.add(earth);


    // Animation
    const clock = new THREE.Clock();
    // Time-lapse spin for visibility (about 30 minutes per turn).
    // The directional light remains scene-level and does not rotate with the Earth.
    const EARTH_ROTATION_RAD_PER_SECOND = (2 * Math.PI) / (30 * 60);
    function animate() {

        requestAnimationFrame(animate);
        const elapsedSeconds = Math.min(clock.getDelta(), 0.1);

        // Keep a slow, visible Earth spin while the camera flies around the fixed globe center.
        if (!earth.userData.rotationPaused) earth.rotation.y += EARTH_ROTATION_RAD_PER_SECOND * elapsedSeconds;
        if (earth.userData.clouds) {
            earth.userData.clouds.rotation.y += EARTH_ROTATION_RAD_PER_SECOND * elapsedSeconds * 1.08;
        }

        earth.userData.advanceDevices?.(elapsedSeconds);

        controls.update();

        renderer.render(
            scene,
            camera
        );
    }

    animate();


    // Resize
    window.addEventListener("resize", () => {

        const width =
            container.clientWidth;

        const height =
            container.clientHeight;

        camera.aspect =
            width / height;

        camera.updateProjectionMatrix();

        renderer.setSize(
            width,
            height
        );
    });


    return {
        scene,
        camera,
        renderer,
        controls,
        earth
    };
}
