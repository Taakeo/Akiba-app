from flask import Blueprint

bp = Blueprint("rh", __name__, template_folder="../templates/rh")

from . import routes  # noqa: E402,F401
