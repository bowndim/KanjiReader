import asyncio, tempfile, traceback
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from reader import make_reader

app = FastAPI(
    title="Kanji Reader API",
    docs_url=None,               # hide Swagger in production
    redoc_url=None
)

from fastapi.responses import PlainTextResponse
import inspect, pathlib

@app.get("/debug/reader", include_in_schema=False)
def debug_reader():
    mod_path = pathlib.Path(sys.modules["reader"].__file__).resolve().parent
    attrs = [a for a in dir(reader) if a.startswith("make")]
    return PlainTextResponse(f"path  : {mod_path}\nattrs : {attrs}\n")


@app.get("/", include_in_schema=False)
def root():
    return JSONResponse({"status": "ok"})

@app.post("/generate")
async def generate(data: dict):
    tmp = tempfile.TemporaryDirectory() # auto-deleted on GC
    work = pathlib.Path(tmp.name)
    try:
        epub, pdf, html = await make_reader(out_dir=work, **data)
    except Exception as exc:
        traceback.print_exc() 
        raise HTTPException(400, str(exc))
    # single-file return (html); you may zip three files instead
    return FileResponse(html, media_type="text/html; charset=utf-8",
                        filename=html.name)
