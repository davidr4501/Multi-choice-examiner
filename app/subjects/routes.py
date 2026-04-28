from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.subjects import subjects_bp
from app.models import Subject


@subjects_bp.route('/')
@login_required
def list_subjects():
    subjects = Subject.query.filter_by(
        teacher_id=current_user.id
    ).order_by(Subject.created_at.desc()).all()
    return render_template('subjects/list.html', subjects=subjects)


@subjects_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_subject():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Subject name is required.', 'danger')
            return render_template('subjects/create.html')

        existing = Subject.query.filter_by(name=name, teacher_id=current_user.id).first()
        if existing:
            flash('A subject with that name already exists.', 'warning')
            return render_template('subjects/create.html')

        subject = Subject(name=name, teacher_id=current_user.id)
        db.session.add(subject)
        db.session.commit()
        flash(f'Subject "{name}" created successfully.', 'success')
        return redirect(url_for('subjects.list_subjects'))

    return render_template('subjects/create.html')


@subjects_bp.route('/<int:subject_id>/delete', methods=['POST'])
@login_required
def delete_subject(subject_id):
    subject = Subject.query.filter_by(
        id=subject_id, teacher_id=current_user.id
    ).first_or_404()
    db.session.delete(subject)
    db.session.commit()
    flash(f'Subject "{subject.name}" deleted.', 'info')
    return redirect(url_for('subjects.list_subjects'))
