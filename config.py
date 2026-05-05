import os
import secrets
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(16)
    _raw_mongo = os.environ.get('MONGO_URI', '').strip()
    if _raw_mongo and not (_raw_mongo.startswith('mongodb://') or _raw_mongo.startswith('mongodb+srv://')):
        print("WARNING: MONGO_URI is invalid. Falling back to localhost.")
        MONGO_URI = 'mongodb://localhost:27017/education_platform'
    else:
        MONGO_URI = _raw_mongo or 'mongodb://localhost:27017/education_platform'
        
    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY') or 'AIzaSyAQvd9bhuAFHmzxnpg7xqxhA_avSoDJqnE'
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't']
