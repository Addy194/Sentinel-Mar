from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from shapely.geometry import shape

from db import db, clean, audit
from geo import circle_polygon
from models import CorrelateRequest, ReviewCreate, REASON_CODES, new_id
from jobs import enqueue, process

router = APIRouter()


async def _case(case_id):
    case = await db.cases.find_one({"id": case_id}, {"_id": 0})
    if not case:
        raise HTTPException(404, "case not found")
    return case


async def _result(case_id, version: Optional[int]):
    q = {"case_id": case_id}
    if version:
        q["version"] = version
    return await db.correlation_results.find_one(q, {"_id": 0}, sort=[("version", -1)])


@router.get("/cases")
async def list_cases(status: Optional[str] = None, attribution_status: Optional[str] = None, limit: int = Query(200, le=1000)):
    q = {}
    if status:
        q["status"] = status
    if attribution_status:
        q["attribution_status"] = attribution_status
    return clean(await db.cases.find(q, {"_id": 0}).sort("acquisition_time", -1).to_list(limit))


@router.get("/cases/{case_id}")
async def get_case(case_id: str):
    case = await _case(case_id)
    spill = await db.spill_observations.find_one({"id": case["spill_observation_id"]}, {"_id": 0, "raw_input": 0})
    scene = await db.scenes.find_one({"id": case["scene_id"]}, {"_id": 0}) if case.get("scene_id") else None
    versions = await db.correlation_results.find({"case_id": case_id}, {"_id": 0, "version": 1, "created_at": 1, "overall_status": 1, "algorithm_version": 1, "input_hash": 1, "degraded": 1}).sort("version", 1).to_list(100)
    return clean({**case, "spill_observation": spill, "scene": scene, "result_versions": versions})


@router.post("/cases/{case_id}/correlate", status_code=202)
async def correlate_case(case_id: str, body: CorrelateRequest = CorrelateRequest()):
    await _case(case_id)
    job = await enqueue("correlate", {"case_id": case_id, "params": body.params.model_dump() if body.params else None}, body.actor, inline=body.sync)
    await audit("case", case_id, "case.correlation_requested", {"job_id": job["id"], "sync": body.sync}, body.actor)
    if body.sync:
        job = await process(job["id"])
    return clean(job)


@router.get("/cases/{case_id}/candidates")
async def get_candidates(case_id: str, version: Optional[int] = None, include_tracks: bool = False):
    case = await _case(case_id)
    result = await _result(case_id, version)
    if not result:
        return {"case_id": case_id, "version": 0, "candidates": [], "overall_status": case["attribution_status"], "message": "no correlation run yet"}
    if not include_tracks:
        for c in result["candidates"]:
            c.pop("track", None)
    result.pop("processing_log", None)
    return clean({"case_id": case_id, **result, "attribution_status": case["attribution_status"], "review_state": case["review_state"],
                  "disclaimer": "Ranked candidates are decision-support output from AIS/satellite correlation, not a legal determination of responsibility."})


@router.post("/cases/{case_id}/review", status_code=201)
async def review_case(case_id: str, body: ReviewCreate):
    case = await _case(case_id)
    bad = [c for c in body.reason_codes if c not in REASON_CODES]
    if bad:
        raise HTTPException(400, f"unknown reason codes: {bad}")
    result = await _result(case_id, body.result_version)
    if body.decision == "confirm":
        if not body.vessel_mmsi:
            raise HTTPException(400, "vessel_mmsi is required to confirm")
        if not result or body.vessel_mmsi not in {c["mmsi"] for c in result["candidates"]}:
            raise HTTPException(400, "vessel_mmsi must be a ranked candidate in the referenced result version")
    now = datetime.now(timezone.utc)
    review = {"id": new_id(), "case_id": case_id, "result_version": result["version"] if result else None, "decision": body.decision,
              "vessel_mmsi": body.vessel_mmsi, "reason_codes": body.reason_codes, "notes": body.notes, "analyst": body.analyst,
              "previous_attribution_status": case["attribution_status"], "created_at": now}
    await db.reviews.insert_one(dict(review))
    update = {"updated_at": now}
    if body.decision == "confirm":
        update.update({"attribution_status": "analyst_confirmed", "review_state": "confirmed", "confirmed_vessel_mmsi": body.vessel_mmsi, "status": "closed"})
    elif body.decision == "reject":
        update.update({"attribution_status": "insufficient_evidence", "review_state": "rejected", "confirmed_vessel_mmsi": None, "status": "closed"})
    else:
        update.update({"review_state": "needs_more_data", "status": "under_review"})
    await db.cases.update_one({"id": case_id}, {"$set": update})
    await audit("case", case_id, f"review.{body.decision}", {"review_id": review["id"], "vessel_mmsi": body.vessel_mmsi, "reason_codes": body.reason_codes,
                                                          "result_version": review["result_version"], "from": case["attribution_status"], "to": update.get("attribution_status", case["attribution_status"])}, body.analyst)
    review.pop("_id", None)
    return clean(review)


