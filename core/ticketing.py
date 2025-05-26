# hackathon/core/ticketing.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField, HiddenField
from wtforms.validators import DataRequired
from datetime import datetime

from .models import db, Ticket, User, Company, ChatMessage, KnowledgeItem
from .utils import query_llm_groq
from .knowledge_base import init_chroma_client, get_chroma_embedding_function, get_company_collection

ticketing_bp = Blueprint('ticketing', __name__)

class TicketForm(FlaskForm):
    subject = StringField('Subject', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()]) # Remains required
    status = SelectField('Status', choices=[('Open', 'Open'), ('In Progress', 'In Progress'), ('Pending Customer', 'Pending Customer'), ('Resolved', 'Resolved'), ('Closed', 'Closed')])
    priority = SelectField('Priority', choices=[('Low', 'Low'), ('Medium', 'Medium'), ('High', 'High'), ('Urgent', 'Urgent')])
    category = StringField('Category')
    assignee_id = SelectField('Assign To Agent', coerce=int, choices=[])
    submit_ticket_details = SubmitField('Update Ticket Details')
    create_ticket_submit = SubmitField('Create Ticket')


class AgentTicketNoteForm(FlaskForm):
    note_content = TextAreaField('Add Note / Reply to Customer', validators=[DataRequired()])
    submit_note = SubmitField('Add Note')


def populate_agent_choices(form, company_id):
    if not hasattr(form, 'assignee_id'):
        current_app.logger.warning("Attempted to populate agent choices, but form has no 'assignee_id' field.")
        return

    agents = User.query.filter_by(company_id=company_id, role='agent').all()
    form.assignee_id.choices = [(0, 'Unassigned')] + [(agent.id, agent.username) for agent in agents]
    current_app.logger.debug(f"Populated agent choices for company {company_id}: {form.assignee_id.choices}")


@ticketing_bp.route('/')
@login_required
def list_tickets():
    company_id = current_user.company_id
    if not company_id:
        flash("User not associated with a company.", "danger")
        return redirect(url_for('index'))

    if current_user.role == 'customer':
        tickets = Ticket.query.filter_by(customer_id=current_user.id, company_id=company_id).order_by(Ticket.updated_at.desc()).all()
    elif current_user.role == 'agent':
        tickets = Ticket.query.filter(
            Ticket.company_id == company_id,
            (Ticket.agent_id == current_user.id) | (Ticket.agent_id == None),
            Ticket.status.in_(['Open', 'In Progress', 'Pending Customer'])
        ).order_by(Ticket.updated_at.desc(), Ticket.priority).all()
    elif current_user.role == 'admin':
        tickets = Ticket.query.filter_by(company_id=company_id).order_by(Ticket.updated_at.desc()).all()
    else:
        tickets = []
        flash("Invalid user role for viewing tickets.", "warning")

    return render_template('list_tickets.html', tickets=tickets, title="Support Tickets", User=User)


@ticketing_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_ticket():
    form = TicketForm()
    form.submit_ticket_details.label.text = 'Create Ticket' # For button label

    company_id = current_user.company_id
    if not company_id:
        flash("Cannot create ticket: User not associated with a company.", "danger")
        return redirect(url_for('index'))

    if current_user.role in ['agent', 'admin']:
        populate_agent_choices(form, company_id)
    else:
        if hasattr(form, 'assignee_id'): del form.assignee_id
        if hasattr(form, 'status'): del form.status
        if hasattr(form, 'priority'): del form.priority

    # Check which submit button was pressed if using different names/values
    # For now, validate_on_submit() will trigger on any submit within the form
    if form.validate_on_submit() and (request.form.get('create_ticket_submit') or request.form.get('submit_ticket_details')): # Check if either create button was clicked
        current_app.logger.info(f"Create ticket form submitted by user {current_user.id}")
        description_for_ai = form.description.data
        category_suggestion_prompt = f"Analyze the following support ticket description and suggest a Category (e.g., Billing, Technical, Feature Request, General Inquiry) and a Priority (Low, Medium, High, Urgent).\n\nDescription: \"{description_for_ai}\"\n\nRespond with 'Category: <category_name>' and 'Priority: <priority_level>' on separate lines or clearly indicated."
        ai_suggestions_text = query_llm_groq(category_suggestion_prompt, system_message="You are a ticket analysis assistant. Provide only Category and Priority.")
        current_app.logger.info(f"AI suggestions for new ticket: {ai_suggestions_text}")

        suggested_category = "General Inquiry"
        suggested_priority = "Medium"
        try:
            lines = ai_suggestions_text.lower().split('\n')
            for line in lines:
                if line.startswith("category:"):
                    suggested_category = line.split("category:")[1].strip().title()
                elif line.startswith("priority:"):
                    suggested_priority = line.split("priority:")[1].strip().title()
        except Exception as e:
            current_app.logger.error(f"Error parsing AI suggestions for ticket: {e} - Raw: {ai_suggestions_text}")

        new_ticket_data = {
            'subject': form.subject.data,
            'description': form.description.data, # Description is required and taken from form
            'customer_id': current_user.id,
            'company_id': company_id,
            'category': form.category.data if hasattr(form, 'category') and form.category.data else suggested_category,
            'priority': suggested_priority,
            'status': 'Open'
        }

        if current_user.role in ['admin', 'agent']:
            if hasattr(form, 'priority') and form.priority.data:
                new_ticket_data['priority'] = form.priority.data
            if hasattr(form, 'status') and form.status.data:
                new_ticket_data['status'] = form.status.data
            if hasattr(form, 'assignee_id') and form.assignee_id.data is not None and form.assignee_id.data != 0:
                new_ticket_data['agent_id'] = form.assignee_id.data
            else:
                new_ticket_data['agent_id'] = None

        ticket = Ticket(**new_ticket_data)
        db.session.add(ticket)
        db.session.commit()
        flash('Ticket created successfully!', 'success')
        current_app.logger.info(f"Ticket {ticket.id} created successfully.")
        return redirect(url_for('ticketing.view_ticket', ticket_id=ticket.id))
    elif request.method == 'POST' and not form.validate():
        flash('Please correct the errors in the form.', 'danger')
        for field, errors in form.errors.items():
            current_app.logger.error(f"Create Ticket Form error in field '{field}': {error}")

    return render_template('create_ticket.html', form=form, title="Create New Ticket")


