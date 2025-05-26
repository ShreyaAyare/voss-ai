# hackathon/app.py
from flask import Flask, render_template, redirect, url_for, flash, session
from flask_login import LoginManager, current_user, logout_user
from dotenv import load_dotenv
import os

# Assuming config.py, core.models, etc., are in the same root directory or correctly on PYTHONPATH
from config import Config
from core.models import db, User # db must be initialized before blueprints that use it
from core.auth import auth_bp
from core.knowledge_base import kb_bp
from core.chatbot import chatbot_bp
from core.ticketing import ticketing_bp

load_dotenv() # For local development

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # For Vercel, ensure instance_path and db paths are correctly resolved by Config
    # If bundling SQLite, 'instance' folder should be at the project root.
    # Config.py now uses PROJECT_ROOT to make paths absolute.

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(kb_bp, url_prefix='/kb')
    app.register_blueprint(chatbot_bp, url_prefix='/chat')
    app.register_blueprint(ticketing_bp, url_prefix='/tickets')

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            company_id_to_set = None
            if current_user.company_id:
                company_id_to_set = current_user.company_id
            # Example for a platform admin without a direct company_id in User model
            # You might have a flag like current_user.is_platform_admin
            elif current_user.role == 'admin' and not current_user.company_id: # A simple check
                company_id_to_set = "platform_admin" # Special string identifier

            session['company_id'] = company_id_to_set

            if current_user.role == 'admin':
                return redirect(url_for('admin_dashboard_route'))
            elif current_user.role == 'agent':
                return redirect(url_for('agent_dashboard_route'))
            elif current_user.role == 'customer':
                return redirect(url_for('customer_dashboard_route'))
        return redirect(url_for('auth.login'))

    @app.route('/admin_dashboard')
    def admin_dashboard_route():
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("Access denied.")
            return redirect(url_for('auth.login'))
        
        company_name_display = "Platform Super Admin" # Default for platform admin
        if current_user.company: # User is tied to a specific company
            company_name_display = current_user.company.name
        elif session.get('company_id') != "platform_admin": # Not platform admin, but no company (should not happen for admin)
             company_name_display = "Admin (Unassociated Company)"


        return render_template('admin_dashboard.html', username=current_user.username, company_name_display=company_name_display)

    @app.route('/agent_dashboard')
    def agent_dashboard_route():
        if not current_user.is_authenticated or current_user.role != 'agent':
            flash("Access denied.")
            return redirect(url_for('auth.login'))
        company_name_display = current_user.company.name if current_user.company else "Agent (No Company)"
        return render_template('agent_dashboard.html', username=current_user.username, company_name_display=company_name_display)

    @app.route('/customer_dashboard')
    def customer_dashboard_route():
        if not current_user.is_authenticated or current_user.role != 'customer':
            flash("Access denied.")
            return redirect(url_for('auth.login'))
        company_name_display = current_user.company.name if current_user.company else "Customer (No Company)"
        return render_template('customer_dashboard.html', username=current_user.username, company_name_display=company_name_display)

    @app.route('/logout')
    def logout():
        logout_user()
        session.clear()
        flash('You have been logged out.')
        return redirect(url_for('auth.login'))

    # db.create_all() should NOT be run here for Vercel + bundled SQLite.
    # It's handled in the __main__ block for local dev or one-time for cloud DBs.

    return app

# This block is for LOCAL execution only. Vercel uses api/index.py.
if __name__ == '__main__':
    app_instance = create_app() # Renamed to avoid conflict with 'app' for Vercel
    
    # Ensure instance folder exists for local SQLite
    # Config.py now defines PROJECT_ROOT which can be used.
    # For simplicity, relying on relative path from app.py for local instance folder.
    local_instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    if not os.path.exists(local_instance_path):
        print(f"Creating local instance folder at {local_instance_path}")
        os.makedirs(local_instance_path)
    
    with app_instance.app_context():
        db_uri = app_instance.config['SQLALCHEMY_DATABASE_URI']
        if db_uri.startswith('sqlite:///'):
            db_file_path = db_uri.replace('sqlite:///', '')
            # Ensure the directory for the SQLite file exists
            db_dir = os.path.dirname(db_file_path)
            if not os.path.exists(db_dir):
                print(f"Creating directory for local SQLite DB: {db_dir}")
                os.makedirs(db_dir)

            if not os.path.exists(db_file_path):
                print(f"Local SQLite database not found at {db_file_path}. Creating tables...")
                db.create_all()
                print("Tables created.")
            else:
                print(f"Local SQLite database found at {db_file_path}.")
        else:
            print(f"Using non-SQLite database: {db_uri}. Manual schema management recommended.")
            # For cloud DBs, you might run db.create_all() here once during setup
            # or use migration tools like Alembic.
            # db.create_all() # Potentially run once for cloud DB setup

    app_instance.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))