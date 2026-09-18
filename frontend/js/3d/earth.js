import * as THREE from "three";


export function createEarth() {

    const earthGroup = new THREE.Group();

    // 1. Earth Sphere
    const geometry = new THREE.SphereGeometry(2, 64, 64);

    const textureLoader = new THREE.TextureLoader();
    
    // Load textures
    const earthTexture = textureLoader.load("/assets/textures/earth_daymap.jpg");
    const earthNormal = textureLoader.load("/assets/textures/earth_normal_map.jpg");
    const earthSpecular = textureLoader.load("/assets/textures/earth_specular_map.jpg");

    // Use Phong material for better specular map support
    const material = new THREE.MeshPhongMaterial({
        map: earthTexture,
        normalMap: earthNormal,
        specularMap: earthSpecular,
        specular: new THREE.Color(0x333333),
        shininess: 15
    });

    const earth = new THREE.Mesh(geometry, material);
    earthGroup.add(earth);

    // 2. Cloud Layer
    const cloudGeometry = new THREE.SphereGeometry(2.03, 64, 64);
    const cloudTexture = textureLoader.load("/assets/textures/earth_clouds.jpg");
    
    const cloudMaterial = new THREE.MeshPhongMaterial({
        map: cloudTexture,
        transparent: true,
        opacity: 0.6,
        blending: THREE.AdditiveBlending, // Black becomes transparent
        depthWrite: false
    });

    const clouds = new THREE.Mesh(cloudGeometry, cloudMaterial);
    earthGroup.add(clouds);

    // Provide a way to animate clouds slightly faster than earth later
    earthGroup.userData = { clouds: clouds, earth: earth };

    return earthGroup;
}