@router.get("/cases/{case_id}/reviews")
async def list_reviews(case_id: str):
    await _case(case_id)
    return clean(await db.reviews.find({"case_id": case_id}, {"_id": 0}).sort("created_at", 1).to_list(500))


def _geojson(case, spill, result):
    features = [{"type": "Feature", "geometry": spill["geometry"], "properties": {"layer": "spill", "id": spill["id"], "case_number": case["case_number"],
                 "acquisition_time": spill["acquisition_time"], "detection_confidence": spill["detection_confidence"], "quality_flags": spill["quality_flags"],
                 "estimated_area_km2": spill["estimated_area_km2"], "source": spill["source"]}}]
    if result:
        lon, lat = spill["centroid"]["coordinates"]
        features.append({"type": "Feature", "geometry": circle_polygon(lat, lon, result["params"]["corridor_km"] + spill.get("extent_km", 0)),
                         "properties": {"layer": "corridor", "radius_km": result["params"]["corridor_km"] + spill.get("extent_km", 0)}})
        for c in result["candidates"]:
            props = {"layer": "track", "mmsi": c["mmsi"], "vessel_name": c.get("vessel_name"), "rank": c["rank"], "score": c["score"], "status": c["status"]}
            track = c.get("track", [])
            if len(track) >= 2:
                features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in track]},
                                 "properties": {**props, "timestamps": [p["timestamp"] for p in track]}})
            cf = c["evidence"]["closest_fix"]
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [cf["lon"], cf["lat"]]},
                             "properties": {**props, "layer": "closest_fix", "timestamp": cf["timestamp"], "distance_km": c["evidence"]["distance_km"],
                                            "time_gap_hours": c["evidence"]["time_gap_hours"], "sog_kn": cf.get("sog_kn"), "cog_deg": cf.get("cog_deg")}})
            if c["evidence"].get("backprojected_centroid"):
                features.append({"type": "Feature", "geometry": c["evidence"]["backprojected_centroid"],
                                 "properties": {**props, "layer": "backprojected_centroid"}})
    return {"type": "FeatureCollection", "features": features}


@router.get("/cases/{case_id}/geojson")
async def case_geojson(case_id: str, version: Optional[int] = None):
    case = await _case(case_id)
    spill = await db.spill_observations.find_one({"id": case["spill_observation_id"]}, {"_id": 0, "raw_input": 0})
    result = await _result(case_id, version)
    return clean(_geojson(case, spill, result))


@router.get("/cases/{case_id}/evidence")
async def case_evidence(case_id: str, version: Optional[int] = None):
    case = await _case(case_id)
    spill = await db.spill_observations.find_one({"id": case["spill_observation_id"]}, {"_id": 0})
    scene = await db.scenes.find_one({"id": case["scene_id"]}, {"_id": 0}) if case.get("scene_id") else None
    result = await _result(case_id, version)
    all_versions = await db.correlation_results.find({"case_id": case_id}, {"_id": 0, "candidates": 0, "processing_log": 0}).sort("version", 1).to_list(100)
    reviews = await db.reviews.find({"case_id": case_id}, {"_id": 0}).sort("created_at", 1).to_list(500)
    entity_ids = [case_id, spill["id"]] + ([scene["id"]] if scene else [])
    audit_events = await db.audit_events.find({"entity_id": {"$in": entity_ids}}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    jobs = await db.jobs.find({"payload.case_id": case_id}, {"_id": 0}).sort("created_at", 1).to_list(200)
    calculations = None
    if result:
        calculations = {"algorithm_version": result["algorithm_version"], "input_hash": result["input_hash"], "params": result["params"],
                        "environment": result["environment"], "degraded": result["degraded"], "spill_axis_bearing": result["spill_axis_bearing"],
                        "candidates": [{k: v for k, v in c.items() if k != "track"} for c in result["candidates"]],
                        "processing_log": result["processing_log"]}
    return clean({
        "case": case,
        "source_references": {"scene": scene, "spill_observation": spill, "storage_ref": scene.get("storage_ref") if scene else None,
                              "ais_fix_ids": [fid for c in (result or {}).get("candidates", []) for fid in c["evidence"]["fix_ids"]]},
        "geometries": _geojson(case, {k: v for k, v in spill.items() if k != "raw_input"}, result),
        "calculations": calculations,
        "result_versions": all_versions,
        "reviews": reviews,
        "audit_history": audit_events,
        "jobs": jobs,
        "disclaimer": "Decision-support evidence bundle. Correlation output indicates possible/probable association only; responsibility requires analyst confirmation and corroborating evidence.",
    })
