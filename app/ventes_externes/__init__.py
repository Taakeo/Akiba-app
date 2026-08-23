from flask import Blueprint

bp = Blueprint("ventes_externes", __name__, template_folder="../templates/ventes_externes")

from . import routes  # noqa: E402,F401