@ticketing_bp.route('/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def view_ticket(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(f"Ticket with ID {ticket_id} not found.", "danger")
        current_app.logger.warning(f"Attempt to view non-existent ticket ID: {ticket_id}")
        return redirect(url_for('ticketing.list_tickets'))

    company_id_current_user = current_user.company_id
    if ticket.company_id != company_id_current_user:
        flash("Access Denied: Ticket does not belong to your company.", "danger")
        current_app.logger.warning(f"Access denied for user {current_user.id} to ticket {ticket_id} (company mismatch).")
        return redirect(url_for('ticketing.list_tickets'))
    if current_user.role == 'customer' and ticket.customer_id != current_user.id:
        flash('Access Denied: You are not authorized to view this ticket.', 'danger')
        current_app.logger.warning(f"Access denied for customer {current_user.id} to ticket {ticket_id} (not owner).")
        return redirect(url_for('ticketing.list_tickets'))

    ticket_company = db.session.get(Company, ticket.company_id)

    form = TicketForm(obj=ticket if request.method == 'GET' else None)
    if request.method == 'POST' and 'submit_ticket_details' in request.form:
        # OPTION 1 FIX: If description isn't in the submitted update form but is required, load it from the ticket.
        if 'description' not in request.form and hasattr(form, 'description'):
            form.description.data = ticket.description
            current_app.logger.debug(f"POST (update details): Description not in form, loaded from ticket: '{ticket.description[:50]}...'")


    form.submit_ticket_details.label.text = 'Update Ticket Details'
    note_form = AgentTicketNoteForm()

    if current_user.role in ['agent', 'admin']:
        populate_agent_choices(form, ticket.company_id)
        if request.method == 'GET':
            form.subject.data = ticket.subject
            form.status.data = ticket.status
            form.priority.data = ticket.priority
            form.category.data = ticket.category
            form.description.data = ticket.description # Ensure description field in form object has data
            if hasattr(form, 'assignee_id'):
                form.assignee_id.data = ticket.agent_id if ticket.agent_id is not None else 0
            current_app.logger.debug(f"GET request for ticket {ticket_id}: Populated form fields. Assignee ID: {form.assignee_id.data}")
    else: # Customer role
        if hasattr(form, 'assignee_id'): del form.assignee_id
        if hasattr(form, 'status'): del form.status
        if hasattr(form, 'priority'): del form.priority
        if hasattr(form, 'description'): del form.description # Remove description field from form if customer doesn't edit it here
        if hasattr(form, 'submit_ticket_details'): del form.submit_ticket_details

    ai_suggested_solutions = []
    if current_user.role in ['agent', 'admin'] and ticket_company:
        # ... (AI suggestion logic remains the same) ...
        chroma_client = init_chroma_client()
        st_embedding_function = get_chroma_embedding_function()
        if chroma_client and st_embedding_function:
            collection = get_company_collection(chroma_client, ticket_company.id, st_embedding_function)
            if collection:
                search_query_text = f"Subject: {ticket.subject}\nDescription: {ticket.description}"
                try:
                    results = collection.query(query_texts=[search_query_text], n_results=3, include=['documents', 'metadatas'])
                    if results and results.get('documents') and results['documents'][0]:
                        for doc_text, metadata in zip(results['documents'][0], results['metadatas'][0]):
                            ai_suggested_solutions.append({
                                "title": metadata.get('title', 'N/A'),
                                "content_snippet": doc_text[:300] + "...",
                                "id": metadata.get('item_db_id')
                            })
                except Exception as e:
                    current_app.logger.error(f"Error fetching AI suggestions from ChromaDB for ticket {ticket_id}: {e}")


    if 'submit_ticket_details' in request.form and current_user.role in ['agent', 'admin']:
        current_app.logger.info(f"Update ticket details submitted for ticket {ticket.id} by user {current_user.id}")
        current_app.logger.debug(f"Form data received for update: {request.form}")
        current_app.logger.debug(f"Form description data before validation: '{form.description.data[:50] if form.description.data else 'None'}'")

        if form.validate_on_submit():
            current_app.logger.info(f"Ticket update form validated successfully for ticket {ticket.id}.")
            ticket.subject = form.subject.data
            # ticket.description = form.description.data # DO NOT UPDATE from form if not editable in this section
            ticket.status = form.status.data
            ticket.priority = form.priority.data
            ticket.category = form.category.data

            if hasattr(form, 'assignee_id'):
                assignee_choice = form.assignee_id.data
                current_app.logger.info(f"Attempting to assign agent_id (from form.assignee_id.data): {assignee_choice} to ticket {ticket.id}")
                ticket.agent_id = assignee_choice if assignee_choice != 0 else None
                current_app.logger.info(f"Ticket {ticket.id} agent_id will be set to: {ticket.agent_id}")

            ticket.updated_at = datetime.utcnow()
            try:
                db.session.commit()
                flash('Ticket updated successfully.', 'success')
                current_app.logger.info(f"Ticket {ticket.id} successfully updated in DB. New agent_id: {ticket.agent_id}, Status: {ticket.status}")
                return redirect(url_for('ticketing.view_ticket', ticket_id=ticket.id))
            except Exception as e:
                db.session.rollback()
                flash(f'Database error updating ticket: {str(e)}', 'danger')
                current_app.logger.error(f"DB Error on commit for ticket {ticket.id} update: {e}")
        else:
            flash('Error updating ticket. Please check the form fields.', 'danger')
            current_app.logger.warning(f"Ticket update form validation failed for ticket {ticket.id}.")
            for field, errors in form.errors.items():
                for error in errors:
                    current_app.logger.error(f"Update Ticket Form error in field '{field}': {error}")
            current_app.logger.error(f"Current form.description.data on validation fail: '{form.description.data[:50] if form.description.data else 'None'}'")


    if 'submit_note' in request.form and note_form.validate_on_submit():
        # ... (note submission logic remains the same) ...
        current_app.logger.info(f"Add note submitted for ticket {ticket.id} by user {current_user.id}")
        sender_type = 'agent' if current_user.role in ['agent', 'admin'] else 'customer'
        chat_message = ChatMessage(
            ticket_id=ticket.id, user_id=current_user.id, company_id=ticket.company_id,
            session_id=f"ticket_{ticket.id}", sender_type=sender_type,
            message_text=note_form.note_content.data
        )
        db.session.add(chat_message)

        original_status = ticket.status
        if sender_type == 'agent' and ticket.status == 'Pending Customer':
            ticket.status = 'In Progress'
        elif sender_type == 'customer':
            if ticket.status == 'Resolved':
                ticket.status = 'Open'
                flash('Ticket has been re-opened.', 'info')
            elif ticket.status != 'Closed':
                ticket.status = 'Pending Customer' if ticket.agent_id else 'Open'
        
        if ticket.status != original_status:
            current_app.logger.info(f"Ticket {ticket.id} status changed from '{original_status}' to '{ticket.status}' due to new note.")

        ticket.updated_at = datetime.utcnow()
        try:
            db.session.commit()
            flash('Note added to ticket.', 'success')
            current_app.logger.info(f"Note added to ticket {ticket.id} and committed.")
            return redirect(url_for('ticketing.view_ticket', ticket_id=ticket.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Database error adding note: {str(e)}', 'danger')
            current_app.logger.error(f"DB Error on commit for ticket {ticket.id} note: {e}")

    elif 'submit_note' in request.form and not note_form.validate():
        flash('Error adding note. Content cannot be empty.', 'danger')
        current_app.logger.warning(f"Add note validation failed for ticket {ticket.id}.")


    ticket_messages = ChatMessage.query.filter_by(ticket_id=ticket.id).order_by(ChatMessage.timestamp.asc()).all()

    return render_template('view_ticket.html', ticket=ticket, form=form, note_form=note_form,
                           ticket_messages=ticket_messages, ai_suggested_solutions=ai_suggested_solutions,
                           title=f"Ticket #{ticket.id}", User=User)