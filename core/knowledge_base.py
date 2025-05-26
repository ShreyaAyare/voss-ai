from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired
import chromadb
from chromadb.utils import embedding_functions

from .models import db, KnowledgeItem, Company
# No Pinecone utilities needed.

kb_bp = Blueprint('kb', __name__)

class KnowledgeItemForm(FlaskForm):
    item_type = SelectField('Item Type', choices=[
        ('faq', 'FAQ'),
        ('product_info', 'Product Information'),
        ('troubleshooting_guide', 'Troubleshooting Guide'),
        ('policy', 'Policy')
    ], validators=[DataRequired()])
    title = StringField('Title', validators=[DataRequired()])
    content = TextAreaField('Content', validators=[DataRequired()])
    submit = SubmitField('Add Knowledge Item')

# --- ChromaDB Initialization ---
def init_chroma_client():
    """Initializes and returns a ChromaDB client."""
    try:
        client = chromadb.PersistentClient(path=current_app.config['CHROMA_DB_PATH'])
        current_app.logger.info(f"ChromaDB client initialized. Path: {current_app.config['CHROMA_DB_PATH']}")
        return client
    except Exception as e:
        current_app.logger.error(f"Failed to initialize ChromaDB client: {e}")
        return None

def get_chroma_embedding_function():
    """Returns an embedding function configured for Sentence Transformers."""
    model_name = current_app.config.get('EMBEDDING_MODEL_SENTENCE_TRANSFORMERS')
    if not model_name:
        current_app.logger.error("Sentence Transformers embedding model name not configured.")
        return None
    try:
        st_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
        current_app.logger.info(f"SentenceTransformer EF initialized with model: {model_name}")
        return st_ef
    except Exception as e:
        current_app.logger.error(f"Failed to initialize SentenceTransformerEmbeddingFunction with model {model_name}: {e}")
        return None

def get_company_collection(chroma_client, company_id: int, embedding_function):
    """Gets or creates a ChromaDB collection for a specific company."""
    if not chroma_client or not company_id or not embedding_function:
        current_app.logger.error(f"Cannot get/create Chroma collection: client_exists={bool(chroma_client)}, company_id={company_id}, ef_exists={bool(embedding_function)}")
        return None
    collection_name = f"company_{company_id}_kb" # Naming convention for company's KB
    try:
        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            # metadata={"hnsw:space": "cosine"} # Optional: specify distance metric, cosine is default for ST EFs
        )
        current_app.logger.info(f"Retrieved/Created Chroma collection: {collection_name}")
        return collection
    except Exception as e:
        current_app.logger.error(f"Failed to get/create Chroma collection '{collection_name}': {e}")
        return None

@kb_bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_kb():
    if current_user.role != 'admin' or not current_user.company_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    form = KnowledgeItemForm()
    company = db.session.get(Company, current_user.company_id)
    if not company:
        flash('Company not found for your user.', 'danger')
        return redirect(url_for('index'))

    chroma_client = init_chroma_client()
    st_embedding_function = get_chroma_embedding_function()

    if form.validate_on_submit():
        if not chroma_client or not st_embedding_function:
            flash('ChromaDB service or embedding function is not available. Cannot add item.', 'danger')
        else:
            collection = get_company_collection(chroma_client, company.id, st_embedding_function)
            if not collection:
                flash(f'Could not access knowledge base collection for company {company.name}.', 'danger')
            else:
                try:
                    # The document Chroma will embed using its configured SentenceTransformer EF
                    document_to_embed = f"Title: {form.title.data}\nType: {form.item_type.data}\nContent: {form.content.data}"
                    
                    new_item = KnowledgeItem(
                        company_id=current_user.company_id,
                        item_type=form.item_type.data,
                        title=form.title.data,
                        content=form.content.data # Store raw content in SQL DB
                    )
                    db.session.add(new_item)
                    db.session.commit() # Commit to get new_item.id

                    item_id_str_for_chroma = f"kb_{new_item.id}" # Define ID for Chroma
                    
                    collection.add(
                        documents=[document_to_embed], # Chroma embeds this using its EF
                        metadatas=[{
                            "item_db_id": new_item.id, # Store SQL DB ID in metadata
                            "type": form.item_type.data,
                            "title": form.title.data,
                            "company_id": company.id # For potential verification
                        }],
                        ids=[item_id_str_for_chroma] # Use our defined ID
                    )
                    
                    new_item.vector_id = item_id_str_for_chroma # Store Chroma ID in our DB
                    db.session.commit()
                    flash('Knowledge item added and indexed in ChromaDB!', 'success')
                    return redirect(url_for('kb.manage_kb'))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Error adding knowledge item to ChromaDB: {e}")
                    flash(f'Error during ChromaDB operation: {str(e)}', 'danger')
            
    items = KnowledgeItem.query.filter_by(company_id=current_user.company_id).all()
    return render_template('manage_kb.html', form=form, items=items, title="Manage Knowledge Base")
