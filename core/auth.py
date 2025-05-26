from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from werkzeug.security import generate_password_hash
from flask_login import login_user, logout_user, login_required, current_user

from .models import db, User, Company

auth_bp = Blueprint('auth', __name__)

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=25)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    company_name = StringField('Company Name (if registering a new company)', validators=[Length(max=100)])
    # For existing company, you might have a dropdown or code, simplified for now
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is taken. Please choose a different one.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is taken. Please choose a different one.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        new_company = None
        if form.company_name.data: # Assuming first user of a company is an admin
            company_exists = Company.query.filter_by(name=form.company_name.data).first()
            if company_exists:
                flash('Company name already exists. If you belong to this company, contact its administrator.', 'danger')
                return render_template('register_company.html', form=form, title='Register') # register_company.html for company setup
            
            new_company = Company(name=form.company_name.data, pinecone_namespace=f"company_{form.company_name.data.lower().replace(' ', '_')}")
            db.session.add(new_company)
            # Important: commit here to get new_company.id if User needs it immediately
            # However, it's safer to handle this in a transaction or ensure company is committed first.
            # For simplicity, we'll assume it's handled correctly or commit in stages.
            try:
                db.session.commit() # Commit company first
                user_role = 'admin' # First user of a new company is admin
                company_id = new_company.id
            except Exception as e:
                db.session.rollback()
                flash(f'Error creating company: {e}', 'danger')
                return render_template('register_company.html', form=form, title='Register')

        else:
            # This part needs refinement: how do customers/agents register for an *existing* company?
            # Perhaps an invite system or a company code. For now, let's assume they can't self-register without a company.
            # Or, make 'customer' the default role if no company name.
            flash('Company name is required to register.', 'warning')
            return render_template('register_company.html', form=form, title='Register')

        user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password, role=user_role, company_id=company_id)
        db.session.add(user)
        try:
            db.session.commit()
            flash('Your account has been created! You are now able to log in.', 'success')
            # Potentially log them in directly: login_user(user)
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {e}. If company was new, it might also be rolled back.', 'danger')
            # If new_company was created, and user creation fails, you might want to delete new_company
            # or handle this more gracefully.
            if new_company:
                 # Attempt to delete the company if user creation fails for it
                company_to_delete = Company.query.get(new_company.id)
                if company_to_delete:
                    db.session.delete(company_to_delete)
                    db.session.commit()
            return render_template('register_company.html', form=form, title='Register')

    return render_template('register_company.html', form=form, title='Register')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            session['user_role'] = user.role # Store role in session
            session['company_id'] = user.company_id # Store company_id for context
            
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
            # Redirect based on role
            if user.role == 'admin':
                return redirect(next_page or url_for('admin_dashboard_route'))
            elif user.role == 'agent':
                return redirect(next_page or url_for('agent_dashboard_route'))
            elif user.role == 'customer':
                return redirect(next_page or url_for('customer_dashboard_route'))
            else: # Fallback, though should not happen with defined roles
                return redirect(next_page or url_for('index'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', form=form, title='Login')

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))