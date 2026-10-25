"""Deterministic polar shell and geometric coverage checks (no database writes).

Circular two-body orbits, spherical Earth, no drag/J2/terrain/link budget.
The analytical bound applies continuously; the grid check is supplementary.
"""
import argparse
import csv
import json
import math
from pathlib import Path

from backend.database.build_global_multilayer_inventory import (
    EPOCH, EPOCH_TEXT, FIELDNAMES, base_row, gmst_degrees,
)

R = 6371.0
MU = 398600.4418
ALTITUDE_KM = 1200.0
PLANES = 6
SLOTS = 12
MIN_ELEVATION_DEG = 10.0
MANIFEST = Path(__file__).resolve().parents[2] / "data/input/global_ground_nodes/polar_coverage_satellites_v1.csv"
FIELDS = [*FIELDNAMES, "orbit_raan_deg"]


def position(raan_deg, phase_deg, elapsed_s=0.):
    """Earth-fixed position, phase measured from the ascending equatorial node."""
    phase = math.radians(phase_deg) + math.sqrt(MU / (R+ALTITUDE_KM)**3) * elapsed_s
    # Polar orbit: inertial x/y are the ascending-node direction times cos(phase).
    longitude = math.radians(raan_deg - gmst_degrees(EPOCH)) - 2*math.pi*elapsed_s/86164.0905
    x, y, z = math.cos(longitude)*math.cos(phase), math.sin(longitude)*math.cos(phase), math.sin(phase)
    return {"lat": math.degrees(math.asin(max(-1., min(1., z)))),
            "lng": (math.degrees(math.atan2(y, x))+180) % 360-180, "alt": ALTITUDE_KM}


def build_satellites():
    rows = []
    for plane in range(PLANES):
        raan = plane*180/PLANES  # A polar plane already includes both hemispheres.
        for slot in range(SLOTS):
            phase = slot*360/SLOTS + (plane % 2)*180/SLOTS
            p = position(raan, phase)
            rows.append(base_row(
                f"SAT-POLAR-{plane*SLOTS+slot+1:03d}", "SPACE", p["lat"], p["lng"],
                ALTITUDE_KM, 100., 25., f"Polar coverage plane {plane+1}, slot {slot+1}",
                "SIMULATED_POLAR_COVERAGE_V1", "POLAR_COVERAGE_SATELLITE",
                orbit_inclination_deg="90.0", orbit_plane=str(plane+1),
                orbit_phase_deg=f"{phase:.6f}", orbit_raan_deg=f"{raan:.6f}", epoch_utc=EPOCH_TEXT,
            ))
    return rows


def analytical_coverage():
    # Choose a plane at perpendicular angular distance <= half the plane spacing.
    # On that plane a satellite is <= half the along-track spacing away. These
    # form a right spherical triangle: cos(separation) = cos(cross)*cos(along).
    separation = math.acos(math.cos(math.pi/(2*PLANES))*math.cos(math.pi/SLOTS))
    min_elevation = math.atan2(math.cos(separation)-R/(R+ALTITUDE_KM), math.sin(separation))
    footprint = math.acos(R/(R+ALTITUDE_KM)*math.cos(math.radians(MIN_ELEVATION_DEG))) - math.radians(MIN_ELEVATION_DEG)
    return {"satellites_added": PLANES*SLOTS, "planes": PLANES, "satellites_per_plane": SLOTS,
            "altitude_km": ALTITUDE_KM, "inclination_deg": 90.,
            "required_min_elevation_deg": MIN_ELEVATION_DEG,
            "maximum_nearest_satellite_angle_bound_deg": math.degrees(separation),
            "minimum_best_elevation_bound_deg": math.degrees(min_elevation),
            "footprint_angle_at_required_elevation_deg": math.degrees(footprint),
            "continuous_geometric_coverage": min_elevation >= math.radians(MIN_ELEVATION_DEG),
            "assumptions": "All 72 satellites ACTIVE; ideal circular polar orbits, spherical Earth. Coverage is geometric, not a capacity/link-budget or end-to-end routing guarantee."}


def sample_coverage(grid_deg=5, step_s=300, duration_s=86400):
    import numpy as np
    lat, lng = np.meshgrid(np.arange(-90, 90+grid_deg/2, grid_deg), np.arange(-180, 180, grid_deg), indexing="ij")
    lat, lng = np.radians(lat.ravel()), np.radians(lng.ravel())
    points = np.column_stack((np.cos(lat)*np.cos(lng), np.cos(lat)*np.sin(lng), np.sin(lat)))
    satellites = build_satellites()
    worst, gaps, samples = 90., 0, 0
    for t in range(0, duration_s+1, step_s):
        positions = [position(float(row['orbit_raan_deg']), float(row['orbit_phase_deg']), t) for row in satellites]
        lat_s = np.radians([p['lat'] for p in positions]); lng_s = np.radians([p['lng'] for p in positions])
        vectors = np.column_stack((np.cos(lat_s)*np.cos(lng_s), np.cos(lat_s)*np.sin(lng_s), np.sin(lat_s)))
        cosine = np.clip((points @ vectors.T).max(axis=1), -1., 1.)
        elevations = np.degrees(np.arctan2(cosine-R/(R+ALTITUDE_KM), np.sqrt(np.maximum(0., 1-cosine*cosine))))
        worst = min(worst, float(elevations.min()))
        gaps += int((elevations < MIN_ELEVATION_DEG).sum()); samples += len(points)
    return {"grid_deg": grid_deg, "step_s": step_s, "duration_s": duration_s,
            "point_time_samples": samples, "uncovered_samples": gaps,
            "minimum_best_elevation_deg": worst}


def load_satellites():
    with MANIFEST.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if rows != build_satellites():
        raise ValueError("Polar coverage v1 inventory changed; regenerate it or create a new migration version.")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write the committed satellite inventory")
    parser.add_argument("--check", action="store_true", help="Validate the inventory and sample 24 hours")
    args = parser.parse_args()
    report = {"analytical": analytical_coverage()}
    if args.write:
        with MANIFEST.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(build_satellites())
    if args.check:
        load_satellites()
        report["sampled"] = sample_coverage()
        if report["sampled"]["uncovered_samples"]:
            raise RuntimeError("Coverage check failed")
    if not report["analytical"]["continuous_geometric_coverage"]:
        raise RuntimeError("Analytical coverage bound failed")
    print(json.dumps(report, indent=2))
