# Global Multi-Layer SAGSIN Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace the 50-ground-only seed with the approved 106-node global SAGSIN scenario and remove the nonfunctional 2D/3D toggle.

**Architecture:** Keep the existing 50-node ground inventory, add curated static waypoint inputs for ships and UAVs, and derive 24 satellite coordinates from a deterministic Walker-style orbit at the approved epoch. Merge these rows into one database seed, persist platform/orbit metadata, and render them with the existing Three.js coordinate conversion and layer colors.

**Tech Stack:** Python, SQLAlchemy, FastAPI/Pydantic, CSV, vanilla JavaScript, Three.js, MySQL.

**Spec:** `docs/superpowers/specs/2026-10-11-global-multilayer-scenario-design.md`

## Global Constraints

- Scenario counts are ground 50, sea 20, air 12, space 24, total 106.
- UAV simulation altitude is 0.3 km; LEO satellite altitude is 550 km and inclination is 53 degrees.
- Satellite orbit has 6 planes × 4 satellites, Walker phasing F=1, epoch `2026-10-11T00:00:00Z`.
- All newly added positions are simulated and are not live AIS, flight-tracking, or TLE/ephemeris positions.
- Node latitude/longitude remain WGS84 and use the existing `latLngToVector3` axis convention and altitude scaling.
- Preserve the existing ground-node country metadata and use no invented country/flag metadata for sea waypoints.
- Remove the 2D/3D toggle control and listener; keep the 3D globe and reset-camera action.
- Database seeding replaces current demo topology and dependent FL records; do not drop database tables.

## Review Focus

- Satellite coordinates must use the same fixed epoch and convert inertial coordinates to Earth-fixed coordinates before producing WGS84 latitude/longitude.
- Ship waypoints must fall on water and must not be described as observed AIS tracks.
- All rows must have unique IDs and valid layer/platform/altitude combinations.
- Node schema migration must work with the configured MySQL database and preserve existing tables.
- Frontend must not dereference a missing toggle element after removing the button.

---

### Task 1: Produce a merged, reproducible 106-node inventory

**Files:**
- Create: `data/global_ground_nodes/sea_ship_waypoints.csv`
- Create: `data/global_ground_nodes/uav_relay_waypoints.csv`
- Create: `backend/database/build_global_multilayer_inventory.py`
- Create: `data/global_ground_nodes/global_multilayer_nodes_106.csv`
- Modify: `document/Thiết bị.txt`
- Modify: `data/global_ground_nodes/README.md`

**Interfaces:**
- Consumes: `data/global_ground_nodes/global_ground_nodes_50.csv` as the approved ground-layer input.
- Produces: a 106-row combined CSV with the existing node columns plus `platform`, `orbit_inclination_deg`, `orbit_plane`, `orbit_phase_deg`, and `epoch_utc`.

- [ ] Read and retain all 50 ground rows unchanged, including their country and location metadata.
- [ ] Add 20 curated over-water ship waypoints across the maritime corridors specified in the spec; assign `SHIP-*`, `SEA`, 0 km, `platform=SHIP`, simulated source, and corridor label.
- [ ] Add 12 distinct UAV relay waypoints; assign `UAV-*`, `AIR`, 0.3 km, `platform=UAV`, and simulated source.
- [ ] Generate 24 satellite rows using 6 equally spaced RAAN planes, 4 satellites per plane, inclination 53°, altitude 550 km, F=1, and the fixed epoch. Calculate circular-orbit ECI coordinates, rotate by GMST to ECEF, then derive spherical latitude/longitude. Store plane, phase, inclination, and ISO-8601 UTC epoch in each row.
- [ ] Enforce exactly 106 unique IDs, exact per-layer counts, WGS84 coordinate bounds, and the approved platform/type/altitude mapping before writing output.
- [ ] Generate the TXT preview with totals, source limitations, epoch/orbit assumptions, and the existing Three.js coordinate convention; update README with input provenance and rebuild commands.

**Check:** Run the inventory builder and inspect its summary: 106 total, 50 GROUND, 20 SEA, 12 AIR, 24 SPACE, no duplicate IDs, valid coordinates.

### Task 2: Persist platform and orbit metadata and seed the new scenario

**Files:**
- Modify: `backend/models/network.py`
- Modify: `backend/schemas/network.py`
- Modify: `backend/database/seed_db.py`

**Interfaces:**
- Consumes: the combined CSV from Task 1.
- Produces: `/api/nodes` records with platform/orbit metadata, and scenario `SAGSIN-Global-Multilayer-106` with correctly populated layer totals.

- [ ] Add nullable `platform`, `orbit_inclination_deg`, `orbit_plane`, `orbit_phase_deg`, and `epoch_utc` columns to the SQLAlchemy model and Pydantic schemas; store `epoch_utc` as an ISO-8601 UTC string to retain the `Z` timezone marker consistently.
- [ ] Extend the existing migration to add these columns to an existing `nodes` table without dropping tables.
- [ ] Update inventory loading to validate 106 rows and counts by layer rather than requiring ground-only rows; map optional metadata safely for all nodes.
- [ ] Seed scenario counts as total 106, ground 50, sea 20, air 12, space 24; keep node country fields null where they do not apply.
- [ ] Point the seed at `global_multilayer_nodes_106.csv` and rename the scenario to `SAGSIN-Global-Multilayer-106`.

**Check:** Run the configured seed command; query back scenario totals, per-type counts, unique IDs, platform values, simulated flags, and satellite orbit metadata.

### Task 3: Remove the toggle and show multi-layer metadata on the globe

**Files:**
- Modify: `frontend/html/index.html`
- Modify: `frontend/js/app.js`

**Interfaces:**
- Consumes: existing node API response extended by Task 2.
- Produces: a 3D-only simulation UI with layer markers and relevant hover metadata.

- [ ] Remove the `btn-toggle-3d` button from the action panel and remove its alert listener from `app.js`.
- [ ] Keep reset-camera behavior and existing SPACE/AIR/GROUND/SEA marker colors and `latLngToVector3` projection.
- [ ] Extend node tooltip content to show platform and, for satellites, inclination, plane, phase, and epoch when present.
- [ ] Label simulated non-ground locations accurately without implying actual tracked vehicles or satellites.

**Check:** Confirm the toggle ID and placeholder alert are absent; inspect the rendered/API node set and confirm the reset-camera control remains available.

### Task 4: End-to-end scenario reconciliation

**Files:**
- Review: `data/global_ground_nodes/global_multilayer_nodes_106.csv`
- Review: `document/Thiết bị.txt`
- Review: database scenario and `/api/nodes` output

- [ ] Reconcile inventory, DB counts, and dashboard/API counts at 106 total and 50/20/12/24 by layer.
- [ ] Confirm ground country metadata matches the source inventory and new non-ground records are marked simulated.
- [ ] Confirm satellite coordinates are reproducible from stored orbital metadata and epoch and use the same geographic convention as the globe.
- [ ] Run `git diff --check` and review the final changed-file list, preserving unrelated existing workspace modifications.
