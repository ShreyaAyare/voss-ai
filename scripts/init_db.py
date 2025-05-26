import sys
import os

# Add the parent directory to sys.path to allow imports from 'core'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db # Adjusted import
from core.models import User, Company # Import models
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    print("Dropping all tables...")
    db.drop_all()
    print("Creating all tables...")
    db.create_all()
    print("Database initialized.")

    # Optional: Create a default super admin or test company/users
    if not Company.query.filter_by(name="TestCorp").first():
        test_company = Company(name="TestCorp", pinecone_namespace="company_testcorp")
        db.session.add(test_company)
        db.session.commit()
        print(f"Created company: {test_company.name} with ID {test_company.id}")

        if not User.query.filter_by(username="testadmin").first():
            admin_user = User(
                username="testadmin",
                email="admin@testcorp.com",
                password_hash=generate_password_hash("password"),
                role="admin",
                company_id=test_company.id
            )
            db.session.add(admin_user)
            print(f"Created admin user: {admin_user.username}")

        if not User.query.filter_by(username="testagent").first():
            agent_user = User(
                username="testagent",
                email="agent@testcorp.com",
                password_hash=generate_password_hash("password"),
                role="agent",
                company_id=test_company.id
            )
            db.session.add(agent_user)
            print(f"Created agent user: {agent_user.username}")

        if not User.query.filter_by(username="testcustomer").first():
            customer_user = User(
                username="testcustomer",
                email="customer@testcorp.com",
                password_hash=generate_password_hash("password"),
                role="customer",
                company_id=test_company.id
            )
            db.session.add(customer_user)
            print(f"Created customer user: {customer_user.username}")
        
        db.session.commit()
        print("Default company and users created.")
    else:
        print("TestCorp already exists.")