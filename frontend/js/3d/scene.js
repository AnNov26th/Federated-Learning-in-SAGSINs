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
    // Time-lapse spin: the new 1× matches the previous 5× (6 minutes per turn).
    // The directional light remains scene-level and does not rotate with the Earth.
    const EARTH_ROTATION_RAD_PER_SECOND = (2 * Math.PI) / (6 * 60);
    function animate() {

        requestAnimationFrame(animate);
        const elapsedSeconds = Math.min(clock.getDelta(), 0.1);

        // Keep a slow, visible Earth spin while the camera flies around the fixed globe center.
        const rotationSpeed = Number(earth.userData.rotationSpeedMultiplier) || 1;
        if (!earth.userData.rotationPaused) earth.rotation.y += EARTH_ROTATION_RAD_PER_SECOND * rotationSpeed * elapsedSeconds;
        if (earth.userData.clouds && !earth.userData.rotationPaused) {
            earth.userData.clouds.rotation.y += EARTH_ROTATION_RAD_PER_SECOND * rotationSpeed * elapsedSeconds * 1.08;
        }

        earth.userData.advanceDevices?.(elapsedSeconds);
        earth.userData.advanceRoutes?.(elapsedSeconds);
        earth.userData.advanceTraining?.(elapsedSeconds);

        controls.update();
        earth.userData.advanceAnnotations?.(elapsedSeconds);

        renderer.render(
            scene,
            camera
        );
    }

    animate();


    // Resize
    // Floating controls keep the canvas size stable when a detail panel opens.
    const resizeObserver = new ResizeObserver(() => {

        const width =
            container.clientWidth;

        const height =
            container.clientHeight;

        if (!width || !height) return;

        camera.aspect =
            width / height;

        // Keep the globe in view in a narrow canvas without changing the user's zoom.
        camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(
            Math.tan(THREE.MathUtils.degToRad(45) / 2) / Math.min(camera.aspect, 1)
        ));

        camera.updateProjectionMatrix();

        renderer.setSize(
            width,
            height
        );
    });
    resizeObserver.observe(container);


    return {
        scene,
        camera,
        renderer,
        controls,
        earth
    };
}
