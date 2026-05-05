import os
import secrets
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(16)
    MONGO_URI = os.environ.get('MONGO_URI') or 'mongodb://localhost:27017/education_platform'
    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY') or 'AIzaSyAQvd9bhuAFHmzxnpg7xqxhA_avSoDJqnE'
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't']
