from flask import Blueprint

bp = Blueprint("factures", __name__, template_folder="../templates/factures")

from . import routes  # noqa: E402,F401
