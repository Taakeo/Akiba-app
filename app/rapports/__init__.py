from flask import Blueprint

bp = Blueprint("rapports", __name__, template_folder="../templates/rapports")

from . import routes  # noqa: E402,F401
