import os
import uuid
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.questions import questions_bp
from app.models import Subject, ExamSession, Question, Tag, QuestionTag


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


@questions_bp.route('/upload/<int:subject_id>', methods=['GET', 'POST'])
@login_required
def upload_exam(subject_id):
    subject = Subject.query.filter_by(
        id=subject_id, teacher_id=current_user.id
    ).first_or_404()

    if request.method == 'POST':
        reference_code = request.form.get('reference_code', '').strip()
        if not reference_code:
            flash('Reference code is required.', 'danger')
            return render_template('questions/upload.html', subject=subject)

        exam_file = request.files.get('exam_pdf')
        markscheme_file = request.files.get('markscheme_pdf')

        if not exam_file or not exam_file.filename or not allowed_file(exam_file.filename):
            flash('Please upload a valid exam PDF.', 'danger')
            return render_template('questions/upload.html', subject=subject)

        upload_folder = current_app.config['UPLOAD_FOLDER']

        exam_filename = f"{uuid.uuid4().hex}_{secure_filename(exam_file.filename)}"
        exam_abs_path = os.path.join(upload_folder, exam_filename)
        exam_file.save(exam_abs_path)

        markscheme_abs_path = None
        markscheme_rel_path = None
        if markscheme_file and markscheme_file.filename and allowed_file(markscheme_file.filename):
            ms_filename = f"{uuid.uuid4().hex}_{secure_filename(markscheme_file.filename)}"
            markscheme_abs_path = os.path.join(upload_folder, ms_filename)
            markscheme_file.save(markscheme_abs_path)
            markscheme_rel_path = os.path.join('uploads', ms_filename)

        exam_session = ExamSession(
            subject_id=subject_id,
            reference_code=reference_code,
            pdf_path=os.path.join('uploads', exam_filename),
            markscheme_path=markscheme_rel_path,
        )
        db.session.add(exam_session)
        db.session.commit()

        from app.utils.pdf_parser import parse_exam_pdf, parse_markscheme_pdf
        images_folder = current_app.config['IMAGES_FOLDER']

        try:
            parsed_questions = parse_exam_pdf(exam_abs_path, images_folder)
        except Exception as e:
            current_app.logger.error(f'PDF parsing error: {e}')
            flash(f'Warning: Could not parse PDF automatically: {e}', 'warning')
            parsed_questions = []

        correct_answers = {}
        if markscheme_abs_path:
            try:
                correct_answers = parse_markscheme_pdf(markscheme_abs_path)
            except Exception as e:
                current_app.logger.error(f'Mark scheme parsing error: {e}')
                flash('Warning: Could not parse mark scheme automatically.', 'warning')

        for q_data in parsed_questions:
            q_num = q_data['question_number']
            question = Question(
                exam_session_id=exam_session.id,
                question_number=q_num,
                question_text=q_data.get('question_text', ''),
                option_a=q_data.get('option_a', ''),
                option_b=q_data.get('option_b', ''),
                option_c=q_data.get('option_c', ''),
                option_d=q_data.get('option_d', ''),
                correct_answer=correct_answers.get(q_num),
                has_image=q_data.get('has_image', False),
                image_path=q_data.get('image_path'),
            )
            db.session.add(question)

        db.session.commit()

        if parsed_questions:
            flash(f'Exam uploaded! {len(parsed_questions)} questions extracted.', 'success')
        else:
            flash(
                'Exam uploaded, but no questions could be extracted automatically. '
                'This usually means the PDF is scanned/image-based, or uses an '
                'unexpected layout. You can add questions manually below.',
                'warning',
            )
        return redirect(url_for('questions.tag_questions', exam_session_id=exam_session.id))

    return render_template('questions/upload.html', subject=subject)


@questions_bp.route('/tag/<int:exam_session_id>', methods=['GET', 'POST'])
@login_required
def tag_questions(exam_session_id):
    exam_session = ExamSession.query.join(Subject).filter(
        ExamSession.id == exam_session_id,
        Subject.teacher_id == current_user.id
    ).first_or_404()

    subject = exam_session.subject
    questions = Question.query.filter_by(
        exam_session_id=exam_session_id
    ).order_by(Question.question_number).all()
    existing_tags = Tag.query.filter_by(subject_id=subject.id).all()

    if request.method == 'POST':
        for question in questions:
            tag_names_raw = request.form.get(f'tags_{question.id}', '')
            tag_names = [t.strip() for t in tag_names_raw.split(',') if t.strip()]

            q_text = request.form.get(f'qtext_{question.id}', '').strip()
            if q_text:
                question.question_text = q_text

            correct_answer = request.form.get(f'correct_{question.id}', '').strip().upper()
            if correct_answer in ('A', 'B', 'C', 'D'):
                question.correct_answer = correct_answer

            QuestionTag.query.filter_by(question_id=question.id).delete()

            for tag_name in tag_names:
                tag = Tag.query.filter_by(name=tag_name, subject_id=subject.id).first()
                if not tag:
                    tag = Tag(name=tag_name, subject_id=subject.id)
                    db.session.add(tag)
                    db.session.flush()
                qt = QuestionTag(question_id=question.id, tag_id=tag.id)
                db.session.add(qt)

        db.session.commit()
        flash('Tags saved successfully!', 'success')
        return redirect(url_for('subjects.list_subjects'))

    return render_template('questions/tag.html',
                           exam_session=exam_session,
                           subject=subject,
                           questions=questions,
                           existing_tags=existing_tags)


@questions_bp.route('/tags/autocomplete')
@login_required
def tags_autocomplete():
    subject_id = request.args.get('subject_id', type=int)
    query = request.args.get('q', '').strip()
    if not subject_id:
        return jsonify([])
    tags = Tag.query.filter(
        Tag.subject_id == subject_id,
        Tag.name.ilike(f'%{query}%')
    ).all()
    return jsonify([{'id': t.id, 'name': t.name} for t in tags])


@questions_bp.route('/question/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_question(question_id):
    question = Question.query.join(ExamSession).join(Subject).filter(
        Question.id == question_id,
        Subject.teacher_id == current_user.id
    ).first_or_404()

    if request.method == 'POST':
        question.question_text = request.form.get('question_text', '').strip()
        question.option_a = request.form.get('option_a', '').strip()
        question.option_b = request.form.get('option_b', '').strip()
        question.option_c = request.form.get('option_c', '').strip()
        question.option_d = request.form.get('option_d', '').strip()
        correct = request.form.get('correct_answer', '').strip().upper()
        if correct in ('A', 'B', 'C', 'D'):
            question.correct_answer = correct
        db.session.commit()
        flash('Question updated.', 'success')
        return redirect(url_for('questions.tag_questions',
                                exam_session_id=question.exam_session_id))

    return render_template('questions/edit.html', question=question)
