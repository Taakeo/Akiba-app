import re
import unicodedata

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from ..extensions import db
from ..models import Profile, SubProfile
from ..models.user import PERMISSIONS_DISPONIBLES, generer_pin
from . import bp
from .backup_service import log_audit
from .forms import ProfileForm, SubProfileForm


def _slugifier_code_profil(texte):
    """Même logique que _slugifier (routes_catalogue.py) pour TypeTarif,
    dupliquée volontairement ici : deux entités indépendantes (Profile vs
    TypeTarif), pas de raison de les coupler par un import croisé pour un
    utilitaire aussi petit."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    code = re.sub(r"[^a-z0-9]+", "_", sans_accents.lower()).strip("_") or "profil"
    base = code
    suffixe = 2
    while Profile.query.filter_by(code=code).first() is not None:
        code = f"{base}_{suffixe}"
        suffixe += 1
    return code


def _permissions_soumises():
    """Lit la case "accès total" et la liste de cases individuelles
    envoyées par le formulaire de profil. L'accès total (§3 spec, réservé à
    l'Administrateur) n'est pas une simple case parmi d'autres : cochée,
    elle prime et remplace toute sélection individuelle."""
    if request.form.get("acces_total"):
        return ["*"]
    return request.form.getlist("permissions")


def _aucun_profil_naura_admin(profile_modifie, nouvelles_permissions):
    """Empêche d'enregistrer un état où plus aucun profil n'aurait accès à
    l'Administration — sinon plus personne ne pourrait revenir corriger ce
    réglage ni gérer les utilisateurs."""
    aura_admin = "*" in nouvelles_permissions or "admin" in nouvelles_permissions
    if aura_admin:
        return False
    autres_ont_admin = any(
        p.id != (profile_modifie.id if profile_modifie else None) and p.has_permission("admin")
        for p in Profile.query.all()
    )
    return not autres_ont_admin


@bp.route("/profils")
@permission_required("admin")
def profils():
    items = Profile.query.order_by(Profile.name).all()
    return render_template("admin/profils.html", items=items, permissions_disponibles=PERMISSIONS_DISPONIBLES)


@bp.route("/profils/nouveau", methods=["GET", "POST"])
@permission_required("admin")
def profil_nouveau():
    form = ProfileForm()
    if form.validate_on_submit():
        nouvelles_permissions = _permissions_soumises()
        if _aucun_profil_naura_admin(None, nouvelles_permissions):
            flash(
                "Aucun profil n'a accès à l'Administration : cochez au moins « Administration » "
                "ou « Accès total » sur ce profil ou un autre avant de continuer.",
                "error",
            )
        else:
            profile = Profile(
                code=_slugifier_code_profil(form.name.data),
                name=form.name.data,
                icon=form.icon.data or "badge",
            )
            profile.permissions = nouvelles_permissions
            db.session.add(profile)
            db.session.commit()
            log_audit(current_app, "profil_cree", profile.name, current_user)
            flash(f"Profil « {profile.name} » créé.", "info")
            return redirect(url_for("admin.profils"))

    return render_template(
        "admin/profil_form.html",
        form=form,
        profile=None,
        permissions_disponibles=PERMISSIONS_DISPONIBLES,
        permissions_actuelles=request.form.getlist("permissions") if request.method == "POST" else [],
        acces_total=bool(request.form.get("acces_total")) if request.method == "POST" else False,
    )


@bp.route("/profils/<int:profile_id>/modifier", methods=["GET", "POST"])
@permission_required("admin")
def profil_modifier(profile_id):
    profile = db.session.get(Profile, profile_id)
    if profile is None:
        abort(404)

    form = ProfileForm(obj=profile)
    if form.validate_on_submit():
        nouvelles_permissions = _permissions_soumises()
        if _aucun_profil_naura_admin(profile, nouvelles_permissions):
            flash(
                "Impossible : plus aucun profil n'aurait accès à l'Administration. "
                "Gardez « Administration » ou « Accès total » coché sur au moins un profil.",
                "error",
            )
        else:
            profile.name = form.name.data
            profile.icon = form.icon.data or "badge"
            profile.permissions = nouvelles_permissions
            db.session.commit()
            log_audit(
                current_app, "profil_modifie", f"{profile.name} — permissions : {', '.join(nouvelles_permissions)}",
                current_user,
            )
            flash(f"Profil « {profile.name} » mis à jour.", "info")
            return redirect(url_for("admin.profils"))

    permissions_actuelles = request.form.getlist("permissions") if request.method == "POST" else profile.permissions
    acces_total = (
        bool(request.form.get("acces_total")) if request.method == "POST" else "*" in profile.permissions
    )
    return render_template(
        "admin/profil_form.html",
        form=form,
        profile=profile,
        permissions_disponibles=PERMISSIONS_DISPONIBLES,
        permissions_actuelles=permissions_actuelles,
        acces_total=acces_total,
    )


@bp.route("/utilisateurs")
@permission_required("admin")
def utilisateurs():
    items = SubProfile.query.order_by(SubProfile.is_active.desc(), SubProfile.full_name).all()
    return render_template("admin/utilisateurs.html", items=items)


@bp.route("/utilisateurs/nouveau", methods=["GET", "POST"])
@permission_required("admin")
def utilisateur_nouveau():
    form = SubProfileForm()
    form.profile_id.choices = [(p.id, p.name) for p in Profile.query.order_by(Profile.name)]

    if form.validate_on_submit():
        pin = generer_pin()
        sub_profile = SubProfile(profile_id=form.profile_id.data, full_name=form.full_name.data)
        sub_profile.set_pin(pin)
        db.session.add(sub_profile)
        db.session.commit()
        # Le PIN en clair n'existe qu'ici, le temps de cette réponse : il n'est
        # jamais stocké ni journalisé, seul son hash reste en base.
        log_audit(current_app, "utilisateur_cree", f"{sub_profile.full_name} ({sub_profile.profile.name})", current_user)
        return render_template("admin/utilisateur_pin_genere.html", sub_profile=sub_profile, pin=pin)

    return render_template("admin/utilisateur_form.html", form=form)


@bp.route("/utilisateurs/<int:sub_profile_id>/suspendre", methods=["POST"])
@permission_required("admin")
def utilisateur_suspendre(sub_profile_id):
    sub_profile = db.session.get(SubProfile, sub_profile_id)
    if sub_profile is None:
        abort(404)
    sub_profile.suspend()
    db.session.commit()
    log_audit(current_app, "utilisateur_suspendu", sub_profile.full_name, current_user)
    flash(f"{sub_profile.full_name} suspendu.", "info")
    return redirect(url_for("admin.utilisateurs"))


@bp.route("/utilisateurs/<int:sub_profile_id>/reactiver", methods=["POST"])
@permission_required("admin")
def utilisateur_reactiver(sub_profile_id):
    sub_profile = db.session.get(SubProfile, sub_profile_id)
    if sub_profile is None:
        abort(404)
    sub_profile.reactivate()
    db.session.commit()
    log_audit(current_app, "utilisateur_reactive", sub_profile.full_name, current_user)
    flash(f"{sub_profile.full_name} réactivé.", "info")
    return redirect(url_for("admin.utilisateurs"))


@bp.route("/utilisateurs/<int:sub_profile_id>/pin", methods=["GET"])
@permission_required("admin")
def utilisateur_reset_pin(sub_profile_id):
    sub_profile = db.session.get(SubProfile, sub_profile_id)
    if sub_profile is None:
        abort(404)
    return render_template("admin/utilisateur_pin_confirmer.html", sub_profile=sub_profile)


@bp.route("/utilisateurs/<int:sub_profile_id>/pin/regenerer", methods=["POST"])
@permission_required("admin")
def utilisateur_regenerer_pin(sub_profile_id):
    sub_profile = db.session.get(SubProfile, sub_profile_id)
    if sub_profile is None:
        abort(404)

    pin = generer_pin()
    sub_profile.set_pin(pin)
    db.session.commit()
    log_audit(current_app, "utilisateur_pin_regenere", sub_profile.full_name, current_user)
    return render_template("admin/utilisateur_pin_genere.html", sub_profile=sub_profile, pin=pin)


@bp.route("/utilisateurs/<int:sub_profile_id>/supprimer", methods=["POST"])
@permission_required("admin")
def utilisateur_supprimer(sub_profile_id):
    sub_profile = db.session.get(SubProfile, sub_profile_id)
    if sub_profile is None:
        abort(404)
    if sub_profile.is_active:
        flash("Suspendez d'abord ce compte avant de le supprimer définitivement.", "error")
        return redirect(url_for("admin.utilisateurs"))

    # Même logique que la purge automatique (app/cli.py) : les opérations déjà
    # enregistrées par ce sous-profil sont conservées (FK nullable + nom figé
    # en texte sur chaque opération), seul l'enregistrement utilisateur
    # disparaît — jamais de blocage ici, contrairement au catalogue/RH/clients.
    nom = sub_profile.full_name
    db.session.delete(sub_profile)
    db.session.commit()
    log_audit(current_app, "utilisateur_supprime", nom, current_user)
    flash(f"{nom} supprimé définitivement.", "info")
    return redirect(url_for("admin.utilisateurs"))
