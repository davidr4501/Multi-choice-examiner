import random
from flask import render_template, redirect, url_for, flash, request, jsonify, send_file, current_app
from flask_login import login_required, current_user
from app import db
from app.tests import tests_bp
from app.models import Subject, Question, Tag, GeneratedTest, TestQuestion, QuestionTag, ExamSession


@tests_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_test():
    subjects = Subject.query.filter_by(teacher_id=current_user.id).all()

    if request.method == 'POST':
        subject_id = request.form.get('subject_id', type=int)
        title = request.form.get('title', '').strip()
        duration = request.form.get('duration_minutes', type=int)
        num_questions = request.form.get('num_questions', type=int)
        selected_tag_ids = request.form.getlist('tag_ids', type=int)

        if not all([subject_id, title, duration, num_questions]):
            flash('All fields are required.', 'danger')
            return render_template('tests/create.html', subjects=subjects)

        Subject.query.filter_by(id=subject_id, teacher_id=current_user.id).first_or_404()

        query = Question.query.join(ExamSession).filter(ExamSession.subject_id == subject_id)

        if selected_tag_ids:
            query = query.join(QuestionTag).filter(QuestionTag.tag_id.in_(selected_tag_ids))

        question_pool = query.distinct().all()

        if len(question_pool) < num_questions:
            flash(
                f'Not enough questions ({len(question_pool)} available, {num_questions} requested).',
                'warning'
            )
            tags = Tag.query.filter_by(subject_id=subject_id).all()
            return render_template('tests/create.html', subjects=subjects,
                                   selected_subject_id=subject_id, tags=tags)

        selected = random.sample(question_pool, num_questions)

        test = GeneratedTest(
            teacher_id=current_user.id,
            subject_id=subject_id,
            title=title,
            duration_minutes=duration,
            num_questions=num_questions,
            status='draft',
        )
        db.session.add(test)
        db.session.flush()

        for i, q in enumerate(selected):
            tq = TestQuestion(test_id=test.id, question_id=q.id, order_position=i + 1)
            db.session.add(tq)

        db.session.commit()
        flash('Test draft created! Review the questions below.', 'success')
        return redirect(url_for('tests.review_test', test_id=test.id))

    return render_template('tests/create.html', subjects=subjects)


@tests_bp.route('/<int:test_id>/review')
@login_required
def review_test(test_id):
    test = GeneratedTest.query.filter_by(
        id=test_id, teacher_id=current_user.id
    ).first_or_404()
    test_questions = TestQuestion.query.filter_by(
        test_id=test_id
    ).order_by(TestQuestion.order_position).all()
    return render_template('tests/review.html', test=test, test_questions=test_questions)


@tests_bp.route('/<int:test_id>/reject/<int:tq_id>', methods=['POST'])
@login_required
def reject_question(test_id, tq_id):
    test = GeneratedTest.query.filter_by(
        id=test_id, teacher_id=current_user.id
    ).first_or_404()

    if test.status == 'finalized':
        flash('Cannot modify a finalized test.', 'warning')
        return redirect(url_for('tests.review_test', test_id=test_id))

    tq = TestQuestion.query.filter_by(id=tq_id, test_id=test_id).first_or_404()
    rejected_q_id = tq.question_id

    existing_q_ids = [t.question_id for t in TestQuestion.query.filter_by(test_id=test_id).all()]

    rejected_tag_ids = [
        qt.tag_id for qt in QuestionTag.query.filter_by(question_id=rejected_q_id).all()
    ]

    replacement = None
    if rejected_tag_ids:
        candidates = Question.query.join(ExamSession).filter(
            ExamSession.subject_id == test.subject_id,
            Question.id.notin_(existing_q_ids),
        ).join(QuestionTag).filter(
            QuestionTag.tag_id.in_(rejected_tag_ids)
        ).distinct().all()
        if candidates:
            replacement = random.choice(candidates)

    if not replacement:
        candidates = Question.query.join(ExamSession).filter(
            ExamSession.subject_id == test.subject_id,
            Question.id.notin_(existing_q_ids),
        ).all()
        if candidates:
            replacement = random.choice(candidates)

    if replacement:
        tq.question_id = replacement.id
        db.session.commit()
        flash('Question replaced successfully.', 'success')
    else:
        flash('No replacement question available.', 'warning')

    return redirect(url_for('tests.review_test', test_id=test_id))


@tests_bp.route('/<int:test_id>/finalize', methods=['POST'])
@login_required
def finalize_test(test_id):
    test = GeneratedTest.query.filter_by(
        id=test_id, teacher_id=current_user.id
    ).first_or_404()
    test.status = 'finalized'
    db.session.commit()
    flash('Test finalized!', 'success')
    return redirect(url_for('tests.export_test', test_id=test_id))


@tests_bp.route('/<int:test_id>/export')
@login_required
def export_test(test_id):
    test = GeneratedTest.query.filter_by(
        id=test_id, teacher_id=current_user.id
    ).first_or_404()
    test_questions = TestQuestion.query.filter_by(
        test_id=test_id
    ).order_by(TestQuestion.order_position).all()
    return render_template('tests/export.html', test=test, test_questions=test_questions)


@tests_bp.route('/<int:test_id>/export/pdf')
@login_required
def export_pdf(test_id):
    test = GeneratedTest.query.filter_by(
        id=test_id, teacher_id=current_user.id
    ).first_or_404()
    test_questions = TestQuestion.query.filter_by(
        test_id=test_id
    ).order_by(TestQuestion.order_position).all()

    from app.utils.exporters import generate_pdf
    pdf_buffer = generate_pdf(test, test_questions)

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{test.title.replace(" ", "_")}.pdf',
    )


@tests_bp.route('/<int:test_id>/export/docx')
@login_required
def export_docx(test_id):
    test = GeneratedTest.query.filter_by(
        id=test_id, teacher_id=current_user.id
    ).first_or_404()
    test_questions = TestQuestion.query.filter_by(
        test_id=test_id
    ).order_by(TestQuestion.order_position).all()

    from app.utils.exporters import generate_docx
    docx_buffer = generate_docx(test, test_questions)

    return send_file(
        docx_buffer,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=f'{test.title.replace(" ", "_")}.docx',
    )


@tests_bp.route('/list')
@login_required
def list_tests():
    tests = GeneratedTest.query.filter_by(
        teacher_id=current_user.id
    ).order_by(GeneratedTest.created_at.desc()).all()
    return render_template('tests/list.html', tests=tests)


@tests_bp.route('/<int:test_id>/delete', methods=['POST'])
@login_required
def delete_test(test_id):
    test = GeneratedTest.query.filter_by(
        id=test_id, teacher_id=current_user.id
    ).first_or_404()
    db.session.delete(test)
    db.session.commit()
    flash('Test deleted.', 'info')
    return redirect(url_for('tests.list_tests'))


@tests_bp.route('/tags-for-subject')
@login_required
def tags_for_subject():
    subject_id = request.args.get('subject_id', type=int)
    if not subject_id:
        return jsonify([])
    subject = Subject.query.filter_by(id=subject_id, teacher_id=current_user.id).first()
    if not subject:
        return jsonify([])
    tags = Tag.query.filter_by(subject_id=subject_id).all()
    return jsonify([{'id': t.id, 'name': t.name} for t in tags])
