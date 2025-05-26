import asyncio, tempfile
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse
import reader

app = FastAPI()

from fastapi.responses import PlainTextResponse
import inspect, pathlib

@app.get("/debug/reader", include_in_schema=False)
def debug_reader():
    mod_path = pathlib.Path(reader.__file__).resolve()
    attrs = [a for a in dir(reader) if a.startswith("make")]
    return PlainTextResponse(f"path  : {mod_path}\nattrs : {attrs}\n")


@app.get("/", include_in_schema=False)
def root():
    return JSONResponse({"status": "ok"})

@app.post("/generate")
async def generate(data: dict):
    try:
        epub, pdf, html = await reader.make_reader(**data)
    except Exception as e:
        raise HTTPException(400, str(e))
    # single-file return (PDF); you may zip three files instead
    return FileResponse(pdf, media_type="application/pdf",
                        filename=pdf.name)
