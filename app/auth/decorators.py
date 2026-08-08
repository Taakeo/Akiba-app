from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def permission_required(code):
    """Restreint une vue aux profils disposant du droit `code` (§3.1 spec)."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.profile.has_permission(code):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def permission_required_any(*codes):
    """Comme permission_required, mais accepte plusieurs droits possibles —
    pour une vue accessible depuis plusieurs parcours différents (ex. une
    facture consultable aussi bien depuis le PDV que depuis la fiche
    client), sans devoir exiger les deux droits à la fois."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not any(current_user.profile.has_permission(code) for code in codes):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
