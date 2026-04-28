import random
import string
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.auth import auth_bp
from app.models import Teacher, OTPToken
from app.utils.email_sender import send_otp_email


def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('subjects.list_subjects'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        if not email or '@' not in email:
            flash('Please enter a valid email address.', 'danger')
            return render_template('auth/login.html')

        teacher = Teacher.query.filter_by(email=email).first()
        if not teacher:
            teacher = Teacher(email=email)
            db.session.add(teacher)
            db.session.commit()

        if not teacher.is_active:
            flash('Your account has been deactivated. Please contact support.', 'danger')
            return render_template('auth/login.html')

        # Invalidate old tokens
        OTPToken.query.filter_by(teacher_id=teacher.id, used=False).update({'used': True})
        db.session.commit()

        otp = generate_otp()
        expiry_minutes = current_app.config.get('OTP_EXPIRY_MINUTES', 5)
        expires_at = datetime.utcnow() + timedelta(minutes=expiry_minutes)
        token = OTPToken(teacher_id=teacher.id, token=otp, expires_at=expires_at)
        db.session.add(token)
        db.session.commit()

        sent, error = send_otp_email(email, otp, teacher.name)

        if error == 'dev_mode':
            flash(f'[DEV MODE] Your OTP is: {otp}', 'info')
        elif sent:
            flash(f'OTP sent to {email}. Please check your inbox.', 'success')
        else:
            flash(f'Could not send email. Your OTP is: {otp}', 'warning')

        session['pending_email'] = email
        return redirect(url_for('auth.verify_otp'))

    return render_template('auth/login.html')


@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if current_user.is_authenticated:
        return redirect(url_for('subjects.list_subjects'))

    email = session.get('pending_email')
    if not email:
        flash('Please enter your email first.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()

        teacher = Teacher.query.filter_by(email=email).first()
        if not teacher:
            flash('Invalid session. Please try again.', 'danger')
            return redirect(url_for('auth.login'))

        token = OTPToken.query.filter_by(
            teacher_id=teacher.id,
            token=entered_otp,
            used=False
        ).order_by(OTPToken.created_at.desc()).first()

        if not token:
            flash('Invalid OTP. Please check and try again.', 'danger')
            return render_template('auth/verify_otp.html', email=email)

        if datetime.utcnow() > token.expires_at:
            token.used = True
            db.session.commit()
            flash('OTP has expired. Please request a new one.', 'danger')
            return redirect(url_for('auth.login'))

        token.used = True
        db.session.commit()

        login_user(teacher, remember=True)
        session.pop('pending_email', None)

        flash(f'Welcome back, {teacher.name or teacher.email}!', 'success')

        # Only allow relative (same-origin) redirects to prevent open redirect attacks
        next_page = request.args.get('next', '')
        safe_next = url_for('subjects.list_subjects')
        if next_page and next_page.startswith('/') and not next_page.startswith('//'):
            safe_next = next_page
        return redirect(safe_next)

    expiry_minutes = current_app.config.get('OTP_EXPIRY_MINUTES', 5)
    return render_template('auth/verify_otp.html', email=email, otp_expiry_minutes=expiry_minutes)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            current_user.name = name
            db.session.commit()
            flash('Profile updated successfully.', 'success')
    return render_template('auth/profile.html')
