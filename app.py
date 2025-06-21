from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import gridfs
import io
import os

app = Flask(__name__)
CORS(app)  # Enable CORS

# MongoDB Setup
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["PDFDatabase"]
fs = gridfs.GridFS(db)

# Upload PDF Endpoint
@app.route("/upload", methods=["POST"])
def upload_pdf():
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF part in the request"}), 400

    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    # Optional: Remove previous PDFs to keep only the latest
    for old_file in fs.find():
        fs.delete(old_file._id)

    fs.put(file, filename=file.filename)
    return jsonify({"message": "PDF uploaded successfully"}), 200

# Fetch Latest PDF Endpoint
@app.route("/latest-pdf", methods=["GET"])
def get_latest_pdf():
    latest = fs.find().sort("uploadDate", -1).limit(1)
    for file in latest:
        return send_file(io.BytesIO(file.read()), mimetype="application/pdf")
    return jsonify({"error": "No PDF found"}), 404

if __name__ == "__main__":
    app.run(debug=True)
