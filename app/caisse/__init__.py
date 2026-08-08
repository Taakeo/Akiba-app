from flask import Blueprint

bp = Blueprint("caisse", __name__, template_folder="../templates/caisse")

from . import routes  # noqa: E402,F401
