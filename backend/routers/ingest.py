from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user, require_role
from db import db, clean, to_utc
from models import SceneCreate, SpillObservationCreate, AISBatch, new_id
from services import create_scene, create_spill_observation, ingest_ais, mock_detect
from jobs import enqueue

router = APIRouter()


@router.post("/scenes", status_code=201)
async def register_scene(payload: SceneCreate, user=Depends(require_role("analyst"))):
    try:
        return clean(await create_scene(payload, user["email"]))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/scenes")
async def list_scenes(limit: int = Query(100, le=500), user=Depends(get_current_user)):
    return clean(await db.scenes.find({}, {"_id": 0}).sort("acquisition_time", -1).to_list(limit))


@router.get("/scenes/{scene_id}")
async def get_scene(scene_id: str, user=Depends(get_current_user)):
    doc = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "scene not found")
    spills = await db.spill_observations.find({"scene_id": scene_id}, {"_id": 0, "raw_input": 0}).to_list(100)
    return clean({**doc, "spill_observations": spills})


@router.post("/scenes/{scene_id}/detect", status_code=201)
async def detect_scene(scene_id: str, correlate: bool = True, user=Depends(require_role("analyst"))):
    scene = await db.scenes.find_one({"id": scene_id}, {"_id": 0})
    if not scene:
        raise HTTPException(404, "scene not found")
    scene["acquisition_time"] = to_utc(scene["acquisition_time"])
    spill, case = await mock_detect(scene, user["email"])
    job = await enqueue("correlate", {"case_id": case["id"], "params": None}, user["email"]) if correlate else None
    return clean({"spill_observation": spill, "case": case, "job": job})


@router.post("/spill-observations", status_code=201)
async def create_spill(payload: SpillObservationCreate, correlate: bool = False, user=Depends(require_role("analyst"))):
    try:
        spill, case = await create_spill_observation(payload, user["email"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    job = await enqueue("correlate", {"case_id": case["id"], "params": None}, user["email"]) if correlate else None
    return clean({"spill_observation": spill, "case": case, "job": job})


@router.get("/spill-observations")
async def list_spills(limit: int = Query(100, le=500), user=Depends(get_current_user)):
    return clean(await db.spill_observations.find({}, {"_id": 0, "raw_input": 0}).sort("acquisition_time", -1).to_list(limit))


@router.get("/spill-observations/{spill_id}")
async def get_spill(spill_id: str, user=Depends(get_current_user)):
    doc = await db.spill_observations.find_one({"id": spill_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "spill observation not found")
    return clean(doc)


@router.post("/ais/positions", status_code=201)
async def ingest_positions(batch: AISBatch, user=Depends(require_role("analyst"))):
    return await ingest_ais(batch.positions, new_id(), user["email"])


@router.get("/ais/positions")
async def query_positions(mmsi: Optional[str] = None, start: Optional[datetime] = None, end: Optional[datetime] = None,
                          limit: int = Query(1000, le=10000), user=Depends(get_current_user)):
    q = {}
    if mmsi:
        q["mmsi"] = mmsi
    if start or end:
        q["timestamp"] = {}
        if start:
            q["timestamp"]["$gte"] = to_utc(start)
        if end:
            q["timestamp"]["$lte"] = to_utc(end)
    return clean(await db.ais_positions.find(q, {"_id": 0, "location": 0, "dedup_hash": 0}).sort("timestamp", 1).to_list(limit))


@router.get("/ais/vessels")
async def list_vessels(user=Depends(get_current_user)):
    pipeline = [
        {"$sort": {"timestamp": -1}},
        {"$group": {"_id": "$mmsi", "vessel_name": {"$first": "$vessel_name"}, "imo": {"$first": "$imo"}, "vessel_type": {"$first": "$vessel_type"},
                    "fixes": {"$sum": 1}, "first_seen": {"$min": "$timestamp"}, "last_seen": {"$max": "$timestamp"},
                    "flags": {"$addToSet": "$quality_flags"}}},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.ais_positions.aggregate(pipeline).to_list(1000)
    return clean([{"mmsi": r["_id"], "vessel_name": r["vessel_name"], "imo": r["imo"], "vessel_type": r["vessel_type"], "fixes": r["fixes"],
                   "first_seen": r["first_seen"], "last_seen": r["last_seen"], "quality_flags": sorted({f for fl in r["flags"] for f in fl})} for r in rows])
