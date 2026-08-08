from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from ..extensions import db
from ..models import (
    Categorie,
    Inventaire,
    InventaireLigne,
    MouvementStock,
    Produit,
    enregistrer_mouvement,
)
from . import bp
from .forms import AjustementForm, InventaireForm


@bp.route("/")
@permission_required("stocks")
def index():
    items = Produit.query.filter_by(is_archived=False).order_by(Produit.name).all()
    ruptures = sum(1 for p in items if p.statut_stock == "rupture")
    faibles = sum(1 for p in items if p.statut_stock == "faible")
    valeur_stock = sum((p.prix_achat or 0) * p.stock_quantite for p in items)
    return render_template(
        "stocks/index.html", items=items, ruptures=ruptures, faibles=faibles, valeur_stock=valeur_stock
    )


@bp.route("/mouvements")
@permission_required("stocks")
def mouvements():
    items = MouvementStock.query.order_by(MouvementStock.created_at.desc()).limit(200).all()
    return render_template("stocks/mouvements.html", items=items)


@bp.route("/ajustement", methods=["GET", "POST"])
@permission_required("stocks")
def ajustement():
    form = AjustementForm()
    form.produit_id.choices = [
        (p.id, p.name) for p in Produit.query.filter_by(is_archived=False).order_by(Produit.name)
    ]

    if form.validate_on_submit():
        produit = db.session.get(Produit, form.produit_id.data)
        motif = form.motif_entree.data if form.type_mouvement.data == "entree" else form.motif_sortie.data

        if form.type_mouvement.data == "sortie" and produit.stock_quantite < form.quantite.data:
            flash(f"Stock insuffisant ({produit.stock_quantite} disponible(s)).", "error")
            return render_template("stocks/ajustement.html", form=form)

        enregistrer_mouvement(
            produit,
            form.type_mouvement.data,
            motif,
            form.quantite.data,
            current_user,
            commentaire=form.commentaire.data or None,
        )
        db.session.commit()
        flash("Mouvement de stock enregistré.", "info")
        return redirect(url_for("stocks.index"))

    return render_template("stocks/ajustement.html", form=form)


@bp.route("/inventaires")
@permission_required("stocks")
def inventaires():
    items = Inventaire.query.order_by(Inventaire.created_at.desc()).all()
    return render_template("stocks/inventaires.html", items=items)


@bp.route("/inventaires/nouveau", methods=["GET", "POST"])
@permission_required("stocks")
def inventaire_nouveau():
    form = InventaireForm()
    form.categorie_id.choices = [
        (c.id, f"{c.poste.name} / {c.name}")
        for c in Categorie.query.filter_by(is_archived=False).order_by(Categorie.name)
    ]
    form.produit_id.choices = [
        (p.id, p.name) for p in Produit.query.filter_by(is_archived=False).order_by(Produit.name)
    ]

    if form.validate_on_submit():
        scope = form.type_inventaire.data
        query = Produit.query.filter_by(is_archived=False)
        categorie_id = None
        if scope == "categorie":
            categorie_id = form.categorie_id.data
            query = query.filter_by(categorie_id=categorie_id)
        elif scope == "produit":
            query = query.filter_by(id=form.produit_id.data)

        produits = query.order_by(Produit.name).all()
        if not produits:
            flash("Aucun produit dans ce périmètre.", "error")
            return render_template("stocks/inventaire_form.html", form=form)

        inventaire = Inventaire(
            type_inventaire=scope,
            categorie_id=categorie_id,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(inventaire)
        db.session.flush()

        for produit in produits:
            db.session.add(
                InventaireLigne(inventaire_id=inventaire.id, produit_id=produit.id, stock_theorique=produit.stock_quantite)
            )
        db.session.commit()
        return redirect(url_for("stocks.inventaire_detail", inventaire_id=inventaire.id))

    return render_template("stocks/inventaire_form.html", form=form)


@bp.route("/inventaires/<int:inventaire_id>", methods=["GET", "POST"])
@permission_required("stocks")
def inventaire_detail(inventaire_id):
    inventaire = db.session.get(Inventaire, inventaire_id)
    if inventaire is None:
        abort(404)

    if request.method == "POST":
        if inventaire.statut != "ouvert":
            abort(400)

        for ligne in inventaire.lignes:
            raw = request.form.get(f"reel_{ligne.id}", "").strip()
            if raw == "":
                continue
            ligne.stock_reel = int(raw)
            ecart = ligne.ecart
            if ecart:
                enregistrer_mouvement(
                    ligne.produit,
                    "entree" if ecart > 0 else "sortie",
                    "correction",
                    abs(ecart),
                    current_user,
                    commentaire=f"Inventaire #{inventaire.id}",
                    reference_type="inventaire",
                    reference_id=inventaire.id,
                )

        inventaire.statut = "cloture"
        inventaire.cloture_par_name = current_user.full_name
        from ..models.inventaire import utcnow

        inventaire.cloture_le = utcnow()
        db.session.commit()
        flash("Inventaire clôturé, écarts appliqués au stock.", "info")
        return redirect(url_for("stocks.inventaire_detail", inventaire_id=inventaire.id))

    return render_template("stocks/inventaire_detail.html", inventaire=inventaire)
