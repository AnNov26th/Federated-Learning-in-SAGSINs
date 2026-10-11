# Global Multi-Layer SAGSIN Scenario Design

## Purpose

Extend the existing global scenario from 50 ground nodes into a visible,
reproducible Space-Air-Ground-Sea (SAGSIN) simulation. Remove the unfinished
2D/3D toggle because the application only renders a Three.js 3D globe. Keep
the existing WGS84 latitude/longitude convention shared by inventory data and
the globe renderer.

## Approved scenario size

The scenario contains 106 nodes:

| Layer | Count | Platform | Altitude |
| --- | ---: | --- | ---: |
| Ground | 50 | Existing representative ground participants | 0 km |
| Sea | 20 | Simulated ships on major maritime corridors | 0 km |
| Air | 12 | Simulated low-altitude UAV relays | 0.3 km |
| Space | 24 | Simulated LEO satellites | 550 km |

The values are a manageable global simulation sample. They are not estimates
of real worldwide asset counts. All new layer positions are marked simulated;
they must not be labeled as live AIS, flight-tracking, or satellite ephemeris
data. Preserve country attribution for the existing ground nodes. Maritime
nodes may have no country code because a waypoint on an international route
does not identify a vessel's flag state.

## Position model

### Sea

Place 20 ship representatives at manually curated WGS84 waypoints over water,
distributed across major corridors in East/Southeast Asia, the Indian Ocean and
Red Sea, the Mediterranean, the Atlantic, and the Pacific. Coordinates are
static simulation waypoints, not observed ship tracks. Store `type=SEA`,
`platform=SHIP`, `alt=0`, a corridor label in `location_name`, and a simulation
coordinate source.

### Air

Place 12 UAV relay representatives at distinct global service-region
coordinates, preferentially near but not exactly coincident with ground hubs.
Use `type=AIR`, `platform=UAV`, and `alt=0.3` km. The altitude is a simulation
height, not an operational authorization; actual UAV limits depend on local
airspace and regulations.

### Space

Generate a deterministic Walker-Delta-style LEO sample of 24 satellites: six
planes, four satellites per plane, 53-degree inclination, 550 km circular
altitude, and phasing factor F=1. Use epoch `2026-10-11T00:00:00Z`. Compute each
satellite's inertial position from the circular-orbit elements, rotate to
Earth-fixed coordinates using Earth rotation at that epoch, and convert to
spherical latitude/longitude. Save the orbital metadata (inclination, plane,
phase, and epoch) so a row can be reproduced and understood. This one-time
epoch produces a snapshot, not a propagation or coverage guarantee.

NASA classifies LEO as orbits at or below 2,000 km; the selected 550 km altitude
falls within that range. The 24-satellite arrangement is a simulation
constellation and is not claimed to provide continuous global service.

## Persistence and rendering

- Keep scenario name `SAGSIN-Global-Ground-50` only if compatibility requires
  it; otherwise rename it to `SAGSIN-Global-Multilayer-106` so dashboard counts
  and scenario identity describe the new dataset. The implementation should
  use `SAGSIN-Global-Multilayer-106`.
- Seed counts must match the rows: `total_nodes=106`, `ground=50`, `sea=20`,
  `air=12`, `space=24`.
- Extend node persistence/API only with fields required to identify platform
  and reproduce satellite placement: `platform`, `orbit_inclination_deg`,
  `orbit_plane`, `orbit_phase_deg`, and `epoch_utc`. These are nullable for
  ground, sea, and air nodes. Existing country and representative-location
  fields remain nullable for non-ground nodes.
- Use IDs with stable layer prefixes (`GND`, `SHIP`, `UAV`, `SAT`) and preserve
  type values (`GROUND`, `SEA`, `AIR`, `SPACE`) consumed by the current renderer.
- Keep the existing `latLngToVector3` convention and altitude exaggeration;
  feed physical altitude in kilometers. Ground markers remain slightly above
  the globe surface. No alternate 2D map is introduced.
- Extend hover details to show platform and satellite orbital metadata where
  present. Layer colors and current Three.js scene controls remain unchanged
  except for removal of the nonfunctional toggle.

## UI change

Remove the `Toggle 2D/3D` button from the action panel and remove its alert
listener from `frontend/js/app.js`. Retain the reset-camera action and 3D globe.

## Database update behavior

Update the existing inventory builder and seed path to produce and load all
106 rows. Apply the scenario through the existing seed workflow, which clears
the current demo topology and related FL records before inserting the new
scenario. Preserve the 50 existing ground rows and metadata as the ground
portion of the new inventory. Add schema migration for the nullable platform
and orbit fields without dropping tables.

## Acceptance criteria

1. The UI contains no 2D/3D toggle and no corresponding event listener or
   placeholder alert; reset camera still works.
2. Inventory and database contain exactly 106 nodes with counts 50/20/12/24
   for ground/sea/air/space and unique IDs.
3. All new nodes have `is_simulated=true`, valid WGS84 coordinates, correct
   type/platform, and their specified altitude.
4. All 24 satellite rows have reproducible orbit metadata and coordinates
   derived from the shared fixed epoch.
5. Existing ground-node country metadata remains intact, and non-ground rows
   do not receive invented country or live-location claims.
6. Database nodes render with their layer colors and globe-coordinate mapping;
   hover shows platform and orbit data when present.
7. The TXT preview and dataset README state the counts, assumptions, epoch,
   limitations, and coordinate convention.

## Sources

- NASA, [SCaN Glossary: Low Earth Orbit](https://www.nasa.gov/reference/scan-glossary/):
  LEO altitude range.
- ESA, [Galileo satellites](https://www.esa.int/Applications/Satellite_navigation/Galileo/Galileo_satellites):
  example of describing a constellation by orbit altitude, inclination, and
  orbital planes. Galileo itself is MEO and is not used as the altitude model
  for this scenario.
- FAA, [Small Unmanned Aircraft Systems Regulations (Part 107)](https://www.faa.gov/newsroom/small-unmanned-aircraft-systems-uas-regulations-part-107):
  an example of why UAV operational altitude is jurisdiction-dependent.
