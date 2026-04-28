from datetime import datetime
from flask_login import UserMixin
from app import db, login_manager


class Teacher(UserMixin, db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    subjects = db.relationship('Subject', backref='teacher', lazy='dynamic')
    generated_tests = db.relationship('GeneratedTest', backref='teacher', lazy='dynamic')
    otp_tokens = db.relationship('OTPToken', backref='teacher', lazy='dynamic')

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    return Teacher.query.get(int(user_id))


class OTPToken(db.Model):
    __tablename__ = 'otp_tokens'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    token = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    exam_sessions = db.relationship('ExamSession', backref='subject', lazy='dynamic')
    tags = db.relationship('Tag', backref='subject', lazy='dynamic')
    generated_tests = db.relationship('GeneratedTest', backref='subject', lazy='dynamic')


class ExamSession(db.Model):
    __tablename__ = 'exam_sessions'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    reference_code = db.Column(db.String(100), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(500))
    markscheme_path = db.Column(db.String(500))

    questions = db.relationship('Question', backref='exam_session', lazy='dynamic',
                                cascade='all, delete-orphan')


class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    exam_session_id = db.Column(db.Integer, db.ForeignKey('exam_sessions.id'), nullable=False)
    question_number = db.Column(db.Integer, nullable=False)
    question_text = db.Column(db.Text)
    option_a = db.Column(db.Text)
    option_b = db.Column(db.Text)
    option_c = db.Column(db.Text)
    option_d = db.Column(db.Text)
    correct_answer = db.Column(db.String(1))
    has_image = db.Column(db.Boolean, default=False)
    image_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tags = db.relationship('Tag', secondary='question_tags',
                           backref=db.backref('questions', lazy='dynamic'))
    test_questions = db.relationship('TestQuestion', backref='question', lazy='dynamic')


class Tag(db.Model):
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('name', 'subject_id', name='uq_tag_name_subject'),)


class QuestionTag(db.Model):
    __tablename__ = 'question_tags'
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), primary_key=True)


class GeneratedTest(db.Model):
    __tablename__ = 'generated_tests'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    num_questions = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='draft')

    test_questions = db.relationship('TestQuestion', backref='test', lazy='dynamic',
                                     cascade='all, delete-orphan',
                                     order_by='TestQuestion.order_position')


class TestQuestion(db.Model):
    __tablename__ = 'test_questions'
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('generated_tests.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    order_position = db.Column(db.Integer, nullable=False)
