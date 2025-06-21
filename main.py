import os
import io
import logging
from urllib.parse import quote_plus
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from gridfs import GridFS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to load .env file if available (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    logger.info("python-dotenv not installed, skipping .env file loading")

app = FastAPI()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://currencychronicle.in",
        "http://currencychronicle.in",
        "https://www.currencychronicle.in",
        "http://www.currencychronicle.in"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"]
)

# MongoDB Connection Setup
def get_mongo_uri():
    """Construct MongoDB URI with proper password encoding"""
    username = os.getenv("MONGO_USER", "your_username")
    password = os.getenv("MONGO_PASS", "your_password")
    cluster = os.getenv("MONGO_CLUSTER", "your_cluster.mongodb.net")
    db_name = os.getenv("MONGO_DB", "PDFDatabase")
    
    if not all([username, password, cluster]):
        raise ValueError("Missing MongoDB configuration")
    
    encoded_password = quote_plus(password)
    return f"mongodb+srv://{username}:{encoded_password}@{cluster}/{db_name}?retryWrites=true&w=majority"

def initialize_mongodb():
    """Initialize MongoDB connection with retry logic"""
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            client = MongoClient(
                get_mongo_uri(),
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
                socketTimeoutMS=10000
            )
            # Test the connection
            client.admin.command('ping')
            db = client[os.getenv("MONGO_DB", "PDFDatabase")]
            fs = GridFS(db)
            logger.info("Successfully connected to MongoDB!")
            return client, fs
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed to connect to MongoDB: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            logger.error("All connection attempts failed")
            raise

try:
    client, fs = initialize_mongodb()
except Exception as e:
    logger.error("Failed to initialize MongoDB connection", exc_info=True)
    # Don't crash the app - we'll handle it in the endpoints
    client = None
    fs = None

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    logger.info(f"Incoming request: {request.method} {request.url}")
    
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"Request error: {str(e)}", exc_info=True)
        raise
    
    process_time = (datetime.now() - start_time).total_seconds() * 1000
    response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
    return response

@app.post("/upload")
async def upload_pdf(pdf: UploadFile = File(...)):
    if not client:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        if not pdf.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="File must be a PDF")

        # Clear existing files
        for old_file in fs.find():
            fs.delete(old_file._id)

        file_id = fs.put(
            pdf.file,
            filename=pdf.filename,
            content_type=pdf.content_type
        )
        return {
            "message": "PDF uploaded successfully",
            "filename": pdf.filename,
            "file_id": str(file_id)
        }
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/latest-pdf")
async def get_latest_pdf():
    if not client:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        latest = fs.find().sort("uploadDate", -1).limit(1)
        file = next(latest, None)
        
        if not file:
            raise HTTPException(status_code=404, detail="No PDF found")
        
        headers = {
            "Content-Disposition": f'inline; filename="{file.filename}"',
            "Content-Length": str(file.length),
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        
        return StreamingResponse(
        io.BytesIO(file.read()),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename={file.filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )
    except Exception as e:
        logger.error(f"PDF retrieval failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    try:
        if not client:
            return {"status": "unhealthy", "database": "not connected"}
        client.admin.command('ping')
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error("Health check failed", exc_info=True)
        return {"status": "unhealthy", "database": "connection failed"}

@app.options("/{path:path}")
async def options_handler():
    return JSONResponse(
        status_code=200,
        headers={
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)