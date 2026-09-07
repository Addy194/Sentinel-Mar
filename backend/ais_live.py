import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import websockets

from db import db
from models import AISPositionIn

logger = logging.getLogger("ais_live")
WS_URL = "wss://stream.aisstream.io/v0/stream"
DEFAULT_BBOXES = [[[50.0, -5.0], [62.0, 12.0]]]  # [[lat,lon],[lat,lon]] North Sea default

state = {"connected": False, "messages": 0, "positions": 0, "inserted": 0, "vessels": set(), "last_message_at": None, "connected_at": None, "error": None, "restarts": 0}
_task = None
_buffer: list = []


async def get_config() -> dict:
    s = await db.settings.find_one({"key": "ais_live"}, {"_id": 0}) or {}
    return {"api_key": s.get("api_key") or os.environ.get("AISSTREAM_API_KEY") or "", "enabled": s.get("enabled", False),
            "bboxes": s.get("bboxes") or DEFAULT_BBOXES, "source": "settings" if s.get("api_key") else ("env" if os.environ.get("AISSTREAM_API_KEY") else "none"),
            "updated_at": s.get("updated_at"), "updated_by": s.get("updated_by")}


def status() -> dict:
    return {**{k: v for k, v in state.items() if k != "vessels"}, "vessels": len(state["vessels"]), "running": bool(_task and not _task.done())}


def _parse_time(s):
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def _to_position(msg: dict):
    pr = (msg.get("Message") or {}).get("PositionReport")
    if not pr:
        return None
    meta = msg.get("MetaData") or {}
    hdg = pr.get("TrueHeading")
    cog = pr.get("Cog")
    return AISPositionIn(mmsi=str(pr.get("UserID") or meta.get("MMSI")), vessel_name=(meta.get("ShipName") or "").strip() or None, timestamp=_parse_time(meta.get("time_utc") or ""),
                         lat=pr["Latitude"], lon=pr["Longitude"], sog_kn=pr.get("Sog") if pr.get("Sog") is not None and pr.get("Sog") < 102.3 else None,
                         cog_deg=cog if cog is not None and cog < 360 else None, heading_deg=hdg if hdg is not None and hdg <= 511 else None, source="aisstream.io")


async def _flush():
    global _buffer
    if not _buffer:
        return
    batch, _buffer = _buffer, []
    from services import ingest_ais
    try:
        res = await ingest_ais(batch, source_batch_id=f"aisstream-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}", actor="aisstream.io")
        state["inserted"] += res["inserted"]
    except Exception as e:  # noqa: BLE001
        logger.error("aisstream flush failed: %s", e)


async def _run():
    while True:
        cfg = await get_config()
        if not cfg["enabled"] or not cfg["api_key"]:
            state["connected"] = False
            await asyncio.sleep(5)
            continue
        try:
            async with websockets.connect(WS_URL, ping_interval=20, close_timeout=5) as ws:
                await ws.send(json.dumps({"APIKey": cfg["api_key"], "BoundingBoxes": cfg["bboxes"], "FilterMessageTypes": ["PositionReport"]}))
                state.update({"connected": True, "connected_at": datetime.now(timezone.utc), "error": None})
                logger.info("aisstream connected, bboxes=%s", cfg["bboxes"])
                last_flush = asyncio.get_event_loop().time()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=10)
                        msg = json.loads(raw)
                        state["messages"] += 1
                        state["last_message_at"] = datetime.now(timezone.utc)
                        if msg.get("error"):
                            raise RuntimeError(msg["error"])
                        p = _to_position(msg)
                        if p:
                            _buffer.append(p)
                            state["positions"] += 1
                            state["vessels"].add(p.mmsi)
                    except asyncio.TimeoutError:
                        pass
                    now = asyncio.get_event_loop().time()
                    if now - last_flush >= 8 or len(_buffer) >= 500:
                        await _flush()
                        last_flush = now
                    fresh = await get_config()
                    if not fresh["enabled"] or fresh["bboxes"] != cfg["bboxes"] or fresh["api_key"] != cfg["api_key"]:
                        await _flush()
                        break
        except Exception as e:  # noqa: BLE001
            state.update({"connected": False, "error": str(e)[:300], "restarts": state["restarts"] + 1})
            logger.warning("aisstream disconnected: %s", e)
            await asyncio.sleep(10)
        finally:
            state["connected"] = False


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run())
