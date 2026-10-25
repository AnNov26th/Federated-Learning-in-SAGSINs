"""Build the deterministic, land-area-weighted 50-node ground inventory."""

import csv
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "input" / "global_ground_nodes"
TARGET_NODES = 50
MAX_NODES_PER_COUNTRY = 2
CONTINENT_NAMES = {
    "AF": "Africa",
    "AS": "Asia",
    "EU": "Europe",
    "NA": "North America",
    "SA": "South America",
    "OC": "Oceania",
}


def read_rows(filename):
    with (DATA / filename).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        return list(reader)


def normalized(value):
    return " ".join(value.casefold().replace("&", "and").replace("’", "'").split())


def largest_remainder(weights, slots):
    total = sum(weights.values())
    if not weights or total <= 0:
        raise ValueError("Cannot allocate nodes without positive area weights")
    quotas = {key: slots * value / total for key, value in weights.items()}
    counts = {key: math.floor(quota) for key, quota in quotas.items()}
    remainder = slots - sum(counts.values())
    ranking = sorted(quotas, key=lambda key: (-(quotas[key] - counts[key]), key))
    for key in ranking[:remainder]:
        counts[key] += 1
    return counts


def build_inventory():
    names = {row["alpha_3_code"].strip(): row["common_english_name"].strip()
             for row in read_rows("country_names.csv")}
    capitals = {row["alpha_3_code"].strip(): row
                for row in read_rows("country_capitals.csv")}
    population = {row["alpha_3_code"].strip(): int(row["population"])
                  for row in read_rows("country_population_2024.csv")
                  if row.get("population", "").isdigit()}
    gdp = {row["alpha_3_code"].strip(): int(row["gdp_usd"])
           for row in read_rows("country_gdp_2024.csv")
           if row.get("gdp_usd", "").isdigit()}
    land_area = {row["alpha_3_code"].strip(): float(row["land"])
                 for row in read_rows("country_area.csv")
                 if row.get("land", "").strip()}
    geography = {row["iso3"].strip(): row
                 for row in read_rows("geonames_country_info.csv")}
    idi = {normalized(row["country"]): float(row["idi_score_2025"])
           for row in read_rows("itu_idi_2025_scores.csv")}
    secondary_cities = {}
    for row in read_rows("secondary_city_coordinates.csv"):
        secondary_cities.setdefault(row["country_code"], []).append({
            "name": row["location_name"],
            "lat": float(row["latitude"]),
            "lng": float(row["longitude"]),
        })

    aliases = {
        "brunei darussalam": "brunei", "cabo verde": "cape verde",
        "cote d'ivoire": "ivory coast", "côte d'ivoire": "ivory coast",
        "congo, dem. rep.": "dr congo", "congo, rep.": "republic of the congo",
        "iran, islamic rep.": "iran", "korea, rep.": "south korea",
        "korea, dem. people's rep.": "north korea", "kyrgyz republic": "kyrgyzstan",
        "lao pdr": "laos", "micronesia, fed. sts.": "micronesia",
        "russian federation": "russia", "syrian arab republic": "syria",
        "turkiye": "turkey", "viet nam": "vietnam",
        "egypt, arab rep.": "egypt", "gambia, the": "gambia",
        "moldova": "moldova", "venezuela, rb": "venezuela",
        "yemen, rep.": "yemen", "tanzania": "tanzania",
    }
    idi_by_code = {}
    for code, country_name in names.items():
        key = normalized(country_name)
        idi_key = aliases.get(key, key)
        if idi_key in idi:
            idi_by_code[code] = idi[idi_key]

    countries = []
    area_fallbacks = []
    for code, capital in capitals.items():
        if code not in names or code not in geography:
            continue
        geo = geography[code]
        area_from_world_bank = land_area.get(code)
        area = area_from_world_bank or float(geo.get("area_km2") or 0)
        if area <= 0 or geo["continent"] not in CONTINENT_NAMES:
            continue
        pop = population.get(code)
        gdp_total = gdp.get(code)
        gdp_pc = gdp_total / pop if pop and gdp_total else None
        continent = geo["continent"]
        # Most of Russia's land area is in Asia; place its scenario quota there.
        if code == "RUS":
            continent = "AS"
        countries.append({
            "code": code,
            "country": names[code],
            "capital": capital["capital_city"].strip(),
            "lat": float(capital["latitude"]),
            "lng": float(capital["longitude"]),
            "population": pop,
            "gdp_pc": gdp_pc,
            "idi": idi_by_code.get(code),
            "land_area_km2": area,
            "area_source": "WORLD_BANK_LAND_AREA" if area_from_world_bank else "GEONAMES_FALLBACK",
            "continent_code": continent,
        })
        if not area_from_world_bank:
            area_fallbacks.append(code)

    if len(countries) < TARGET_NODES:
        raise ValueError(f"Country/geography coverage unexpectedly low: {len(countries)}")

    available_pop = [row["population"] for row in countries if row["population"]]
    available_gdp_pc = [row["gdp_pc"] for row in countries if row["gdp_pc"]]
    population_fallback = sorted(available_pop)[len(available_pop) // 2]
    gdp_fallback = sorted(available_gdp_pc)[len(available_gdp_pc) // 2]
    for row in countries:
        row["population_imputed"] = row["population"] is None
        row["gdp_imputed"] = row["gdp_pc"] is None
        row["population"] = row["population"] or population_fallback
        row["gdp_pc"] = row["gdp_pc"] or gdp_fallback
        row["idi_imputed"] = row["idi"] is None
        row["idi"] = row["idi"] if row["idi"] is not None else 78.0

    # Economic/technology development only gently adjusts country area weights.
    gdp_values = sorted(row["gdp_pc"] for row in countries)
    idi_values = sorted(row["idi"] for row in countries)
    gdp_pct = {
        row["code"]: next(i for i, value in enumerate(gdp_values) if value >= row["gdp_pc"])
        / max(len(gdp_values) - 1, 1)
        for row in countries
    }
    idi_pct = {
        row["code"]: next(i for i, value in enumerate(idi_values) if value >= row["idi"])
        / max(len(idi_values) - 1, 1)
        for row in countries
    }
    for row in countries:
        development = 0.5 * gdp_pct[row["code"]] + 0.5 * idi_pct[row["code"]]
        row["area_weight"] = row["land_area_km2"] * (0.75 + 0.5 * development)

    continent_area = Counter()
    countries_by_continent = {}
    for row in countries:
        continent_area[row["continent_code"]] += row["land_area_km2"]
        countries_by_continent.setdefault(row["continent_code"], []).append(row)
    # Continental node quotas follow land-area share (Antarctica excluded).
    continent_quota = largest_remainder(continent_area, TARGET_NODES)
    for region, slots in continent_quota.items():
        regional = sorted(countries_by_continent[region],
                          key=lambda row: (-row["area_weight"], row["code"]))
        # At least one node per chosen country; additional nodes favor larger
        # countries. This yields a non-uniform allocation with max two per country.
        base_countries = slots if slots <= 2 else math.ceil(slots / MAX_NODES_PER_COUNTRY)
        chosen = regional[:base_countries]
        counts = {row["code"]: 1 for row in chosen}
        extra_slots = slots - base_countries
        # Allocate at most one additional node per country so each has a
        # distinct representative city and the two-node cap is respected.
        extra_rank = sorted(chosen, key=lambda row: (-row["area_weight"], row["code"]))
        for row in extra_rank[:extra_slots]:
            counts[row["code"]] += 1
        for row in countries_by_continent[region]:
            row["node_count"] = counts.get(row["code"], 0)

    selected_countries = [row for row in countries if row["node_count"]]
    if any(row["node_count"] > MAX_NODES_PER_COUNTRY for row in selected_countries):
        raise ValueError("Country allocation exceeded the city-location cap")

    output_rows = []
    for country in sorted(selected_countries, key=lambda row: (row["continent_code"], row["code"])):
        for index in range(1, country["node_count"] + 1):
            if index == 1:
                location = country["capital"]
                lat, lng = country["lat"], country["lng"]
                coordinate_source = "REPRESENTATIVE_CAPITAL"
            else:
                choices = secondary_cities.get(country["code"], [])
                if len(choices) < index - 1:
                    raise ValueError(f"No secondary city coordinate for {country['code']} node {index}")
                location_row = choices[index - 2]
                location = location_row["name"]
                lat, lng = location_row["lat"], location_row["lng"]
                coordinate_source = "REPRESENTATIVE_MAJOR_CITY"
            output_rows.append({
                "id": f"GND-{country['code']}-{index:03d}",
                "type": "GROUND",
                "lat": f"{lat:.6f}",
                "lng": f"{lng:.6f}",
                "alt_km": "0.000",
                "bandwidth_mbps": "100.0",
                "latency_ms": "10.0",
                "battery_percent": "100.0",
                "status": "ACTIVE",
                "country_code": country["code"],
                "country_name": country["country"],
                "continent": CONTINENT_NAMES[country["continent_code"]],
                "land_area_km2": f"{country['land_area_km2']:.1f}",
                "location_name": location,
                "coordinate_source": coordinate_source,
                "is_simulated": "true",
                "population_2024": country["population"],
                "idi_2025": f"{country['idi']:.1f}",
                "area_weight": f"{country['area_weight']:.2f}",
                "imputed_indicators": ";".join(
                    name for name, missing in (
                        ("population", country["population_imputed"]),
                        ("gdp_per_capita", country["gdp_imputed"]),
                        ("itu_idi", country["idi_imputed"]),
                        ("area_geonames_fallback", country["area_source"] != "WORLD_BANK_LAND_AREA"),
                    ) if missing
                ),
            })

    if len(output_rows) != TARGET_NODES:
        raise AssertionError(f"Expected {TARGET_NODES} nodes, generated {len(output_rows)}")
    csv_path = DATA / "global_ground_nodes_50.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=output_rows[0].keys())
        writer.writeheader()
        writer.writerows(output_rows)

    region_counts = Counter(row["continent"] for row in output_rows)
    country_counts = Counter(row["country_code"] for row in output_rows)
    document = ROOT / "document" / "Thiết bị.txt"
    with document.open("w", encoding="utf-8", newline="\n") as target:
        target.write(
            "SAGSIN GLOBAL GROUND NODE INVENTORY (50 nodes)\n"
            "Generated deterministically by backend/database/build_global_ground_inventory.py\n"
            f"Coverage: {len(selected_countries)} countries/economies from {len(countries)} candidates;\n"
            "each node retains ISO3 country code, country name, continent and representative city.\n"
            "Scope: ground-tier FL participants for simulation; not real tower/device inventory.\n"
            "Regional node quotas use each continent's share of total land area (Antarctica excluded),\n"
            "then largest-remainder rounding. Within each continent, country land area sets the base\n"
            "weight; population, nominal GDP per capita and ITU IDI gently adjust it. Max 2 nodes/country.\n"
            "For each region, choose one node per largest-weight country, then give remaining slots\n"
            "to the larger-area countries. Multiple nodes in a country use separate named cities.\n"
            "Economic values: World Bank 2024 GDP total / population; development indicators are\n"
            "normalised percentiles. Missing population/GDP values use the global median; missing IDI\n"
            "uses 78. Area is World Bank land area; GeoNames is a marked fallback where missing.\n"
            "All coordinates are WGS84 representative-city proxies, marked simulated; they do not\n"
            "claim actual device/station locations. Database altitude is 0 km.\n"
            "Three.js SphereGeometry radius=2: x=r*cos(lat)*cos(lng), y=r*sin(lat), z=-r*cos(lat)*sin(lng).\n"
            "Ground markers use visual radius 2.01; bandwidth 100 Mbps and latency 10 ms are sim defaults.\n"
            "Sources and attribution: README.md (data sources section).\n\n"
            "Regional totals: "
            + ", ".join(f"{region}={region_counts.get(region, 0)}" for region in CONTINENT_NAMES.values())
            + "\n\n"
            "id | continent | country_code | country | location | latitude | longitude | land_area_km2 | coordinate_source\n"
        )
        for row in output_rows:
            target.write(
                f"{row['id']} | {row['continent']} | {row['country_code']} | {row['country_name']} | "
                f"{row['location_name']} | {row['lat']} | {row['lng']} | {row['land_area_km2']} | "
                f"{row['coordinate_source']}\n"
            )

    print(f"candidates={len(countries)} nodes={len(output_rows)} countries={len(country_counts)}")
    print("regional_counts=" + ", ".join(
        f"{region}:{region_counts.get(region, 0)}" for region in CONTINENT_NAMES.values()
    ))
    print("country_counts=" + ", ".join(
        f"{row['country']}:{row['node_count']}" for row in selected_countries
    ))
    if area_fallbacks:
        print("geonames_area_fallback=" + ",".join(area_fallbacks))


if __name__ == "__main__":
    build_inventory()
