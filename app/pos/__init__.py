from flask import Blueprint

bp = Blueprint("pos", __name__, template_folder="../templates/pos")

from . import routes  # noqa: E402,F401
