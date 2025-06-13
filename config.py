import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'supersecretkey')
    MONGO_URI = 'mongodb://localhost:27017/instagram_clone'
