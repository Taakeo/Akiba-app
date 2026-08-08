from flask import Blueprint

bp = Blueprint("admin", __name__, template_folder="../templates/admin")

from . import routes_backup, routes_catalogue, routes_journal, routes_users  # noqa: E402,F401
