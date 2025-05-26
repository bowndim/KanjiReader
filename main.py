import asyncio, tempfile
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse
import reader

app = FastAPI()

@app.post("/generate")
async def generate(data: dict):
    try:
        epub, pdf, html = await reader.make_reader(**data)
    except Exception as e:
        raise HTTPException(400, str(e))
    # single-file return (PDF); you may zip three files instead
    return FileResponse(pdf, media_type="application/pdf",
                        filename=pdf.name)
