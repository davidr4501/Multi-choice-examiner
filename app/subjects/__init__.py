from flask import Blueprint

subjects_bp = Blueprint('subjects', __name__, url_prefix='/subjects')

from app.subjects import routes  # noqa: E402, F401
