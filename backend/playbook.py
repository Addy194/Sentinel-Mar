import math
from datetime import timedelta

import numpy as np
from global_land_mask import globe
from shapely.geometry import shape

from db import db, to_utc
from geo import destination
from correlation_env import drift_vector_ms

PLAYBOOK_VERSION = "playbook-rules-0.1.0"
THICKNESS_UM = {"sheen": 0.1, "thin": 1.0, "thick": 10.0}  # µm assumptions per appearance class


def coast_distance_km(lat, lon, max_km=300):
    """Approximate distance to nearest land using the 1-km global land mask (radial search)."""
    if globe.is_land(lat, lon):
        return 0.0, "on land mask (shoreline/estuary)"
    for r in [1, 2, 5, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200, 300]:
        if r > max_km:
            break
        for b in range(0, 360, 15):
            la, lo = destination(lat, lon, b, r)
            if -90 <= la <= 90 and globe.is_land(la, ((lo + 180) % 360) - 180):
                return float(r), f"nearest land ≈{r} km bearing {b}°"
    return float(max_km), f">{max_km} km offshore"


def build_playbook(case, spill, result):
    area = spill.get("estimated_area_km2") or 0.0
    conf = spill.get("detection_confidence") or 0
    lon, lat = spill["centroid"]["coordinates"]
    wind, current = (result or {}).get("environment", {}).get("wind") if result else spill.get("wind"), (result or {}).get("environment", {}).get("current") if result else spill.get("current")
    thick_class = "thick" if area < 2 else "thin" if area < 25 else "sheen"
    vol_m3 = {k: area * 1e6 * v * 1e-6 for k, v in THICKNESS_UM.items()}
    vol_t = {k: round(v * 0.9, 1) for k, v in vol_m3.items()}
    coast_km, coast_note = coast_distance_km(lat, lon)
    depth_class = "shallow (<50 m likely)" if coast_km < 20 else "shelf (50–200 m likely)" if coast_km < 80 else "deep water likely"
    wind_ms = wind["speed_ms"] if wind else None
    sea_state = None if wind_ms is None else ("calm" if wind_ms < 5 else "moderate" if wind_ms < 10 else "rough" if wind_ms < 15 else "severe")
    vx, vy = drift_vector_ms(wind, current) if (wind or current) else (0.0, 0.0)
    drift_speed = math.hypot(vx, vy)
    drift_bearing = (math.degrees(math.atan2(vx, vy)) + 360) % 360 if drift_speed > 0 else None
    poly = shape(spill["geometry"])
    bounds = poly.bounds
    ext_km = max((bounds[2] - bounds[0]) * 111.32 * math.cos(math.radians(lat)), (bounds[3] - bounds[1]) * 110.574)
    tactical = []
    if drift_bearing is not None:
        # down-drift edge: project spill boundary in drift direction; boom line perpendicular, 6 h ahead
        lead_km = drift_speed * 6 * 3.6
        edge_lat, edge_lon = destination(lat, lon, drift_bearing, ext_km / 2 + lead_km)
        for i, off in enumerate([-0.6, 0, 0.6]):
            bl, bo = destination(edge_lat, edge_lon, (drift_bearing + 90) % 360, off * max(ext_km, 1.0))
            tactical.append({"id": f"boom-{i + 1}", "lat": round(bl, 5), "lon": round(bo, 5), "role": "containment boom anchor (down-drift line, 6 h lead)", "bearing_of_line_deg": round((drift_bearing + 90) % 360)})
        sk_lat, sk_lon = destination(lat, lon, drift_bearing, ext_km / 4)
        tactical.append({"id": "skimmer-1", "lat": round(sk_lat, 5), "lon": round(sk_lon, 5), "role": "skimmer / recovery vessel at thickest down-drift zone"})
    t0 = to_utc(case["acquisition_time"])
    eta_coast_h = round(coast_km / (drift_speed * 3.6), 1) if drift_speed > 0.02 and coast_km < 300 else None
    tier1 = {"tier": 1, "title": "Containment & recovery", "priority": "immediate" if area >= 0.5 or coast_km < 30 else "standard",
             "actions": [f"Deploy {'ocean' if coast_km > 30 else 'harbour/inshore'} containment booms along the down-drift edge (see tactical coordinates); estimated slick extent {ext_km:.1f} km.",
                         f"Position {'weir/brush' if thick_class == 'thick' else 'oleophilic drum'} skimmers with temporary storage ≥ {max(10, vol_m3['thick'] * 0.3):.0f} m³.",
                         "Issue NAVTEX/notice to mariners; establish 3 nm exclusion zone; overflight/drone verification of slick edges within 2 h.",
                         "Log sample collection (fingerprinting) at 3 points for source identification and legal chain of custody."],
             "constraints": [f"Sea state {sea_state or 'unknown'} — booms lose effectiveness above ~1 m significant wave height / 10 m/s wind" if sea_state in (None, "rough", "severe") else f"Sea state {sea_state}: mechanical recovery viable."]}
    dispersant_ok = coast_km >= 20 and "shallow" not in depth_class and thick_class != "sheen" and (wind_ms is None or 4 <= wind_ms <= 12)
    tier2 = {"tier": 2, "title": "Chemical & biological treatment", "priority": "conditional",
             "dispersant": {"suitable": dispersant_ok, "reason": ("Offshore (≥20 km), sufficient depth, fresh non-sheen oil and mixing energy" if dispersant_ok else
                            "; ".join([r for r, bad in [("within 20 km of shore", coast_km < 20), ("shallow water", "shallow" in depth_class), ("sheen too thin to disperse", thick_class == "sheen"), ("insufficient/excess wind for mixing", wind_ms is not None and not 4 <= wind_ms <= 12)] if bad]) or "insufficient data"),
                            "note": "Requires national authority approval (e.g. NOS-DCP / regional contingency plan); never over reefs, mangroves, aquaculture or drinking-water intakes."},
             "in_situ_burning": {"suitable": coast_km >= 50 and thick_class == "thick", "reason": "fresh thick oil far offshore" if coast_km >= 50 and thick_class == "thick" else "too thin / too near shore"},
             "bioremediation": {"suitable": coast_km < 30, "reason": "shoreline stranding likely — nutrient-enhanced bioremediation for sandy/gravel beaches; avoid pressure washing on rocky intertidal" if coast_km < 30 else "not applicable offshore"}}
    tier3 = {"tier": 3, "title": "Restoration monitoring", "priority": "follow-up",
             "schedule": [{"when": (t0 + timedelta(hours=24)).isoformat(), "task": "Repeat SAR/optical acquisition request; update drift forecast"},
                          {"when": (t0 + timedelta(days=3)).isoformat(), "task": "Shoreline (SCAT) survey along threatened coast; water & sediment sampling"},
                          {"when": (t0 + timedelta(days=14)).isoformat(), "task": "Fisheries/aquaculture tissue sampling; seabird & turtle mortality census"},
                          {"when": (t0 + timedelta(days=90)).isoformat(), "task": "Sediment PAH re-sampling; mangrove/wetland recovery assessment; close or extend monitoring"}]}
    return {"version": PLAYBOOK_VERSION, "advisory": True, "disclaimer": "ADVISORY — algorithmic guidance from a rules engine, not an operational order. Validate with on-scene commander and the national contingency plan.",
            "inputs": {"area_km2": round(area, 3), "detection_confidence": conf, "thickness_class": thick_class, "estimated_volume_m3": {k: round(v, 1) for k, v in vol_m3.items()}, "estimated_volume_tonnes": vol_t,
                       "coast_distance_km": coast_km, "coast_note": coast_note, "depth_class": depth_class, "wind_ms": wind_ms, "sea_state": sea_state, "drift_speed_ms": round(drift_speed, 3), "drift_bearing_deg": round(drift_bearing) if drift_bearing is not None else None,
                       "eta_to_coast_hours": eta_coast_h, "primary_jurisdiction": (case.get("primary_jurisdiction") or {}).get("code")},
            "tactical_coordinates": tactical, "tiers": [tier1, tier2, tier3]}


async def playbook_for_case(case_id: str):
    case = await db.cases.find_one({"id": case_id}, {"_id": 0})
    if not case:
        return None
    spill = await db.spill_observations.find_one({"id": case["spill_observation_id"]}, {"_id": 0})
    result = await db.correlation_results.find_one({"case_id": case_id}, {"_id": 0, "environment": 1}, sort=[("version", -1)])
    return build_playbook(case, spill, result)
