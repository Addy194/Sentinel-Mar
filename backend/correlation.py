import hashlib
import json
import math
from datetime import datetime, timezone

from shapely.geometry import shape

from geo import haversine_km, distance_to_geom_km, major_axis_bearing, max_extent_km, bearing_deg
from models import CorrelationParams
from correlation_env import drift_vector_ms
from gapfill import fill_gaps, GAP_FILL_VERSION
from drift import build_drift_model, score_fixes, DRIFT_MODEL_VERSION

ALGORITHM_VERSION = "corr-1.1.0"
SEVERE_FLAGS = {"natural_seep_suspect", "low_wind", "sunglint", "conflicting_source", "cloud_contaminated", "lookalike_suspect"}
RELIABILITY_PENALTIES = {
    "spoof_suspect": 0.4, "position_jump": 0.3, "implausible_speed": 0.2, "naive_timestamp": 0.1,
    "stale": 0.2, "missing_identity": 0.1, "future_timestamp": 0.3, "interpolated": 0.0,
}
STATUS_ORDER = ["insufficient_evidence", "possible", "probable"]


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def cap_status(status, cap):
    return STATUS_ORDER[min(STATUS_ORDER.index(status), STATUS_ORDER.index(cap))]


_path_cache: dict = {}


def drift_model_path(model):
    """Rebuild the hourly path list from the stored model (cached per model object)."""
    key = id(model)
    if key not in _path_cache:
        coords = model["path"]["coordinates"]
        _path_cache.clear()
        _path_cache[key] = [{"h": h, "lat": c[1], "lon": c[0], "sigma_km": s} for h, c, s in zip(model["path_hours"], coords, model["sigma_km"])]
    return _path_cache[key]


def resolve_environment(spill, params: CorrelationParams):
    wind = params.wind.model_dump() if params.wind else (spill.get("wind") if params.use_observation_environment else None)
    current = params.current.model_dump() if params.current else (spill.get("current") if params.use_observation_environment else None)
    return wind, current


