"""Build the approved deterministic 106-node global SAGSIN inventory."""

import csv
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "global_ground_nodes"
GROUND_INPUT = DATA / "global_ground_nodes_50.csv"
OUTPUT = DATA / "global_multilayer_nodes_106.csv"
EPOCH_TEXT = "2026-10-11T00:00:00Z"
EPOCH = datetime(2026, 10, 11, tzinfo=timezone.utc)
EARTH_RADIUS_KM = 6371.0
SATELLITE_ALTITUDE_KM = 550.0
SATELLITE_INCLINATION_DEG = 53.0
ORBITAL_PLANES = 6
SATELLITES_PER_PLANE = 4
WALKER_PHASE_FACTOR = 1

FIELDNAMES = [
    "id", "type", "lat", "lng", "alt_km", "bandwidth_mbps", "latency_ms",
    "battery_percent", "status", "country_code", "country_name", "continent",
    "land_area_km2", "location_name", "coordinate_source", "is_simulated",
    "population_2024", "idi_2025", "area_weight", "imputed_indicators",
    "platform", "orbit_inclination_deg", "orbit_plane", "orbit_phase_deg", "epoch_utc",
]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def julian_date(timestamp):
    year = timestamp.year
    month = timestamp.month
    day = timestamp.day
    if month <= 2:
        year -= 1
        month += 12
    century = math.floor(year / 100)
    correction = 2 - century + math.floor(century / 4)
    day_fraction = (
        timestamp.hour + timestamp.minute / 60
        + (timestamp.second + timestamp.microsecond / 1_000_000) / 3600
    ) / 24
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day + day_fraction + correction - 1524.5
    )


def gmst_degrees(timestamp):
    jd = julian_date(timestamp)
    centuries = (jd - 2451545.0) / 36525.0
    angle = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * centuries**2
        - centuries**3 / 38710000.0
    )
    return angle % 360.0


def satellite_position(plane, slot):
    """Return a spherical Earth-fixed lat/lng for a circular Walker-style orbit."""
    raan = math.radians(plane * 360.0 / ORBITAL_PLANES)
    inclination = math.radians(SATELLITE_INCLINATION_DEG)
    phase_deg = (
        slot * 360.0 / SATELLITES_PER_PLANE
        + WALKER_PHASE_FACTOR * plane * 360.0 / (ORBITAL_PLANES * SATELLITES_PER_PLANE)
    ) % 360.0
    argument_latitude = math.radians(phase_deg)
    radius = EARTH_RADIUS_KM + SATELLITE_ALTITUDE_KM

    # Perifocal circular-orbit position rotated into Earth-centered inertial axes.
    x_eci = radius * (
        math.cos(raan) * math.cos(argument_latitude)
        - math.sin(raan) * math.sin(argument_latitude) * math.cos(inclination)
    )
    y_eci = radius * (
        math.sin(raan) * math.cos(argument_latitude)
        + math.cos(raan) * math.sin(argument_latitude) * math.cos(inclination)
    )
    z_eci = radius * math.sin(argument_latitude) * math.sin(inclination)

    # Convert inertial coordinates to Earth-fixed coordinates at the selected epoch.
    earth_rotation = math.radians(gmst_degrees(EPOCH))
    x_ecef = math.cos(earth_rotation) * x_eci + math.sin(earth_rotation) * y_eci
    y_ecef = -math.sin(earth_rotation) * x_eci + math.cos(earth_rotation) * y_eci
    lat = math.degrees(math.asin(z_eci / radius))
    lng = (math.degrees(math.atan2(y_ecef, x_ecef)) + 180.0) % 360.0 - 180.0
    return lat, lng, phase_deg


def base_row(node_id, node_type, lat, lng, alt, bandwidth, latency, location,
             source, platform, **metadata):
    row = {name: "" for name in FIELDNAMES}
    row.update({
        "id": node_id,
        "type": node_type,
        "lat": f"{lat:.6f}",
        "lng": f"{lng:.6f}",
        "alt_km": f"{alt:.3f}",
        "bandwidth_mbps": f"{bandwidth:.1f}",
        "latency_ms": f"{latency:.1f}",
        "battery_percent": "100.0",
        "status": "ACTIVE",
        "location_name": location,
        "coordinate_source": source,
        "is_simulated": "true",
        "platform": platform,
    })
    row.update(metadata)
    return row


