# Global multi-layer SAGSIN scenario

`global_multilayer_nodes_106.csv` is the deterministic seed inventory for
scenario `SAGSIN-Global-Multilayer-106`. It contains 50 ground nodes, 20 sea
nodes, 12 air nodes and 24 space nodes. The non-ground counts and positions are
simulation samples, not estimates of real worldwide assets.

## Layer assumptions

- **Ground (50):** retained from `global_ground_nodes_50.csv`, preserving each
  node's country metadata and representative city coordinates.
- **Sea (20):** `sea_ship_waypoints.csv` places simulated ship nodes over major
  maritime corridors in East/Southeast Asia, the Indian Ocean and Red Sea, the
  Mediterranean, the Atlantic and the Pacific. These are static WGS84
  waypoints, not observed AIS positions. Country/flag metadata is intentionally
  left blank rather than inferred from an ocean coordinate.
- **Air (12):** `uav_relay_waypoints.csv` places simulated relay UAVs around
  global service regions, at 0.3 km altitude. This is a visualization/simulation
  height, not a general operating authorization; aviation rules vary by
  jurisdiction. The FAA, for example, generally limits small UAS under Part
  107 to 400 feet AGL unless an exception applies.
- **Space (24):** 24 simulated satellites in a circular 550 km LEO sample, with
  53-degree inclination, six equally spaced orbital planes, four satellites
  per plane and Walker-style phasing factor F=1. Coordinates are calculated at
  `2026-10-11T00:00:00Z` and converted from inertial to Earth-fixed coordinates
  using GMST before deriving spherical latitude/longitude. This is one fixed
  snapshot, not live TLE/ephemeris or a propagation/coverage guarantee. NASA
  defines LEO as at or below 2,000 km.

All newly added rows are marked `is_simulated=true`. Ground uses the existing
scenario defaults (100 Mbps and 10 ms); added ships use 25 Mbps/80 ms, UAVs use
50 Mbps/30 ms, and satellites use 100 Mbps/25 ms. These bandwidth and latency
values are illustrative scenario parameters, not measurements.

## Ground data sources and attribution

- `country_area.csv` is a snapshot from [iliyaj/country-data](https://github.com/iliyaj/country-data),
  based on World Bank land-area values. World Bank defines land area in square
  kilometers excluding inland water: [AG.LND.TOTL.K2](https://data.worldbank.org/indicator/AG.LND.TOTL.K2).
- `geonames_country_info.csv` supplies continent codes and fallback area where
  the World Bank area snapshot has no entry. GeoNames data is CC BY 4.0:
  [countryInfo.txt](https://download.geonames.org/export/dump/countryInfo.txt).
- Country names, representative capital coordinates, population and GDP
  snapshots come from [iliyaj/country-data](https://github.com/iliyaj/country-data).
  Population and GDP are 2024 snapshots; GDP per capita is nominal GDP divided
  by population, not PPP-adjusted.
- `itu_idi_2025_scores.csv` captures the 2025 score table shown by
  [World Population Review](https://worldpopulationreview.com/country-rankings/ict-development-index-by-country),
  with [ITU](https://www.itu.int/itu-d/reports/statistics/idi2025/) as index
  publisher. Missing population/GDP values use the candidate-set median;
  missing ITU scores use 78 and are marked in the ground inventory.
- Capital and secondary-city locations are representative WGS84 proxies, not
  verified towers, cell sites, servers, vessels or devices.

## Coordinates and rebuild

Coordinates use WGS84 latitude/longitude. The Three.js `SphereGeometry` radius
is 2, with `x=r*cos(lat)*cos(lng)`, `y=r*sin(lat)`, `z=-r*cos(lat)*sin(lng)`.
The existing renderer exaggerates positive altitudes for visibility; database
altitudes remain physical kilometers.

Build the combined CSV and human-readable preview with:

```powershell
python backend\database\build_global_multilayer_inventory.py
```

Apply it to the configured database with:

```powershell
python -m backend.database.seed_db
```

The seed replaces the current demo nodes, links, participants, scenarios and
FL demo records; it does not drop database tables. Configure `DATABASE_URL` or
use the default local MySQL URL in `backend/database/database.py`.

## References

- NASA, [SCaN Glossary: Low Earth Orbit](https://www.nasa.gov/reference/scan-glossary/).
- ESA, [Galileo satellites](https://www.esa.int/Applications/Satellite_navigation/Galileo/Galileo_satellites),
  an example of specifying constellations using altitude, inclination and
  orbital planes (Galileo itself is MEO, unlike this LEO scenario).
- FAA, [Small Unmanned Aircraft Systems Regulations (Part 107)](https://www.faa.gov/newsroom/small-unmanned-aircraft-systems-uas-regulations-part-107).
