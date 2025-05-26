from flask import Blueprint, request, jsonify, current_app, session
from flask_login import current_user, login_required
import uuid
from datetime import datetime

from .knowledge_base import init_chroma_client, get_chroma_embedding_function, get_company_collection
from .utils import query_llm_groq 
from .models import db, ChatMessage, Company, Ticket, User, KnowledgeItem
# No Pinecone exceptions needed

chatbot_bp = Blueprint('chatbot', __name__)

MAX_CONTEXT_MESSAGES = 10

@chatbot_bp.route('/customer_chat', methods=['POST'])
@login_required
def customer_chat_endpoint():
    if current_user.role != 'customer':
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json()
    user_message = data.get('message')
    chat_session_id = data.get('session_id')

    if not user_message: return jsonify({"error": "No message provided"}), 400
    if not chat_session_id: chat_session_id = str(uuid.uuid4())

    company_id = current_user.company_id
    if not company_id: return jsonify({"error": "User not associated with a company"}), 400
    
    company = db.session.get(Company, company_id)
    if not company: 
        return jsonify({"error": "Company not configured"}), 500

    db_user_message = ChatMessage(company_id=company_id, user_id=current_user.id, session_id=chat_session_id, sender_type='customer', message_text=user_message)
    db.session.add(db_user_message)
    db.session.commit()

    relevant_docs_texts = []
    chroma_client = init_chroma_client()
    st_embedding_function = get_chroma_embedding_function()

    if chroma_client and st_embedding_function:
        collection = get_company_collection(chroma_client, company.id, st_embedding_function)
        if collection:
            try:
                # Chroma will use its configured EF (SentenceTransformer) to embed the query_texts
                results = collection.query(
                    query_texts=[user_message], # Text to be embedded by Chroma for query
                    n_results=3,
                    include=['documents', 'metadatas'] 
                )
                
                if results and results.get('documents') and results['documents'][0]:
                    # `results['documents'][0]` contains the original text that was stored and embedded
                    # `results['metadatas'][0]` contains the corresponding metadata
                    for doc_text, metadata in zip(results['documents'][0], results['metadatas'][0]):
                        title = metadata.get('title', 'N/A')
                        # The 'doc_text' is the full "Title: ... Content: ..." string we added.
                        # We can use this directly or reconstruct from metadata if preferred.
                        # For simplicity, let's use the retrieved doc_text.
                        relevant_docs_texts.append(doc_text) 
                        # Or if you want to be more precise from metadata:
                        # content = "Content not found in metadata." # Placeholder
                        # item_db_id_meta = metadata.get('item_db_id')
                        # if item_db_id_meta:
                        #     kb_item = db.session.get(KnowledgeItem, int(item_db_id_meta))
                        #     if kb_item: content = kb_item.content
                        # relevant_docs_texts.append(f"Title: {title}\nContent: {content}")

            except Exception as e:
                current_app.logger.error(f"Error querying ChromaDB for company {company.id}: {e}")
        else:
             current_app.logger.warning(f"ChromaDB collection not found for company {company.id} during customer chat.")
    else:
        current_app.logger.warning("ChromaDB client or embedding function not available for customer chat.")

    chat_history = ChatMessage.query.filter_by(session_id=chat_session_id, company_id=company_id)\
                                    .order_by(ChatMessage.timestamp.desc()).limit(MAX_CONTEXT_MESSAGES).all()
    chat_history.reverse()
    context_str = "\nPrevious conversation:\n" + "".join([f"{msg.sender_type}: {msg.message_text}\n" for msg in chat_history])

    kb_context = "\n\nRelevant information from our knowledge base:\n" + "\n---\n".join(relevant_docs_texts) if relevant_docs_texts else "\nNo specific knowledge base articles found for this query."
    
    system_prompt = f"You are a helpful customer support assistant for {company.name}. Answer based on KB and history. If unable, or customer asks for human, suggest creating a ticket."
    full_prompt = f"{context_str}\nCustomer: {user_message}\n{kb_context}\nAssistant:"
    
    bot_response_text = query_llm_groq(full_prompt, system_message=system_prompt)
    
    ticket = None 
    handoff_triggered = False
    # ... (Handoff logic from previous version - should largely work, ensure db.session.get is used for Ticket)
    if any(phrase in user_message.lower() for phrase in ["talk to human", "speak to agent", "escalate", "human help"]) or \
       any(phrase in bot_response_text.lower() for phrase in ["create a ticket", "human agent", "support ticket"]):
        
        linked_ticket_from_chat_history = ChatMessage.query.filter_by(session_id=chat_session_id, ticket_id=db.not_(None)).first()
        if linked_ticket_from_chat_history:
            ticket = db.session.get(Ticket, linked_ticket_from_chat_history.ticket_id)
            if ticket and ticket.status not in ['Closed', 'Resolved']:
                bot_response_text += f"\n\nI'll add this to your ongoing ticket (ID: {ticket.id})."
                if not db_user_message.ticket_id: 
                    db_user_message.ticket_id = ticket.id
                handoff_triggered = True
            else: 
                ticket = None 
        
        if not ticket: 
            ticket = Ticket.query.filter(
                Ticket.customer_id == current_user.id,
                Ticket.company_id == company_id,
                Ticket.status.notin_(['Closed', 'Resolved']) 
            ).order_by(Ticket.created_at.desc()).first()

            if not ticket: 
                ticket_subject = f"Chat Handoff: {user_message[:50]}"
                ticket_description = f"Chat session ID: {chat_session_id}\nInitial query: {user_message}\n"
                history_for_ticket = ""
                for msg in chat_history: 
                    history_for_ticket += f"{msg.sender_type.capitalize()} ({msg.timestamp.strftime('%H:%M:%S')}): {msg.message_text}\n"
                if db_user_message.message_text not in history_for_ticket: 
                    history_for_ticket += f"Customer ({db_user_message.timestamp.strftime('%H:%M:%S')}): {db_user_message.message_text}\n"
                ticket_description += f"\n--- Chat History ---\n{history_for_ticket}"
                categorization_prompt = f"Based on the following customer query, suggest a category (e.g., Billing, Technical Support, Product Inquiry) and priority (Low, Medium, High) for a support ticket: \"{user_message}\""
                category_suggestion = query_llm_groq(categorization_prompt, system_message="You are a ticket categorization assistant.")
                suggested_category = "General Inquiry" 
                suggested_priority = "Medium" 
                try:
                    if "category:" in category_suggestion.lower(): 
                        cat_part = category_suggestion.lower().split("category:")[1]
                        suggested_category = cat_part.split("priority:")[0].split(",")[0].strip().title()
                    if "priority:" in category_suggestion.lower(): 
                        suggested_priority = category_suggestion.lower().split("priority:")[1].strip().title()
                except Exception: pass
                ticket = Ticket(customer_id=current_user.id, company_id=company_id, subject=ticket_subject, description=ticket_description, status='Open', priority=suggested_priority, category=suggested_category, chat_history_reference=chat_session_id)
                db.session.add(ticket)
                db.session.commit() 
                ChatMessage.query.filter_by(session_id=chat_session_id).update({"ticket_id": ticket.id})
                bot_response_text += f"\n\nA support ticket (ID: {ticket.id}) has been created for you."
                handoff_triggered = True
            else: 
                bot_response_text += f"\n\nAdding this to your open ticket (ID: {ticket.id}). An agent will follow up."
                ticket.description += f"\n\n--- Additional chat from session {chat_session_id} on {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} ---\nUser: {user_message}\nBot: {bot_response_text.splitlines()[-1] if bot_response_text.count(chr(10)) > 0 else bot_response_text}"
                ChatMessage.query.filter_by(session_id=chat_session_id, ticket_id=None).update({"ticket_id": ticket.id})
                handoff_triggered = True
        
        if ticket: 
             db_user_message.ticket_id = ticket.id

    db_bot_message = ChatMessage(company_id=company_id, user_id=None, ticket_id=ticket.id if ticket else None, session_id=chat_session_id, sender_type='bot', message_text=bot_response_text)
    db.session.add(db_bot_message)
    db.session.commit()

    return jsonify({"bot_response": bot_response_text, "session_id": chat_session_id, "ticket_id": ticket.id if ticket else None, "handoff_triggered": handoff_triggered})


