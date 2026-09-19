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
    const earthNight = textureLoader.load("/assets/textures/earth_nightmap.jpg");

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

    // Night Lights Layer (custom shader to only show in the dark)
    const nightMaterial = new THREE.ShaderMaterial({
        uniforms: {
            nightTexture: { value: earthNight },
            sunDirection: { value: new THREE.Vector3(5, 3, 5).normalize() }
        },
        vertexShader: `
            varying vec2 vUv;
            varying vec3 vNormal;
            void main() {
                vUv = uv;
                vNormal = normalize((modelMatrix * vec4(normal, 0.0)).xyz);
                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
        `,
        fragmentShader: `
            uniform sampler2D nightTexture;
            uniform vec3 sunDirection;
            varying vec2 vUv;
            varying vec3 vNormal;
            void main() {
                float intensity = dot(vNormal, sunDirection);
                // When intensity < 0, it's dark. Blend smoothly.
                float blend = smoothstep(0.1, -0.1, intensity);
                vec4 nightColor = texture2D(nightTexture, vUv);
                gl_FragColor = vec4(nightColor.rgb * blend, nightColor.a * blend);
            }
        `,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false
    });

    // Tạo một geometry hơi lớn hơn trái đất một chút xíu (2.005 thay vì 2) để tránh lỗi Z-fighting (nhấp nháy)
    const nightGeometry = new THREE.SphereGeometry(2.005, 64, 64);
    const nightMesh = new THREE.Mesh(nightGeometry, nightMaterial);
    earthGroup.add(nightMesh);

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