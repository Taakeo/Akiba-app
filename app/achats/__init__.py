from flask import Blueprint

bp = Blueprint("achats", __name__, template_folder="../templates/achats")

from . import routes  # noqa: E402,F401
