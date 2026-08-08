from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from ..extensions import db
from ..models import Fabrication, Produit, enregistrer_mouvement
from . import bp
from .forms import FabricationForm, FabricationModifierForm


@bp.route("/")
@permission_required("production")
def index():
    items = Fabrication.query.order_by(Fabrication.date_fabrication.desc(), Fabrication.id.desc()).limit(100).all()
    return render_template("production/index.html", items=items)


@bp.route("/nouvelle", methods=["GET", "POST"])
@permission_required("production")
def nouvelle():
    form = FabricationForm()
    form.produit_id.choices = [
        (p.id, p.name) for p in Produit.query.filter_by(is_archived=False).order_by(Produit.name)
    ]

    if form.validate_on_submit():
        produit = db.session.get(Produit, form.produit_id.data)

        fabrication = Fabrication(
            produit_id=produit.id,
            quantite=form.quantite.data,
            responsable_nom=current_user.full_name,
            date_fabrication=form.date_fabrication.data,
            numero_lot=form.numero_lot.data or None,
            ddm_dlc=form.ddm_dlc.data,
            observations=form.observations.data or None,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(fabrication)
        db.session.flush()

        enregistrer_mouvement(
            produit,
            "entree",
            "fabrication",
            form.quantite.data,
            current_user,
            commentaire=f"Fabrication #{fabrication.id}",
            reference_type="fabrication",
            reference_id=fabrication.id,
        )

        # Traçabilité alimentaire courante du produit (§5.1, §10.3) : reflète
        # le dernier lot fabriqué pour une consultation rapide sur la fiche.
        if form.numero_lot.data:
            produit.numero_lot = form.numero_lot.data
        produit.date_fabrication = form.date_fabrication.data
        if form.ddm_dlc.data:
            produit.ddm_dlc = form.ddm_dlc.data

        db.session.commit()
        flash("Fabrication enregistrée, stock mis à jour.", "info")
        return redirect(url_for("production.index"))

    return render_template("production/form.html", form=form)


@bp.route("/<int:fabrication_id>/modifier", methods=["GET", "POST"])
@permission_required("production")
def modifier(fabrication_id):
    fabrication = db.session.get(Fabrication, fabrication_id)
    if fabrication is None:
        abort(404)

    form = FabricationModifierForm(obj=fabrication)
    if form.validate_on_submit():
        fabrication.date_fabrication = form.date_fabrication.data
        fabrication.numero_lot = form.numero_lot.data or None
        fabrication.ddm_dlc = form.ddm_dlc.data
        fabrication.observations = form.observations.data or None

        # La traçabilité alimentaire courante du produit suit la dernière
        # fabrication modifiée si c'est bien la plus récente pour ce produit.
        derniere = (
            Fabrication.query.filter_by(produit_id=fabrication.produit_id)
            .order_by(Fabrication.date_fabrication.desc(), Fabrication.id.desc())
            .first()
        )
        if derniere and derniere.id == fabrication.id:
            if fabrication.numero_lot:
                fabrication.produit.numero_lot = fabrication.numero_lot
            fabrication.produit.date_fabrication = fabrication.date_fabrication
            if fabrication.ddm_dlc:
                fabrication.produit.ddm_dlc = fabrication.ddm_dlc

        db.session.commit()
        flash("Fabrication mise à jour.", "info")
        return redirect(url_for("production.index"))

    return render_template("production/modifier.html", form=form, fabrication=fabrication)
