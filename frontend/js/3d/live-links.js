import * as THREE from 'three';

const SEGMENTS = 48;

/** Keep a curved link attached to two live, globe-local positions.
 * Reuse its geometry and dashed-distance buffers across animation frames.
 */
export function createLiveArc({ from, to, color, dashed = false, opacity = .62 }) {
    const geometry = new THREE.BufferGeometry();
    const position = new THREE.Float32BufferAttribute(new Float32Array((SEGMENTS + 1) * 3), 3);
    position.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('position', position);
    const distance = dashed ? new THREE.Float32BufferAttribute(new Float32Array(SEGMENTS + 1), 1) : null;
    if (distance) { distance.setUsage(THREE.DynamicDrawUsage); geometry.setAttribute('lineDistance', distance); }
    const options = { color, transparent:true, opacity, depthWrite:false };
    const material = dashed ? new THREE.LineDashedMaterial({ ...options, dashSize:.035, gapSize:.025 })
        : new THREE.LineBasicMaterial(options);
    const line = new THREE.Line(geometry, material);
    line.frustumCulled = false;
    const previousFrom = new THREE.Vector3(Infinity,0,0), previousTo = previousFrom.clone();
    const a = new THREE.Vector3(), b = new THREE.Vector3(), point = new THREE.Vector3(), last = new THREE.Vector3();
    const rotation = new THREE.Quaternion(), partial = new THREE.Quaternion();

    function update() {
        const first = from(), second = to();
        line.visible = Boolean(first && second);
        if (!line.visible) return;
        if (first.equals(previousFrom) && second.equals(previousTo)) return;
        previousFrom.copy(first); previousTo.copy(second);
        const r1 = first.length(), r2 = second.length();
        a.copy(first).normalize(); b.copy(second).normalize();
        rotation.setFromUnitVectors(a,b);
        let accumulated = 0;
        for (let index = 0; index <= SEGMENTS; index++) {
            const t = index / SEGMENTS;
            // Exact endpoints meet the marker centres, without an extra lift.
            if (index === 0) point.copy(first);
            else if (index === SEGMENTS) point.copy(second);
            else point.copy(a).applyQuaternion(partial.identity().slerp(rotation,t))
                .multiplyScalar(THREE.MathUtils.lerp(r1,r2,t) + Math.sin(Math.PI*t)*.06);
            position.setXYZ(index,point.x,point.y,point.z);
            if (distance) {
                if (index) accumulated += point.distanceTo(last);
                distance.setX(index,accumulated); last.copy(point);
            }
        }
        position.needsUpdate = true;
        if (distance) distance.needsUpdate = true;
    }

    function sample(fraction, target) {
        const scaled = THREE.MathUtils.clamp(fraction,0,1)*SEGMENTS;
        const index = Math.min(SEGMENTS-1,Math.floor(scaled)), t = scaled-index;
        return target.set(
            THREE.MathUtils.lerp(position.getX(index),position.getX(index+1),t),
            THREE.MathUtils.lerp(position.getY(index),position.getY(index+1),t),
            THREE.MathUtils.lerp(position.getZ(index),position.getZ(index+1),t)
        );
    }
    update();
    return { line, update, sample };
}

export function sampleLivePath(segments, fraction, target) {
    if (!segments.length || segments.some(segment => !segment.line.visible)) return false;
    const scaled = THREE.MathUtils.clamp(fraction,0,.999999)*segments.length;
    segments[Math.floor(scaled)].sample(scaled%1,target);
    return true;
}
