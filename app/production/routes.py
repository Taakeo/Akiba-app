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


def _packaging_choices():
    return [(0, "—")] + [
        (p.id, p.name)
        for p in Produit.query.filter_by(is_archived=False, vendable_pdv=False).order_by(Produit.name)
    ]


def _packaging_par_produit():
    """{ produit_id: {"packagingId": ..., "quantite": ...} } pour préremplir en
    JS l'emballage par défaut d'un produit fini et sa quantité (ratio 1:1 par
    défaut, ajustable) au changement de produit sélectionné."""
    mapping = {}
    for p in Produit.query.filter_by(is_archived=False, vendable_pdv=True):
        if p.packaging_produit_id:
            mapping[str(p.id)] = {"packagingId": p.packaging_produit_id}
    return mapping


@bp.route("/nouvelle", methods=["GET", "POST"])
@permission_required("production")
def nouvelle():
    form = FabricationForm()
    form.produit_id.choices = [
        (p.id, p.name) for p in Produit.query.filter_by(is_archived=False, vendable_pdv=True).order_by(Produit.name)
    ]
    form.packaging_produit_id.choices = _packaging_choices()

    if form.validate_on_submit():
        produit = db.session.get(Produit, form.produit_id.data)

        packaging = (
            db.session.get(Produit, form.packaging_produit_id.data)
            if form.packaging_produit_id.data
            else None
        )
        quantite_packaging = form.quantite_packaging.data or form.quantite.data if packaging else None

        fabrication = Fabrication(
            produit_id=produit.id,
            quantite=form.quantite.data,
            responsable_nom=current_user.full_name,
            date_fabrication=form.date_fabrication.data,
            numero_lot=form.numero_lot.data or None,
            ddm_dlc=form.ddm_dlc.data,
            observations=form.observations.data or None,
            packaging_produit_id=packaging.id if packaging else None,
            quantite_packaging=quantite_packaging,
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

        if packaging is not None:
            enregistrer_mouvement(
                packaging,
                "sortie",
                "fabrication",
                quantite_packaging,
                current_user,
                commentaire=f"Emballage — Fabrication #{fabrication.id}",
                reference_type="fabrication",
                reference_id=fabrication.id,
            )

        db.session.commit()
        flash("Fabrication enregistrée, stock mis à jour.", "info")

        # Notification immédiate (pas seulement l'alerte du tableau de bord) :
        # un emballage n'étant jamais vendable au PDV, sa seule vitrine est ce
        # moment précis où il vient d'être consommé.
        if packaging is not None and packaging.statut_stock in ("rupture", "faible"):
            if packaging.statut_stock == "rupture":
                flash(f"Stock d'emballage « {packaging.name} » en rupture.", "error")
            else:
                flash(
                    f"Stock d'emballage « {packaging.name} » faible ({packaging.stock_quantite} restant(s)).",
                    "error",
                )

        return redirect(url_for("production.index"))

    return render_template(
        "production/form.html", form=form, packaging_par_produit=_packaging_par_produit()
    )


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
