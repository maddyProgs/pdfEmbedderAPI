from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import gridfs
import io
import os

app = FastAPI()

# Enhanced CORS configuration
origins = [
    "https://currencychronicle.in",
    "http://currencychronicle.in",
    "https://www.currencychronicle.in",
    "http://www.currencychronicle.in",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"]  # Important for file downloads
)


# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["PDFDatabase"]
fs = gridfs.GridFS(db)

@app.post("/upload")
async def upload_pdf(pdf: UploadFile = File(...)):
    if not pdf.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF.")

    # Clear existing files
    for old_file in fs.find():
        fs.delete(old_file._id)

    fs.put(pdf.file, filename=pdf.filename)
    return {"message": "PDF uploaded successfully"}

@app.get("/latest-pdf")
def get_latest_pdf():
    latest = fs.find().sort("uploadDate", -1).limit(1)
    for file in latest:
        return StreamingResponse(io.BytesIO(file.read()), media_type="application/pdf")
    raise HTTPException(status_code=404, detail="No PDF found")
