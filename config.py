# hackathon/config.py
import os

# Determine the absolute path to the project's root directory.
# This assumes config.py is at the project root.
# On Vercel, __file__ will be /var/task/config.py, so dirname is /var/task/
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
# If api/index.py imports this, and PROJECT_ROOT is based on config.py's location,
# paths like os.path.join(PROJECT_ROOT, 'instance/app.db') should correctly point
# to /var/task/instance/app.db if 'instance' is at the root of your deployment.

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a-very-strong-secret-key-for-dev-and-vercel'

    # --- Database Configuration ---
    # For Vercel "Option D: Bundling SQLite"
    # This path will be relative to PROJECT_ROOT.
    # If PROJECT_ROOT is /var/task (Vercel's usual root for your code),
    # and 'instance' folder is at /var/task/instance, this works.
    SQLITE_DB_PATH = os.path.join(PROJECT_ROOT, 'instance', 'app.db')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{SQLITE_DB_PATH}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Groq Configuration
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY') # Must be set in Vercel env vars
    CHAT_MODEL_GROQ = os.environ.get('CHAT_MODEL_GROQ') or "llama3-8b-8192"

    # ChromaDB Configuration
    # For Vercel "Option D: Bundling Chroma Store"
    # This path will be relative to PROJECT_ROOT.
    CHROMA_DB_PATH = os.path.join(PROJECT_ROOT, "chroma_db_store")
    
    # Sentence Transformers Configuration
    EMBEDDING_MODEL_SENTENCE_TRANSFORMERS = os.environ.get('EMBEDDING_MODEL_SENTENCE_TRANSFORMERS') or "sentence-transformers/all-MiniLM-L6-v2"

    # Flask-Login session protection
    SESSION_COOKIE_SECURE = os.environ.get('VERCEL_ENV') == 'production' # True in Vercel production
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'

    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

    # For Flask-WTF CSRF Protection (Flask-Login also uses app.secret_key)
    WTF_CSRF_SECRET_KEY = os.environ.get('WTF_CSRF_SECRET_KEY') or 'another-secret-for-csrf'
    WTF_CSRF_ENABLED = True