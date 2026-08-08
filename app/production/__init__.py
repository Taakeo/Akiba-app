from flask import Blueprint

bp = Blueprint("production", __name__, template_folder="../templates/production")

from . import routes  # noqa: E402,F401
