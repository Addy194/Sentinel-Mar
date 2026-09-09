import asyncio, os
from pathlib import Path
STORAGE_MODE=os.environ.get('STORAGE_MODE','local'); LOCAL_STORAGE_DIR=Path(os.environ.get('LOCAL_STORAGE_DIR',str(Path(__file__).resolve().parents[1]/'data'/'storage')))
def _safe(path):
 p=Path(path); clean=Path(*[x for x in p.parts if x not in ('','.')]);
 if '..' in clean.parts: raise ValueError('invalid storage path')
 return LOCAL_STORAGE_DIR/clean
def init_storage(force=False): LOCAL_STORAGE_DIR.mkdir(parents=True,exist_ok=True)
def storage_available(): return STORAGE_MODE=='local'
def _put_local(path,data,content_type):
 p=_safe(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data); return {'path':path,'content_type':content_type,'bytes':len(data)}
def _get_local(path): return _safe(path).read_bytes(),'application/octet-stream'
async def put_object(path,data,content_type): return await asyncio.to_thread(_put_local,path,data,content_type)
async def get_object(path): return await asyncio.to_thread(_get_local,path)