@chatbot_bp.route('/agent_assist', methods=['POST'])
@login_required
def agent_assist_endpoint():
    if current_user.role != 'agent': return jsonify({"error": "Access denied"}), 403

    data = request.get_json()
    current_conversation = data.get('conversation_context')
    agent_query = data.get('agent_query')
    
    if not current_conversation and not agent_query: return jsonify({"error": "No context or query"}), 400

    company_id = current_user.company_id
    company = db.session.get(Company, company_id)
    if not company: 
        return jsonify({"error": "Company not configured"}), 500

    relevant_docs_texts = []
    chroma_client = init_chroma_client()
    st_embedding_function = get_chroma_embedding_function()
    
    search_text = agent_query if agent_query else current_conversation[-200:]

    if chroma_client and st_embedding_function:
        collection = get_company_collection(chroma_client, company.id, st_embedding_function)
        if collection:
            try:
                results = collection.query(
                    query_texts=[search_text], 
                    n_results=3,
                    include=['documents', 'metadatas']
                )
                if results and results.get('documents') and results['documents'][0]:
                    for doc_text, metadata in zip(results['documents'][0], results['metadatas'][0]):
                        relevant_docs_texts.append(doc_text)
            except Exception as e:
                current_app.logger.error(f"Error querying ChromaDB for agent assist: {e}")
        else:
            current_app.logger.warning(f"ChromaDB collection not found for company {company.id} during agent assist.")
    else:
        current_app.logger.warning("ChromaDB client or embedding function not available for agent assist.")

    kb_context = "\n\nRelevant Knowledge Base Articles:\n" + "\n---\n".join(relevant_docs_texts) if relevant_docs_texts else "\nNo specific knowledge base articles found for this query."
    
    system_prompt = f"You are an AI assistant for support agents at {company.name}. Help agent with customer issues using provided conversation, agent's query, and KB articles. Be concise and provide actionable suggestions or information."
    prompt = f"Current Customer Conversation (if any):\n{current_conversation}\n\nAgent's Specific Request: {agent_query if agent_query else 'General assistance based on conversation.'}\n{kb_context}\n\nAI Copilot Suggestion:"
    
    assist_response = query_llm_groq(prompt, system_message=system_prompt, max_tokens=300)

    return jsonify({"suggestion": assist_response, "retrieved_kb_count": len(relevant_docs_texts)})