def build_inventory():
    if not GROUND_INPUT.exists():
        raise FileNotFoundError(f"Missing approved ground inventory: {GROUND_INPUT}")

    ground_rows = read_csv(GROUND_INPUT)
    if len(ground_rows) != 50 or any(row["type"] != "GROUND" for row in ground_rows):
        raise ValueError("Ground input must contain exactly 50 GROUND rows")
    rows = []
    for ground in ground_rows:
        row = {name: ground.get(name, "") for name in FIELDNAMES}
        row["platform"] = "GROUND_NODE"
        row["orbit_inclination_deg"] = ""
        row["orbit_plane"] = ""
        row["orbit_phase_deg"] = ""
        row["epoch_utc"] = ""
        rows.append(row)

    sea_waypoints = read_csv(DATA / "sea_ship_waypoints.csv")
    if len(sea_waypoints) != 20:
        raise ValueError(f"Expected 20 ship waypoints, found {len(sea_waypoints)}")
    for point in sea_waypoints:
        rows.append(base_row(
            point["node_id"], "SEA", float(point["latitude"]),
            float(point["longitude"]), 0.0, 25.0, 80.0,
            f"{point['location_name']} ({point['corridor']})",
            "SIMULATED_MARITIME_CORRIDOR_WAYPOINT", "SHIP",
        ))

    uav_waypoints = read_csv(DATA / "uav_relay_waypoints.csv")
    if len(uav_waypoints) != 12:
        raise ValueError(f"Expected 12 UAV waypoints, found {len(uav_waypoints)}")
    for point in uav_waypoints:
        rows.append(base_row(
            point["node_id"], "AIR", float(point["latitude"]),
            float(point["longitude"]), 0.3, 50.0, 30.0,
            point["location_name"], "SIMULATED_UAV_RELAY_WAYPOINT", "UAV",
        ))

    satellite_number = 0
    for plane in range(ORBITAL_PLANES):
        for slot in range(SATELLITES_PER_PLANE):
            satellite_number += 1
            lat, lng, phase = satellite_position(plane, slot)
            rows.append(base_row(
                f"SAT-{satellite_number:03d}", "SPACE", lat, lng,
                SATELLITE_ALTITUDE_KM, 100.0, 25.0,
                f"LEO plane {plane + 1}, satellite {slot + 1}",
                "SIMULATED_WALKER_LEO_EPOCH", "LEO_SATELLITE",
                orbit_inclination_deg=f"{SATELLITE_INCLINATION_DEG:.1f}",
                orbit_plane=plane + 1,
                orbit_phase_deg=f"{phase:.6f}",
                epoch_utc=EPOCH_TEXT,
            ))

    ids = [row["id"] for row in rows]
    if len(rows) != 106 or len(ids) != len(set(ids)):
        raise ValueError(f"Expected 106 rows with unique IDs, got {len(rows)} rows")
    counts = Counter(row["type"] for row in rows)
    expected = {"GROUND": 50, "SEA": 20, "AIR": 12, "SPACE": 24}
    if dict(counts) != expected:
        raise ValueError(f"Unexpected layer counts: {dict(counts)}")
    for row in rows:
        lat, lng = float(row["lat"]), float(row["lng"])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError(f"Out-of-range WGS84 coordinate for {row['id']}")
        if row["type"] != "GROUND" and row["is_simulated"].lower() != "true":
            raise ValueError(f"Non-ground node {row['id']} must be marked simulated")

    with OUTPUT.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    document = ROOT / "document" / "Thiết bị.txt"
    with document.open("w", encoding="utf-8", newline="\n") as target:
        target.write(
            "SAGSIN GLOBAL MULTI-LAYER NODE INVENTORY (106 nodes)\n"
            "Counts: GROUND=50, SEA=20, AIR=12, SPACE=24.\n"
            "Ground nodes preserve country metadata from global_ground_nodes_50.csv.\n"
            "Ships are simulated static waypoints over major maritime corridors; they are not AIS tracks.\n"
            "UAV relays are simulated at 0.3 km; actual legal operating height depends on jurisdiction.\n"
            "Satellites form a simulated 24-satellite, 6-plane x 4 Walker-style LEO snapshot.\n"
            f"Orbit: circular, altitude={SATELLITE_ALTITUDE_KM:.0f} km, inclination="
            f"{SATELLITE_INCLINATION_DEG:.0f} deg, phasing F={WALKER_PHASE_FACTOR}, epoch={EPOCH_TEXT}.\n"
            "Satellite positions are epoch-derived, Earth-fixed WGS84 coordinates; not live ephemeris.\n"
            "All new nodes are marked simulated; bandwidth/latency defaults (Mbps/ms): "
            "ground=100/10, ship=25/80, UAV=50/30, satellite=100/25.\n"
            "Three.js uses x=r*cos(lat)*cos(lng), y=r*sin(lat), z=-r*cos(lat)*sin(lng);\n"
            "ground visual radius=2.01 and altitude rendering is exaggerated for visibility.\n\n"
            "id | type | platform | location | latitude | longitude | altitude_km | "
            "country_code | orbit_plane | orbit_phase_deg | epoch_utc\n"
        )
        for row in rows:
            target.write(
                f"{row['id']} | {row['type']} | {row['platform']} | {row['location_name']} | "
                f"{row['lat']} | {row['lng']} | {row['alt_km']} | {row['country_code']} | "
                f"{row['orbit_plane']} | {row['orbit_phase_deg']} | {row['epoch_utc']}\n"
            )

    print(f"nodes={len(rows)} ids={len(ids)} unique_ids={len(set(ids))}")
    print("layer_counts=" + ", ".join(f"{key}:{counts[key]}" for key in expected))
    print(f"satellite_epoch={EPOCH_TEXT} gmst_deg={gmst_degrees(EPOCH):.6f}")


if __name__ == "__main__":
    build_inventory()
