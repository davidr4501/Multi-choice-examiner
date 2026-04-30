import os
import uuid
import json
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.questions import questions_bp
from app.models import Subject, ExamSession, Question, Tag

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@questions_bp.route('/upload/<int:subject_id>', methods=['GET', 'POST'])
@login_required
def upload_exam(subject_id):
    subject = Subject.query.filter_by(id=subject_id, teacher_id=current_user.id).first_or_404()
    return render_template('questions/upload.html', subject=subject)

@questions_bp.route('/upload_json/<int:subject_id>', methods=['GET', 'POST'])
@login_required
def upload_json(subject_id):
    subject = Subject.query.filter_by(id=subject_id, teacher_id=current_user.id).first_or_404()

    if request.method == 'POST':
        reference_code = request.form.get('reference_code', '').strip()
        json_content = request.form.get('json_content', '').strip()

        if not reference_code or not json_content:
            flash('Both Reference Code and JSON Content are required.', 'danger')
            return render_template('questions/upload_json.html', subject=subject)

        try:
            questions_data = json.loads(json_content)
        except json.JSONDecodeError as e:
            flash(f'Invalid JSON format: {e}', 'danger')
            return render_template('questions/upload_json.html', subject=subject, json_content=json_content)

        exam_session = ExamSession(subject_id=subject.id, reference_code=reference_code)
        db.session.add(exam_session)
        db.session.commit()

        for q_data in questions_data:
            options = q_data.get('options', {})
            question = Question(
                exam_session_id=exam_session.id,
                question_number=q_data.get('question_number'),
                question_html=q_data.get('question_html', ''),
                option_a=options.get('A', ''),
                option_b=options.get('B', ''),
                option_c=options.get('C', ''),
                option_d=options.get('D', ''),
                correct_answer=q_data.get('correct_answer'),
                answers_embedded=q_data.get('answers_embedded', False)
            )
            db.session.add(question)
            db.session.flush()

            tag_names = q_data.get('tags', [])
            if tag_names:
                for tag_name in tag_names:
                    tag = Tag.query.filter_by(name=tag_name, subject_id=subject.id).first()
                    if not tag:
                        tag = Tag(name=tag_name, subject_id=subject.id)
                        db.session.add(tag)
                    question.tags.append(tag)
        
        db.session.commit()
        flash(f'{len(questions_data)} questions uploaded. Please review and save each question.', 'success')
        return redirect(url_for('questions.tag_questions', exam_session_id=exam_session.id))

    return render_template('questions/upload_json.html', subject=subject)

@questions_bp.route('/image_upload', methods=['POST'])
@login_required
def image_upload():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file provided.'}), 400

    images_folder = current_app.config['IMAGES_FOLDER']
    filename = f'img_{uuid.uuid4().hex}{os.path.splitext(file.filename)[1]}'
    file_path = os.path.join(images_folder, filename)
    file.save(file_path)

    location = f"/static/uploads/images/{filename}"
    return jsonify({'location': location})

@questions_bp.route('/get/<int:question_id>', methods=['GET'])
@login_required
def get_question_content(question_id):
    question = Question.query.get_or_404(question_id)
    if question.exam_session.subject.teacher_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify({
        'question_html': question.question_html,
        'option_a': question.option_a,
        'option_b': question.option_b,
        'option_c': question.option_c,
        'option_d': question.option_d,
        'reference_code': question.exam_session.reference_code
    })

@questions_bp.route('/save_single/<int:question_id>', methods=['POST'])
@login_required
def save_single_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.exam_session.subject.teacher_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

    data = request.get_json()
    
    question.question_html = data.get('question_html', '')
    question.option_a = data.get('option_a', '')
    question.option_b = data.get('option_b', '')
    question.option_c = data.get('option_c', '')
    question.option_d = data.get('option_d', '')
    question.correct_answer = data.get('correct_answer')
    question.answers_embedded = data.get('answers_embedded', False)
    
    tag_names = [t.strip() for t in data.get('tags', '').split(',') if t.strip()]
    question.tags.clear()
    for tag_name in tag_names:
        tag = Tag.query.filter_by(name=tag_name, subject_id=question.exam_session.subject_id).first()
        if not tag:
            tag = Tag(name=tag_name, subject_id=question.exam_session.subject_id)
            db.session.add(tag)
        question.tags.append(tag)

    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Question saved!'})

@questions_bp.route('/delete_single/<int:question_id>', methods=['DELETE'])
@login_required
def delete_single_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.exam_session.subject.teacher_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    
    db.session.delete(question)
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Question deleted!'})

@questions_bp.route('/tag/<int:exam_session_id>', methods=['GET'])
@login_required
def tag_questions(exam_session_id):
    exam_session = ExamSession.query.get_or_404(exam_session_id)
    if exam_session.subject.teacher_id != current_user.id:
        flash('You are not authorized to view this page.', 'danger')
        return redirect(url_for('subjects.list_subjects'))
        
    questions_in_session = Question.query.filter_by(exam_session_id=exam_session_id).order_by(Question.question_number).all()
    
    for q in questions_in_session:
        duplicates = Question.query.join(ExamSession).filter(
            ExamSession.subject_id == exam_session.subject_id,
            Question.question_html == q.question_html,
            Question.id != q.id
        ).all()
        
        q.is_duplicate = False
        if duplicates:
            q.is_duplicate = True
            q.duplicate_ids = [d.id for d in duplicates]

    existing_tags = Tag.query.filter_by(subject_id=exam_session.subject_id).order_by(Tag.name).all()
    
    return render_template('questions/tag.html',
                           exam_session=exam_session,
                           subject=exam_session.subject,
                           questions=questions_in_session,
                           existing_tags=existing_tags)
