from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import db, clean, audit
from models import REASON_CODES, ATTRIBUTION_STATUSES, SPILL_QUALITY_FLAGS, AIS_QUALITY_FLAGS, CorrelationParams
from correlation import ALGORITHM_VERSION
from services import MOCK_DETECTOR_VERSION

router = APIRouter()


@router.get("/jobs")
async def list_jobs(status: Optional[str] = None, limit: int = Query(100, le=500)):
    q = {"status": status} if status else {}
    return clean(await db.jobs.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit))


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "job not found")
    return clean(job)


@router.get("/alerts")
async def list_alerts(unacknowledged: bool = False, limit: int = Query(100, le=500)):
    q = {"acknowledged": False} if unacknowledged else {}
    return clean(await db.alerts.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit))


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, actor: str = "analyst"):
    res = await db.alerts.find_one_and_update({"id": alert_id}, {"$set": {"acknowledged": True, "acknowledged_by": actor, "acknowledged_at": datetime.now(timezone.utc)}},
                                              projection={"_id": 0}, return_document=True)
    if not res:
        raise HTTPException(404, "alert not found")
    await audit("alert", alert_id, "alert.acknowledged", {}, actor)
    return clean(res)


@router.get("/audit")
async def list_audit(entity_id: Optional[str] = None, limit: int = Query(200, le=2000)):
    q = {"entity_id": entity_id} if entity_id else {}
    return clean(await db.audit_events.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit))


@router.get("/config/defaults")
async def config_defaults():
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "mock_detector_version": MOCK_DETECTOR_VERSION,
        "correlation_params": CorrelationParams().model_dump(),
        "attribution_statuses": ATTRIBUTION_STATUSES,
        "spill_quality_flags": SPILL_QUALITY_FLAGS,
        "ais_quality_flags": AIS_QUALITY_FLAGS,
        "reason_codes": REASON_CODES,
        "drift_model": "surface drift = 3% of wind speed (downwind) + surface current; wind direction is meteorological (FROM), current is oceanographic (TOWARD)",
    }


@router.get("/stats")
async def stats():
    by_status = {s: await db.cases.count_documents({"attribution_status": s}) for s in ATTRIBUTION_STATUSES}
    return {
        "cases_total": await db.cases.count_documents({}),
        "by_attribution_status": by_status,
        "pending_review": await db.cases.count_documents({"review_state": "pending"}),
        "alerts_unacknowledged": await db.alerts.count_documents({"acknowledged": False}),
        "scenes": await db.scenes.count_documents({}),
        "spill_observations": await db.spill_observations.count_documents({}),
        "ais_positions": await db.ais_positions.estimated_document_count(),
        "jobs_running": await db.jobs.count_documents({"status": {"$in": ["queued", "running"]}}),
        "jobs_failed": await db.jobs.count_documents({"status": "failed"}),
    }
