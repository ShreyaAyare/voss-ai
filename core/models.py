from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    # pinecone_namespace was specific to Pinecone; Chroma uses collection names per company.
    # This field is not strictly needed for ChromaDB integration as implemented.
    # It can be repurposed or removed in a future refactor if not used for other multi-tenant vector store strategies.
    pinecone_namespace = db.Column(db.String(100), unique=True, nullable=False) 
    users = db.relationship('User', backref='company', lazy=True)
    knowledge_items = db.relationship('KnowledgeItem', backref='company', lazy=True)
    tickets = db.relationship('Ticket', backref='company', lazy=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'agent', 'customer'
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True) 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class KnowledgeItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    item_type = db.Column(db.String(50)) 
    title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False) 
    vector_id = db.Column(db.String(100)) # ID of the vector in ChromaDB (custom defined, e.g., "kb_ITEMID")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Open') 
    priority = db.Column(db.String(50), default='Medium') 
    category = db.Column(db.String(100)) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    chat_history_reference = db.Column(db.Text) 

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=True) 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Nullable for bot messages
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    session_id = db.Column(db.String(100), nullable=False) 
    sender_type = db.Column(db.String(20)) 
    message_text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
