import * as THREE from "three";

export const EARTH_RENDER_RADIUS = 2;
export const GROUND_MARKER_OFFSET = 0.01;

/** Convert WGS84 decimal-degree coordinates to the local Three.js globe frame.
 * Longitude 0° faces +X, east longitudes point toward -Z, and north is +Y.
 * Altitude is physically stored in km; non-ground layer heights are exaggerated
 * for visibility, matching the existing SAGSIN visualization convention.
 */
export function latLngToVector3(lat, lng, altKm = 0) {
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
        throw new RangeError("Latitude must be a finite value in [-90, 90]");
    }
    if (!Number.isFinite(lng) || lng < -180 || lng > 180) {
        throw new RangeError("Longitude must be a finite value in [-180, 180]");
    }
    if (!Number.isFinite(altKm)) {
        throw new RangeError("Altitude must be a finite value in km");
    }

    let altitudeUnits = 0;
    if (altKm > 0 && altKm < 50) {
        altitudeUnits = 0.05 + (altKm / 50) * 0.15;
    } else if (altKm >= 50 && altKm <= 2000) {
        altitudeUnits = 0.3 + (altKm / 2000) * 0.3;
    } else if (altKm > 2000 && altKm <= 20000) {
        altitudeUnits = 0.7 + (altKm / 20000) * 0.5;
    } else if (altKm > 20000) {
        altitudeUnits = 1.3 + (altKm / 40000) * 1.5;
    }

    const phi = THREE.MathUtils.degToRad(lat);
    const lambda = THREE.MathUtils.degToRad(lng);
    const radius = EARTH_RENDER_RADIUS + altitudeUnits + GROUND_MARKER_OFFSET;
    return new THREE.Vector3(
        radius * Math.cos(phi) * Math.cos(lambda),
        radius * Math.sin(phi),
        -radius * Math.cos(phi) * Math.sin(lambda),
    );
}
