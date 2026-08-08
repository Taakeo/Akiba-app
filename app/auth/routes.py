from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import Profile, SubProfile
from . import bp
from .forms import PinForm


@bp.route("/")
def select_profile():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    profiles = Profile.query.order_by(Profile.id).all()
    return render_template("auth/select_profile.html", profiles=profiles)


@bp.route("/profil/<int:profile_id>")
def select_user(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        abort(404)
    sub_profiles = [sp for sp in profile.sub_profiles if sp.is_active]
    return render_template("auth/select_user.html", profile=profile, sub_profiles=sub_profiles)


@bp.route("/profil/<int:profile_id>/utilisateur/<int:sub_profile_id>", methods=["GET", "POST"])
def enter_pin(profile_id, sub_profile_id):
    sub_profile = db.session.get(SubProfile, sub_profile_id)
    if sub_profile is None or sub_profile.profile_id != profile_id or not sub_profile.is_active:
        abort(404)

    form = PinForm()
    error = None
    if form.validate_on_submit():
        if sub_profile.check_pin(form.pin.data):
            login_user(sub_profile, remember=False)
            return redirect(url_for("main.dashboard"))
        error = "Code PIN incorrect."

    return render_template(
        "auth/enter_pin.html", profile=sub_profile.profile, sub_profile=sub_profile, form=form, error=error
    )


@bp.route("/deconnexion", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("auth.select_profile"))
