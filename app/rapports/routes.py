from datetime import datetime, timedelta, timezone

from flask import render_template, request, send_file

from ..auth.decorators import permission_required
from ..models import CompteFinancier, MouvementStock, Produit
from . import bp
from .exports import export_achats_pdf, export_achats_xlsx, export_ventes_pdf, export_ventes_xlsx
from .services import (
    GROUPES_ACHATS,
    GROUPES_RH,
    GROUPES_VENTES,
    parser_date,
    periode_par_defaut,
    rapport_achats,
    rapport_production,
    rapport_rh,
    rapport_ventes,
)


def _bornes_utc(date_debut, date_fin):
    debut = datetime(date_debut.year, date_debut.month, date_debut.day, tzinfo=timezone.utc)
    fin = datetime(date_fin.year, date_fin.month, date_fin.day, tzinfo=timezone.utc) + timedelta(days=1)
    return debut, fin


@bp.route("/")
@permission_required("rapports")
def index():
    return render_template("rapports/index.html")


def _lire_periode():
    defaut_debut, defaut_fin = periode_par_defaut()
    date_debut = parser_date(request.args.get("debut"), defaut_debut)
    date_fin = parser_date(request.args.get("fin"), defaut_fin)
    return date_debut, date_fin


@bp.route("/ventes")
@permission_required("rapports")
def ventes():
    date_debut, date_fin = _lire_periode()
    group_by = request.args.get("group_by", "produit")
    lignes, total = rapport_ventes(date_debut, date_fin, group_by)
    return render_template(
        "rapports/ventes.html",
        lignes=lignes,
        total=total,
        date_debut=date_debut,
        date_fin=date_fin,
        group_by=group_by,
        groupes=GROUPES_VENTES,
    )


@bp.route("/ventes/export.xlsx")
@permission_required("rapports")
def ventes_export():
    date_debut, date_fin = _lire_periode()
    group_by = request.args.get("group_by", "produit")
    lignes, total = rapport_ventes(date_debut, date_fin, group_by)
    fichier = export_ventes_xlsx(lignes, total, date_debut, date_fin, group_by)
    return send_file(
        fichier,
        as_attachment=True,
        download_name=f"ventes_{date_debut}_{date_fin}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/ventes/export.pdf")
@permission_required("rapports")
def ventes_export_pdf():
    date_debut, date_fin = _lire_periode()
    group_by = request.args.get("group_by", "produit")
    lignes, total = rapport_ventes(date_debut, date_fin, group_by)
    fichier = export_ventes_pdf(lignes, total, date_debut, date_fin, group_by)
    return send_file(
        fichier, as_attachment=True, download_name=f"ventes_{date_debut}_{date_fin}.pdf", mimetype="application/pdf"
    )


@bp.route("/achats")
@permission_required("rapports")
def achats():
    date_debut, date_fin = _lire_periode()
    group_by = request.args.get("group_by", "fournisseur")
    lignes, total = rapport_achats(date_debut, date_fin, group_by)
    return render_template(
        "rapports/achats.html",
        lignes=lignes,
        total=total,
        date_debut=date_debut,
        date_fin=date_fin,
        group_by=group_by,
        groupes=GROUPES_ACHATS,
    )


@bp.route("/achats/export.xlsx")
@permission_required("rapports")
def achats_export():
    date_debut, date_fin = _lire_periode()
    group_by = request.args.get("group_by", "fournisseur")
    lignes, total = rapport_achats(date_debut, date_fin, group_by)
    fichier = export_achats_xlsx(lignes, total, date_debut, date_fin, group_by)
    return send_file(
        fichier,
        as_attachment=True,
        download_name=f"achats_{date_debut}_{date_fin}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/achats/export.pdf")
@permission_required("rapports")
def achats_export_pdf():
    date_debut, date_fin = _lire_periode()
    group_by = request.args.get("group_by", "fournisseur")
    lignes, total = rapport_achats(date_debut, date_fin, group_by)
    fichier = export_achats_pdf(lignes, total, date_debut, date_fin, group_by)
    return send_file(
        fichier, as_attachment=True, download_name=f"achats_{date_debut}_{date_fin}.pdf", mimetype="application/pdf"
    )


@bp.route("/stocks")
@permission_required("rapports")
def stocks():
    date_debut, date_fin = _lire_periode()
    debut, fin = _bornes_utc(date_debut, date_fin)
    produits = Produit.query.filter_by(is_archived=False).order_by(Produit.name).all()
    mouvements = (
        MouvementStock.query.filter(MouvementStock.created_at >= debut, MouvementStock.created_at < fin)
        .order_by(MouvementStock.created_at.desc())
        .limit(200)
        .all()
    )
    valeur_stock = sum((p.prix_achat or 0) * p.stock_quantite for p in produits)
    return render_template(
        "rapports/stocks.html",
        produits=produits,
        mouvements=mouvements,
        valeur_stock=valeur_stock,
        date_debut=date_debut,
        date_fin=date_fin,
    )


@bp.route("/comptes")
@permission_required("rapports")
def comptes():
    items = CompteFinancier.query.filter_by(is_archived=False).order_by(CompteFinancier.name).all()
    return render_template("rapports/comptes.html", items=items)


@bp.route("/production")
@permission_required("rapports")
def production():
    date_debut, date_fin = _lire_periode()
    fabrications, par_produit = rapport_production(date_debut, date_fin)
    return render_template(
        "rapports/production.html",
        fabrications=fabrications,
        par_produit=par_produit,
        date_debut=date_debut,
        date_fin=date_fin,
    )


@bp.route("/rh")
@permission_required("rapports")
def rh():
    date_debut, date_fin = _lire_periode()
    group_by = request.args.get("group_by", "salarie")
    lignes, total = rapport_rh(date_debut, date_fin, group_by)
    return render_template(
        "rapports/rh.html",
        lignes=lignes,
        total=total,
        date_debut=date_debut,
        date_fin=date_fin,
        group_by=group_by,
        groupes=GROUPES_RH,
    )
