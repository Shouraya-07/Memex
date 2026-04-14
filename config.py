import os
from dotenv import load_dotenv

load_dotenv()

FIREBASE_KEY = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY", "serviceAccountKey.json")
MEMORY_API_KEY = os.environ.get("MEMORY_API_KEY", "")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
EXTRACTED_TEXT_CHUNK_SIZE = int(os.environ.get("EXTRACTED_TEXT_CHUNK_SIZE", 8000))

# Optional for metadata generation.
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")

# File uploads.
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
