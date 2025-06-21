from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import gridfs
import io
import os
import logging
from datetime import datetime
import time
from typing import Optional
from dotenv import load_dotenv  # Add this import

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    expose_headers=["Content-Disposition"]
)

# MongoDB connection with multiple configuration options
def get_mongo_client():
    # Try different ways to get the connection string
    MONGO_URI = (
        os.getenv("MONGO_URI") or                  # Render environment variable
        os.getenv("MONGODB_URI") or                # Common alternative name
        "mongodb://localhost:27017/PDFDatabase"    # Local fallback
    )
    
    if not MONGO_URI:
        logger.error("No MongoDB connection string found")
        raise RuntimeError("MongoDB connection string not configured")

    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
                socketTimeoutMS=10000,
                retryWrites=True,
                retryReads=True
            )
            # Test the connection
            client.admin.command('ping')
            logger.info(f"Connected to MongoDB at {MONGO_URI.split('@')[-1]}")
            return client
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed to connect to MongoDB: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            logger.error("All connection attempts failed")
            raise

try:
    client = get_mongo_client()
    db = client["PDFDatabase"]
    fs = gridfs.GridFS(db)
    logger.info("MongoDB initialized successfully")
except Exception as e:
    logger.error("Failed to initialize MongoDB connection", exc_info=True)
    # Don't crash the app - we'll handle it in the endpoints
    client = None
    fs = None

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    
    logger.info(f"Incoming request: {request.method} {request.url}")
    logger.info(f"Headers: {dict(request.headers)}")
    logger.info(f"Client: {request.client}")
    
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"Request error: {str(e)}", exc_info=True)
        raise
    
    process_time = (datetime.now() - start_time).total_seconds() * 1000
    response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
    
    logger.info(f"Response status: {response.status_code}")
    logger.info(f"Response headers: {dict(response.headers)}")
    
    return response

@app.post("/upload")
async def upload_pdf(pdf: UploadFile = File(...)):
    if not client:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        logger.info(f"Upload request received for file: {pdf.filename}")
        
        if not pdf.filename.lower().endswith(".pdf"):
            logger.warning(f"Invalid file type attempted: {pdf.filename}")
            raise HTTPException(status_code=400, detail="File must be a PDF.")

        # Log file info
        logger.info(f"Processing PDF: {pdf.filename} ({pdf.content_type})")

        # Clear existing files with logging
        deleted_count = 0
        for old_file in fs.find():
            fs.delete(old_file._id)
            deleted_count += 1
        logger.info(f"Deleted {deleted_count} old files")

        # Store new file
        file_id = fs.put(
            pdf.file,
            filename=pdf.filename,
            content_type=pdf.content_type
        )
        logger.info(f"Successfully stored PDF with ID: {file_id}")

        return {
            "message": "PDF uploaded successfully",
            "filename": pdf.filename,
            "file_id": str(file_id)
        }
        
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during upload")

@app.get("/latest-pdf")
def get_latest_pdf():
    if not client:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        logger.info("Fetching latest PDF request received")
        
        latest = fs.find().sort("uploadDate", -1).limit(1)
        file = next(latest, None)
        
        if not file:
            logger.warning("No PDF found in database")
            raise HTTPException(status_code=404, detail="No PDF found")
        
        logger.info(f"Serving PDF: {file.filename} (size: {file.length} bytes)")
        
        headers = {
            "Content-Disposition": f'inline; filename="{file.filename}"',
            "Content-Length": str(file.length),
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
        
        return StreamingResponse(
            io.BytesIO(file.read()),
            media_type="application/pdf",
            headers=headers
        )
        
    except Exception as e:
        logger.error(f"PDF retrieval failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

# Health check endpoint
@app.get("/health")
async def health_check():
    try:
        if not client:
            return {"status": "unhealthy", "database": "not connected"}
        
        # Check MongoDB connection
        client.admin.command('ping')
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error("Health check failed", exc_info=True)
        return {"status": "unhealthy", "database": "connection failed"}

# Additional endpoint for debugging CORS
@app.options("/{path:path}")
async def options_handler(path: str):
    logger.info(f"OPTIONS request for path: {path}")
    return JSONResponse(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": ", ".join(origins),
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "600"  # 10 minutes
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)