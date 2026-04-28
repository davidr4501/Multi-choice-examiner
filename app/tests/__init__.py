from flask import Blueprint

tests_bp = Blueprint('tests', __name__, url_prefix='/tests')

from app.tests import routes  # noqa: E402, F401