def input_hash(spill, positions, params, wind, current):
    payload = {
        "algorithm": ALGORITHM_VERSION,
        "spill": {"id": spill["id"], "geometry": spill["geometry"], "t": spill["acquisition_time"].isoformat(),
                  "flags": sorted(spill.get("quality_flags", [])), "conf": spill["detection_confidence"]},
        "params": params.model_dump(), "wind": wind, "current": current,
        "positions": sorted((p["id"], p["timestamp"].isoformat(), p["lat"], p["lon"]) for p in positions),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def run_correlation(spill, positions, params: CorrelationParams):
    log = []

    def L(msg, level="info"):
        log.append({"t": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg})

    poly = shape(spill["geometry"])
    centroid = poly.centroid
    t0 = spill["acquisition_time"]
    axis = major_axis_bearing(poly)
    wind, current = resolve_environment(spill, params)
    degraded = not (wind or current)
    severe = sorted(set(spill.get("quality_flags", [])) & SEVERE_FLAGS)
    low_conf = spill["detection_confidence"] < 0.4
    spill_age = params.spill_age_hours if params.spill_age_hours is not None else spill.get("estimated_age_hours")

    L(f"Algorithm {ALGORITHM_VERSION}; spill {spill['id'][:8]} centroid ({centroid.y:.4f}, {centroid.x:.4f}), "
      f"extent {max_extent_km(poly):.1f} km, major axis {axis:.0f}°, detection confidence {spill['detection_confidence']:.2f}")
    L(f"Search corridor {params.corridor_km} km; window -{params.window_hours_before}h / +{params.window_hours_after}h")
    if degraded:
        L("No wind/current inputs available — drift-back uncertainty unresolved; attribution marked DEGRADED", "warn")
        drift_model = None
    else:
        vx, vy = drift_vector_ms(wind, current)
        L(f"Drift model: 3% wind + surface current → {math.hypot(vx, vy):.2f} m/s toward {(math.degrees(math.atan2(vx, vy)) + 360) % 360:.0f}°")
        drift_model = build_drift_model(centroid.y, centroid.x, wind, current, params.window_hours_before, spill_age)
        L(f"Backward Lagrangian model {DRIFT_MODEL_VERSION}: {drift_model['hours']:.0f} h × {drift_model['step_hours']:.0f} h steps, 2σ envelope grows to {drift_model['sigma_km'][-1] * 2:.1f} km; likely origin window {drift_model['likely_window_hours'][0]}–{drift_model['likely_window_hours'][1]} h before acquisition")
    if severe:
        L(f"Spill quality flags {severe} — candidate statuses capped at 'possible'", "warn")
    if low_conf:
        L("Detection confidence < 0.4 — statuses capped at 'possible'", "warn")
    if spill_age is None:
        L("Spill age unknown — time-gap scoring uses full search window", "warn")

    by_vessel = {}
    for p in positions:
        by_vessel.setdefault(p["mmsi"], []).append(p)
    L(f"{len(positions)} AIS fixes from {len(by_vessel)} vessels inside corridor/time window")
    if params.fill_gaps:
        L(f"AIS gap filling {GAP_FILL_VERSION}: dead-reckoning across gaps > {params.gap_threshold_min} min; implausible transits flagged spoof_suspect")

    candidates = []
    for mmsi, fixes in sorted(by_vessel.items()):
        fixes.sort(key=lambda p: (p["timestamp"], p["id"]))
        real_fixes = list(fixes)
        segments = []
        if params.fill_gaps:
            fixes, segments = fill_gaps(fixes, params.gap_threshold_min)
        dists = [distance_to_geom_km(poly, p["lat"], p["lon"]) for p in fixes]
        i_min = min(range(len(fixes)), key=lambda i: (dists[i], i))
        closest, d_min = fixes[i_min], dists[i_min]
        gap_h = (t0 - closest["timestamp"]).total_seconds() / 3600
        notes = []

        spatial = math.exp(-d_min / (params.corridor_km / 3))
        gap_penalty = 0.0
        if closest.get("interpolated"):
            gap_penalty = clamp(closest["gap_hours"] / 12, 0, 0.6)
            spatial *= 1 - gap_penalty
            notes.append(f"closest approach is an interpolated position inside a {closest['gap_hours']}h AIS gap — spatial score reduced {gap_penalty * 100:.0f}%")
        if gap_h >= 0:
            temporal = clamp(1 - gap_h / params.window_hours_before)
        else:
            temporal = clamp(1 - abs(gap_h) / max(params.window_hours_after, 0.01)) * 0.3
            notes.append("closest approach occurred after acquisition (weak evidence)")
        fixes_before = sum(1 for p in fixes if p["timestamp"] <= t0)
        if spill_age is not None and gap_h > spill_age * 1.5:
            temporal *= 0.5
            notes.append(f"time gap {gap_h:.1f}h exceeds 1.5× estimated spill age {spill_age}h")

        n = len(real_fixes)
        max_gap = 0.0
        jumps = set()
        dark_over_spill = False
        for a, b in zip(real_fixes, real_fixes[1:]):
            dt_h = (b["timestamp"] - a["timestamp"]).total_seconds() / 3600
            max_gap = max(max_gap, dt_h)
            if dt_h > 0:
                kn = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) / 1.852 / dt_h
                if kn > 50:
                    jumps.add("position_jump")
            if dt_h > 2 and a["timestamp"] <= closest["timestamp"] <= b["timestamp"] + (b["timestamp"] - a["timestamp"]):
                dark_over_spill = True
        continuity = 0.0 if n < params.min_positions else clamp(1 - max(0.0, max_gap - 0.5) / 6)
        if dark_over_spill:
            notes.append(f"AIS gap of {max_gap:.1f}h adjacent to closest approach (possible dark period)")
        spoof_segs = [s for s in segments if s["spoof_suspect"]]
        if spoof_segs:
            jumps.add("spoof_suspect")
            notes.append(f"{len(spoof_segs)} gap(s) require {max(s['required_speed_kn'] for s in spoof_segs):.0f} kn to close — kinematically implausible, flagged spoof_suspect (not interpolated)")
        filled = [s for s in segments if s["interpolated_points"]]
        if filled:
            notes.append(f"{len(filled)} AIS gap(s) totalling {sum(s['gap_hours'] for s in filled):.1f}h filled by dead reckoning ({sum(s['interpolated_points'] for s in filled)} synthetic points, dashed on map)")

        sog = closest.get("sog_kn") or 0.0
        cog = closest.get("cog_deg")
        if cog is None and i_min + 1 < n:
            nxt = fixes[i_min + 1]
            cog = bearing_deg(closest["lat"], closest["lon"], nxt["lat"], nxt["lon"])
        if sog < 0.5 or cog is None:
            heading, heading_detail = 0.4, "vessel stationary or COG unavailable — neutral"
        else:
            diff = abs((cog % 180) - axis)
            diff = min(diff, 180 - diff)
            heading = clamp(1 - diff / 90)
            heading_detail = f"COG {cog:.0f}° vs spill axis {axis:.0f}° (Δ {diff:.0f}°)"

        backprojected = None
        drift_match = None
        if gap_h < 0:
            drift, drift_detail = 0.15, "vessel closest approach post-dates acquisition — cannot precede observed slick"
        elif degraded:
            drift, drift_detail = 0.5, "no wind/current — neutral score, attribution degraded"
        else:
            from drift import position_at
            o = position_at(drift_model_path(drift_model), gap_h)
            backprojected = {"type": "Point", "coordinates": [round(o["lon"], 6), round(o["lat"], 6)]}
            drift_match = score_fixes(drift_model_path(drift_model), fixes, t0)
            if drift_match:
                drift = drift_match["score"]
                drift_detail = (f"best fix {drift_match['hours_before']}h before acquisition lies {drift_match['distance_km']:.1f} km from back-tracked origin (σ {drift_match['sigma_km']:.1f} km, z={drift_match['z']}) — "
                                + ("inside 2σ origin envelope" if drift_match["inside_2sigma"] else "outside 2σ origin envelope") + (" · via interpolated position" if drift_match["interpolated"] else ""))
                if drift_match["interpolated"]:
                    drift *= 0.8
            else:
                drift, drift_detail = 0.2, "no fixes before acquisition inside the 72h model horizon"

        flags = set(jumps)
        for p in real_fixes:
            flags |= set(p.get("quality_flags", []))
        if not closest.get("imo") and not closest.get("vessel_name"):
            flags.add("missing_identity")
        flags = sorted(flags)
        reliability = clamp(1 - sum(RELIABILITY_PENALTIES.get(f, 0.05) for f in flags))

        factors = {
            "spatial": {"score": round(spatial, 4), "detail": f"closest approach {d_min:.2f} km from spill boundary"},
            "temporal": {"score": round(temporal, 4), "detail": f"{gap_h:.1f}h before acquisition" if gap_h >= 0 else f"{abs(gap_h):.1f}h after acquisition"},
            "continuity": {"score": round(continuity, 4), "detail": f"{n} fixes, max gap {max_gap:.1f}h"},
            "heading": {"score": round(heading, 4), "detail": heading_detail},
            "drift": {"score": round(drift, 4), "detail": drift_detail},
            "reliability": {"score": round(reliability, 4), "detail": f"AIS flags: {', '.join(flags) if flags else 'none'}"},
        }
        w = params.weights
        total_w = sum(w.get(k, 0) for k in factors) or 1.0
        score = sum(w.get(k, 0) * factors[k]["score"] for k in factors) / total_w
        for k in factors:
            factors[k]["weight"] = w.get(k, 0)
            factors[k]["contribution"] = round(w.get(k, 0) * factors[k]["score"] / total_w, 4)

        status = "probable" if score >= 0.7 else "possible" if score >= 0.45 else "insufficient_evidence"
        if severe or low_conf:
            status = cap_status(status, "possible")
            notes.append("status capped: spill observation quality/confidence concerns")
        if reliability < 0.4:
            status = cap_status(status, "possible")
            notes.append("status capped: low AIS reliability")
        if n < params.min_positions:
            status = "insufficient_evidence"
            notes.append(f"fewer than {params.min_positions} AIS fixes in window")
        if fixes_before == 0:
            status = "insufficient_evidence"
            notes.append("no AIS fixes before acquisition time")

        candidates.append({
            "mmsi": mmsi, "imo": closest.get("imo"), "vessel_name": closest.get("vessel_name"),
            "vessel_type": closest.get("vessel_type"), "score": round(score, 4), "status": status,
            "factors": factors, "notes": notes, "ais_flags": flags,
            "evidence": {
                "closest_fix": {"id": closest["id"], "timestamp": closest["timestamp"], "lat": closest["lat"], "lon": closest["lon"],
                                "sog_kn": closest.get("sog_kn"), "cog_deg": closest.get("cog_deg"), "source": closest.get("source")},
                "distance_km": round(d_min, 3), "time_gap_hours": round(gap_h, 3), "fix_count": n, "interpolated_count": len(fixes) - n,
                "max_gap_hours": round(max_gap, 2), "backprojected_centroid": backprojected, "drift_match": drift_match, "gap_penalty": round(gap_penalty, 3),
                "gap_segments": segments, "closest_is_interpolated": bool(closest.get("interpolated")),
                "fix_ids": [p["id"] for p in real_fixes],
            },
            "track": [{"timestamp": p["timestamp"], "lat": p["lat"], "lon": p["lon"], "sog_kn": p.get("sog_kn"), "cog_deg": p.get("cog_deg"), "interpolated": bool(p.get("interpolated"))} for p in fixes[:800]],
        })

    candidates.sort(key=lambda c: (-STATUS_ORDER.index(c["status"]), -c["score"], c["mmsi"]))
    ambiguous = len(candidates) >= 2 and candidates[0]["score"] - candidates[1]["score"] < 0.08
    if ambiguous:
        L("Top two candidates within 0.08 score — multiple-vessel ambiguity, statuses capped at 'possible'", "warn")
        for c in candidates[:2]:
            c["status"] = cap_status(c["status"], "possible")
            c["notes"].append("status capped: comparable evidence for multiple vessels")
    for i, c in enumerate(candidates):
        c["rank"] = i + 1
        L(f"#{c['rank']} {c['vessel_name'] or c['mmsi']} (MMSI {c['mmsi']}): score {c['score']:.3f} → {c['status']}")

    if severe and spill["detection_confidence"] < 0.5:
        overall = "indeterminate"
        L("Overall: INDETERMINATE — spill observation ambiguous (possible lookalike/seep) with low confidence", "warn")
    elif not candidates:
        overall = "insufficient_evidence"
        L("Overall: no AIS candidates within corridor/time window — insufficient evidence")
    else:
        overall = candidates[0]["status"]
        L(f"Overall attribution status: {overall}")

    top = candidates[0]["score"] if candidates else 0.0
    if overall == "probable" and not degraded:
        band = "high"
    elif overall in ("probable", "possible"):
        band = "medium"
    else:
        band = "low"

    return {
        "algorithm_version": ALGORITHM_VERSION,
        "params": params.model_dump(),
        "environment": {"wind": wind, "current": current, "source": "observation" if (wind or current) and not (params.wind or params.current) else "params"},
        "degraded": degraded,
        "spill_quality_flags": sorted(spill.get("quality_flags", [])),
        "severe_flags": severe,
        "ambiguous_multiple_vessels": ambiguous,
        "spill_axis_bearing": axis,
        "drift_model": drift_model,
        "gap_fill": {"enabled": params.fill_gaps, "version": GAP_FILL_VERSION if params.fill_gaps else None, "threshold_min": params.gap_threshold_min},
        "candidates": candidates,
        "overall_status": overall,
        "confidence_band": band,
        "top_score": round(top, 4),
        "input_hash": input_hash(spill, positions, params, wind, current),
        "position_count": len(positions),
        "vessel_count": len(by_vessel),
        "processing_log": log,
    }
