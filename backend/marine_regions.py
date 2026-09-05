import asyncio
from datetime import datetime, timezone

import httpx
from shapely.geometry import shape, mapping, MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.validation import make_valid

from db import db, audit
from jobs import handler, job_log
from jurisdiction import apply_to_case
from models import new_id


async def _upsert_zone(existing, code, doc, now):
    if existing:
        await db.jurisdictions.update_one({"code": code}, {"$set": doc})
    else:
        await db.jurisdictions.insert_one({**doc, "id": new_id(), "created_at": now})

WFS = "https://geo.vliz.be/geoserver/MarineRegions/wfs"
AUTHORITIES = {
    "NLD": "Rijkswaterstaat / Netherlands Coastguard", "GBR": "UK Maritime & Coastguard Agency", "DEU": "Havariekommando (CCME)",
    "DNK": "Danish Defence – Maritime Assistance Service", "BEL": "Belgian FPS Mobility / MUMM", "NOR": "Norwegian Coastal Administration",
    "FRA": "Préfecture maritime / CROSS", "SWE": "Swedish Coast Guard", "IRL": "Irish Coast Guard", "ESP": "Salvamento Marítimo", "PRT": "Portuguese Navy / DGRM", "ITA": "Guardia Costiera",
}
DEFAULT_ISO3 = ["NLD", "GBR", "DEU", "DNK", "BEL", "NOR"]


async def fetch_eez(iso3: str) -> dict | None:
    params = {"service": "WFS", "version": "1.0.0", "request": "GetFeature", "typeName": "MarineRegions:eez",
              "outputFormat": "application/json", "CQL_FILTER": f"iso_ter1='{iso3}'"}
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.get(WFS, params=params)
    r.raise_for_status()
    data = r.json()
    feats = data.get("features", [])
    main = [f for f in feats if (f["properties"].get("pol_type") or "").upper() == "200NM"]
    feats = main or feats
    if not feats:
        return None
    geoms = [make_valid(shape(f["geometry"])) for f in feats]
    merged = make_valid(unary_union(geoms).simplify(0.004, preserve_topology=True))
    if merged.geom_type == "GeometryCollection":
        merged = unary_union([g for g in merged.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    merged = unary_union(merged.buffer(0))  # dissolve overlapping parts (2dsphere rejects crossing loops)
    parts = merged.geoms if merged.geom_type == "MultiPolygon" else [merged]
    merged = MultiPolygon([Polygon(p.exterior) for p in parts if p.area > 1e-6])  # drop island holes: land is irrelevant for spill jurisdiction
    if merged.geom_type == "Polygon":
        merged = MultiPolygon([merged])
    props = feats[0]["properties"]
    vertices = sum(len(ring.coords) for poly in merged.geoms for ring in [poly.exterior, *poly.interiors])
    return {"geometry": mapping(merged), "geoname": props.get("geoname"), "mrgid": props.get("mrgid"), "territory": props.get("territory1"),
            "sovereign": props.get("sovereign1"), "pol_type": props.get("pol_type"), "area_km2": props.get("area_km2"),
            "features": len(feats), "vertices": vertices}


@handler("import_eez")
async def handle_import_eez(job):
    iso_list = [s.strip().upper() for s in job["payload"].get("iso3", DEFAULT_ISO3) if s.strip()]
    replace_demo = job["payload"].get("replace_demo", True)
    actor = job.get("actor", "system")
    now = datetime.now(timezone.utc)
    imported, failed = [], []
    for iso in iso_list:
        await job_log(job["id"], f"fetching Marine Regions EEZ for {iso} …")
        try:
            rec = await fetch_eez(iso)
        except Exception as e:  # noqa: BLE001
            failed.append({"iso3": iso, "error": str(e)[:200]})
            await job_log(job["id"], f"{iso}: fetch failed — {e}", "error")
            continue
        if not rec:
            failed.append({"iso3": iso, "error": "no EEZ feature returned"})
            await job_log(job["id"], f"{iso}: no feature", "warn")
            continue
        code = f"{iso}-EEZ"
        doc = {"code": code, "name": rec["geoname"] or f"{iso} Exclusive Economic Zone", "authority": AUTHORITIES.get(iso, f"{rec['sovereign'] or iso} maritime authority"),
               "country": iso, "zone_type": "eez", "geometry": rec["geometry"], "active": True,
               "source": "Marine Regions Maritime Boundaries v12 — EEZ (200NM), geo.vliz.be WFS, simplified 0.004°", "official": True,
               "mrgid": rec["mrgid"], "pol_type": rec["pol_type"], "area_km2": rec["area_km2"], "imported_at": now, "updated_at": now}
        existing = await db.jurisdictions.find_one({"code": code})
        try:
            await _upsert_zone(existing, code, doc, now)
        except Exception as e:  # noqa: BLE001
            await job_log(job["id"], f"{iso}: geometry rejected by geospatial index, retrying with repaired orientation", "warn")
            try:
                g = orient(make_valid(shape(rec["geometry"]).buffer(0)), sign=1.0)
                doc["geometry"] = mapping(g if g.geom_type == "MultiPolygon" else MultiPolygon([g]))
                await _upsert_zone(existing, code, doc, now)
            except Exception as e2:  # noqa: BLE001
                failed.append({"iso3": iso, "error": f"geometry not indexable: {str(e2)[:120]}"})
                await job_log(job["id"], f"{iso}: skipped — {str(e2)[:100]}", "error")
                continue
        zid = (existing or await db.jurisdictions.find_one({"code": code}))["id"]
        await audit("jurisdiction", zid, "jurisdiction.imported", {"code": code, "mrgid": rec["mrgid"], "vertices": rec["vertices"]}, actor)
        imported.append({"iso3": iso, "code": code, "name": doc["name"], "vertices": rec["vertices"], "area_km2": rec["area_km2"]})
        await job_log(job["id"], f"{iso}: imported {doc['name']} ({rec['vertices']} vertices, {rec['area_km2']} km²)")
        await asyncio.sleep(0.3)
    if replace_demo and imported:
        res = await db.jurisdictions.update_many({"source": {"$regex": "^demo-seed"}, "zone_type": "eez"}, {"$set": {"active": False, "updated_at": now}})
        await job_log(job["id"], f"deactivated {res.modified_count} demo EEZ polygons")
    ids = [c["id"] async for c in db.cases.find({}, {"id": 1})]
    for cid in ids:
        await apply_to_case(cid, actor)
    await job_log(job["id"], f"re-resolved jurisdiction for {len(ids)} cases")
    return {"imported": imported, "failed": failed, "cases_resolved": len(ids)}
