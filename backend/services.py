import hashlib
import math
import random
from datetime import datetime, timezone, timedelta

from shapely.geometry import shape, mapping

from db import db, audit, to_utc
from geo import validate_polygon, area_km2, max_extent_km, rotated_rect_polygon
from models import new_id, AISPositionIn, SpillObservationCreate, SceneCreate, CorrelationParams
from correlation import run_correlation, ALGORITHM_VERSION
from jobs import handler, job_log

MOCK_DETECTOR_VERSION = "mock-sar-detector-0.1.0"


async def create_scene(payload: SceneCreate, actor="system"):
    validate_polygon(payload.footprint.model_dump())
    if await db.scenes.find_one({"provider": payload.provider, "provider_scene_id": payload.provider_scene_id}):
        raise ValueError("scene with this provider/provider_scene_id already exists")
    doc = payload.model_dump()
    doc.update({"id": new_id(), "acquisition_time": to_utc(payload.acquisition_time), "processing_version": "scene-ingest-1.0",
                "status": "registered", "created_at": datetime.now(timezone.utc)})
    await db.scenes.insert_one(dict(doc))
    await audit("scene", doc["id"], "scene.registered", {"provider": doc["provider"], "provider_scene_id": doc["provider_scene_id"]}, actor)
    return doc


async def create_spill_observation(payload: SpillObservationCreate, actor="system"):
    poly = validate_polygon(payload.geometry.model_dump())
    if payload.scene_id and not await db.scenes.find_one({"id": payload.scene_id}):
        raise ValueError("scene_id not found")
    unknown = set(payload.quality_flags) - set(__import__("models").SPILL_QUALITY_FLAGS)
    if unknown:
        raise ValueError(f"unknown quality flags: {sorted(unknown)}")
    now = datetime.now(timezone.utc)
    spill_id, case_id = new_id(), new_id()
    c = poly.centroid
    doc = payload.model_dump()
    doc.update({
        "id": spill_id, "case_id": case_id, "acquisition_time": to_utc(payload.acquisition_time),
        "centroid": {"type": "Point", "coordinates": [round(c.x, 6), round(c.y, 6)]},
        "estimated_area_km2": payload.estimated_area_km2 if payload.estimated_area_km2 is not None else area_km2(poly),
        "extent_km": round(max_extent_km(poly), 3), "created_at": now, "raw_input": payload.model_dump(mode="json"),
    })
    await db.spill_observations.insert_one(dict(doc))
    seq = await db.cases.count_documents({}) + 1
    case = {
        "id": case_id, "case_number": f"SPL-{doc['acquisition_time'].strftime('%Y%m%d')}-{seq:03d}",
        "spill_observation_id": spill_id, "scene_id": payload.scene_id, "status": "open",
        "attribution_status": "indeterminate", "automated_status": None, "confidence_band": None, "degraded": None,
        "review_state": "pending", "confirmed_vessel_mmsi": None, "latest_result_version": 0,
        "acquisition_time": doc["acquisition_time"], "centroid": doc["centroid"], "source": payload.source,
        "detection_confidence": payload.detection_confidence, "quality_flags": payload.quality_flags,
        "created_at": now, "updated_at": now,
    }
    await db.cases.insert_one(dict(case))
    await audit("spill_observation", spill_id, "spill.created", {"case_id": case_id, "source": payload.source, "processing_version": payload.processing_version}, actor)
    await audit("case", case_id, "case.opened", {"spill_observation_id": spill_id}, actor)
    doc.pop("_id", None)
    case.pop("_id", None)
    return doc, case


def _dedup_hash(p: AISPositionIn, ts):
    key = f"{p.mmsi}|{ts.isoformat()}|{round(p.lat, 5)}|{round(p.lon, 5)}"
    return hashlib.sha1(key.encode()).hexdigest()


async def ingest_ais(positions, source_batch_id=None, actor="system"):
    now = datetime.now(timezone.utc)
    inserted, duplicates, rejected, flagged = 0, 0, [], 0
    docs, seen = [], set()
    for i, p in enumerate(positions):
        flags = set(p.quality_flags)
        ts = p.timestamp
        if ts.tzinfo is None:
            flags.add("naive_timestamp")
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)
        if ts > now + timedelta(minutes=5):
            flags.add("future_timestamp")
        if ts < now - timedelta(days=3650):
            rejected.append({"index": i, "reason": "timestamp older than retention horizon"})
            continue
        if p.sog_kn is not None and p.sog_kn > 60:
            flags.add("implausible_speed")
        if not (p.mmsi.isdigit() and len(p.mmsi) == 9):
            flags.add("spoof_suspect")
        if not p.imo and not p.vessel_name:
            flags.add("missing_identity")
        h = _dedup_hash(p, ts)
        if h in seen:
            duplicates += 1
            continue
        seen.add(h)
        if flags:
            flagged += 1
        docs.append({
            "id": new_id(), "mmsi": p.mmsi, "imo": p.imo, "vessel_name": p.vessel_name, "vessel_type": p.vessel_type,
            "timestamp": ts, "lat": p.lat, "lon": p.lon, "location": {"type": "Point", "coordinates": [p.lon, p.lat]},
            "sog_kn": p.sog_kn, "cog_deg": p.cog_deg, "heading_deg": p.heading_deg, "source": p.source,
            "quality_flags": sorted(flags), "dedup_hash": h, "batch_id": source_batch_id, "received_at": now,
        })
    if docs:
        existing = {d["dedup_hash"] for d in await db.ais_positions.find({"dedup_hash": {"$in": [d["dedup_hash"] for d in docs]}}, {"dedup_hash": 1}).to_list(None)}
        fresh = [d for d in docs if d["dedup_hash"] not in existing]
        duplicates += len(docs) - len(fresh)
        if fresh:
            await db.ais_positions.insert_many([dict(d) for d in fresh])
            inserted = len(fresh)
    summary = {"batch_id": source_batch_id, "received": len(positions), "inserted": inserted, "duplicates": duplicates,
               "rejected": rejected, "flagged": flagged, "vessels": len({d["mmsi"] for d in docs})}
    await audit("ais_batch", source_batch_id or "adhoc", "ais.ingested", summary, actor)
    return summary


