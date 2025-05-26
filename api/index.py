# hackathon/api/index.py
import sys
import os

# Add the parent directory (hackathon/) to sys.path to allow imports from app.py and core/
# This is crucial for Vercel's build environment.
# The current file's directory is /var/task/api/ when running on Vercel
# So, '..' should point to /var/task/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app # Import your create_app function

# Vercel expects the WSGI application to be named 'app' by default for Python runtimes.
app = create_app()

# If you were using a cloud database (e.g., Neon PostgreSQL) and wanted Vercel
# to attempt to create tables on the first deploy (or every deploy if you're okay with that):
# with app.app_context():
#     from core.models import db
#     try:
#         print("Attempting to create database tables if they don't exist (Cloud DB)...")
#         db.create_all()
#         print("Tables checked/created.")
#     except Exception as e:
#         print(f"Error during db.create_all() on Vercel startup: {e}")
# For bundled SQLite, this is not recommended as the FS is ephemeral.