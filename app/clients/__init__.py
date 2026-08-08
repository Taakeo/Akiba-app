from flask import Blueprint

bp = Blueprint("clients", __name__, template_folder="../templates/clients")

from . import routes  # noqa: E402,F401