async def mock_detect(scene, actor="system"):
    """Deterministic mock SAR detector: replaceable ML module placeholder."""
    fp = shape(scene["footprint"])
    c = fp.centroid
    rng = random.Random(scene["id"])
    lat = c.y + rng.uniform(-0.03, 0.03)
    lon = c.x + rng.uniform(-0.05, 0.05)
    bearing = rng.uniform(0, 180)
    geom = rotated_rect_polygon(lat, lon, bearing, rng.uniform(3, 8), rng.uniform(0.4, 1.2))
    conf = round(rng.uniform(0.55, 0.9), 2)
    flags = [] if conf > 0.65 else ["lookalike_suspect"]
    payload = SpillObservationCreate(
        scene_id=scene["id"], geometry=geom, acquisition_time=scene["acquisition_time"], source="mock_detector",
        detection_confidence=conf, quality_flags=flags, processing_version=MOCK_DETECTOR_VERSION,
        notes="Generated by mock detector — replace with validated SAR segmentation model",
    )
    spill, case = await create_spill_observation(payload, actor)
    await db.scenes.update_one({"id": scene["id"]}, {"$set": {"status": "detected", "detector_version": MOCK_DETECTOR_VERSION}})
    return spill, case


@handler("correlate")
async def handle_correlate(job):
    case_id = job["payload"]["case_id"]
    params = CorrelationParams(**job["payload"].get("params") or {})
    case = await db.cases.find_one({"id": case_id}, {"_id": 0})
    if not case:
        raise ValueError("case not found")
    spill = await db.spill_observations.find_one({"id": case["spill_observation_id"]}, {"_id": 0})
    spill["acquisition_time"] = to_utc(spill["acquisition_time"])
    t0 = spill["acquisition_time"]
    radius_km = params.corridor_km + spill.get("extent_km", 0)
    lon, lat = spill["centroid"]["coordinates"]
    await job_log(job["id"], f"querying AIS within {radius_km:.1f} km of ({lat:.4f},{lon:.4f}), {t0 - timedelta(hours=params.window_hours_before):%Y-%m-%d %H:%M} → {t0 + timedelta(hours=params.window_hours_after):%H:%M}Z")
    q = {"timestamp": {"$gte": t0 - timedelta(hours=params.window_hours_before), "$lte": t0 + timedelta(hours=params.window_hours_after)},
         "location": {"$geoWithin": {"$centerSphere": [[lon, lat], radius_km / 6371.0088]}}}
    positions = await db.ais_positions.find(q, {"_id": 0, "location": 0, "dedup_hash": 0}).sort([("timestamp", 1), ("id", 1)]).to_list(50000)
    for p in positions:
        p["timestamp"] = to_utc(p["timestamp"])
    result = run_correlation(spill, positions, params)
    last = await db.correlation_results.find_one({"case_id": case_id}, {"version": 1}, sort=[("version", -1)])
    version = (last["version"] if last else 0) + 1
    now = datetime.now(timezone.utc)
    doc = {"id": new_id(), "case_id": case_id, "version": version, "job_id": job["id"], "created_at": now, "actor": job.get("actor", "system"), **result}
    await db.correlation_results.insert_one(dict(doc))
    update = {"latest_result_version": version, "automated_status": result["overall_status"], "confidence_band": result["confidence_band"],
              "degraded": result["degraded"], "top_score": result["top_score"], "candidate_count": len(result["candidates"]),
              "status": "correlated" if case["review_state"] == "pending" else case["status"], "updated_at": now}
    if case["review_state"] != "confirmed":
        update["attribution_status"] = result["overall_status"]
    await db.cases.update_one({"id": case_id}, {"$set": update})
    await audit("case", case_id, "case.correlated", {"version": version, "algorithm_version": ALGORITHM_VERSION, "input_hash": result["input_hash"],
                                                   "overall_status": result["overall_status"], "job_id": job["id"]}, job.get("actor", "system"))
    await job_log(job["id"], f"result v{version}: {result['overall_status']} ({len(result['candidates'])} candidates, hash {result['input_hash'][:12]})")
    if result["overall_status"] == "probable" and spill["detection_confidence"] >= 0.6 and not result["severe_flags"]:
        top = result["candidates"][0]
        alert = {"id": new_id(), "case_id": case_id, "case_number": case["case_number"], "severity": "high", "acknowledged": False,
                 "message": f"High-confidence correlation: {top.get('vessel_name') or top['mmsi']} (MMSI {top['mmsi']}) score {top['score']:.2f} — requires analyst review",
                 "result_version": version, "created_at": now}
        await db.alerts.insert_one(dict(alert))
        await audit("alert", alert["id"], "alert.raised", {"case_id": case_id, "version": version}, "system")
        await job_log(job["id"], "high-confidence alert raised")
    return {"result_id": doc["id"], "version": version, "overall_status": result["overall_status"], "candidates": len(result["candidates"])}
