import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DETECTOR_VERSION = "sar-ml-pixel-1.0.0"
MODEL_NAME = "sar_spill_pixel_v1"
MODEL_CARD = Path(__file__).resolve().parent / "models" / "sar_spill_pixel_v1.json"

def model_metadata():
    try: return json.loads(MODEL_CARD.read_text())
    except Exception: return {"model": MODEL_NAME, "version": DETECTOR_VERSION, "status": "prototype"}

def detect_candidate_from_array(vv, vh=None):
    import numpy as np
    vv=np.asarray(vv,dtype=np.float32); vh=np.asarray(vh if vh is not None else vv,dtype=np.float32)
    if vv.shape != vh.shape: raise ValueError("VV and VH arrays must have identical shapes")
    finite=np.isfinite(vv)&np.isfinite(vh)
    if not finite.any(): return np.zeros(vv.shape,dtype=np.float32)
    med=float(np.nanmedian(vv[finite])); scale=float(np.nanstd(vv[finite]) or 1.0); z=(med-vv)/scale
    ratio=np.clip(np.abs(vh-vv)/(float(np.nanstd(vh[finite])) or 1.0),0,3)
    probability=1.0/(1.0+np.exp(-(z-0.25*ratio))); probability[~finite]=0.0
    return np.clip(probability,0.0,1.0).astype(np.float32)

def detect(vv,vh=None):
    probability=detect_candidate_from_array(vv,vh); threshold=0.60; mask=probability>=threshold; ys,xs=mask.nonzero()
    return {"detector_version":DETECTOR_VERSION,"model":MODEL_NAME,"model_status":model_metadata().get("status","prototype"),"candidate":bool(mask.any()),"confidence":float(probability[mask].mean()) if mask.any() else 0.0,"threshold":threshold,"pixel_count":int(mask.sum()),"bbox":[int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())] if mask.any() else None,"review_required":True,"generated_at":datetime.now(timezone.utc).isoformat()}

def _load_asset(href):
    import numpy as np
    if not href: return None
    if href.startswith(("http://","https://")): return None
    return np.load(href)

async def detect_scene(scene):
    vv=_load_asset(scene.get("vv_href") or scene.get("vv")); vh=_load_asset(scene.get("vh_href") or scene.get("vh"))
    if vv is None: return {"detector_version":DETECTOR_VERSION,"model":MODEL_NAME,"model_status":"prototype","candidate":False,"confidence":0.0,"review_required":True,"status":"no_local_sar_asset"}
    return detect(vv,vh)
