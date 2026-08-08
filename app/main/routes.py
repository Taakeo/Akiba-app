from collections import OrderedDict
from datetime import datetime, timezone

from flask import render_template
from flask_login import login_required

from ..extensions import db
from ..models import Client, CompteFinancier, Inventaire, LigneVente, Produit, Vente, WidgetTableauBord
from . import bp


@bp.route("/")
@login_required
def dashboard():
    now = datetime.now(timezone.utc)
    debut_jour = now.replace(hour=0, minute=0, second=0, microsecond=0)
    debut_mois = debut_jour.replace(day=1)

    ventes_jour = Vente.query.filter(Vente.statut == "validee", Vente.created_at >= debut_jour).all()
    ca_jour = sum(v.total for v in ventes_jour)

    ca_mois = (
        db.session.query(db.func.coalesce(db.func.sum(Vente.total), 0))
        .filter(Vente.statut == "validee", Vente.created_at >= debut_mois)
        .scalar()
    )

    produits = Produit.query.filter_by(is_archived=False).all()
    ruptures = [p for p in produits if p.statut_stock == "rupture"]
    faibles = [p for p in produits if p.statut_stock == "faible"]
    valeur_stock = sum((p.prix_achat or 0) * p.stock_quantite for p in produits)

    # Un compte peut rester actif pour les transactions mais être masqué de
    # ce bloc précis (retour utilisateur du 08/08/2026 : ex. masquer Espèces
    # Euro ou BMOI sans les rendre inutilisables ailleurs) — indépendant de
    # is_archived, qui les retirerait partout.
    comptes = (
        CompteFinancier.query.filter_by(is_archived=False, visible_tableau_bord=True)
        .order_by(CompteFinancier.ordre_tableau_bord, CompteFinancier.name)
        .all()
    )
    inventaires_ouverts = Inventaire.query.filter_by(statut="ouvert").count()

    top_produits = _top_produits_du_mois(debut_mois)

    # Clients à crédit — §12 spec ("Alertes : ... crédits clients").
    clients_a_credit = (
        Client.query.filter(Client.solde_credit > 0, Client.is_archived.is_(False))
        .order_by(Client.solde_credit.desc())
        .all()
    )
    total_credits_du = sum(c.solde_credit for c in clients_a_credit)

    widgets = WidgetTableauBord.liste_ordonnee()

    return render_template(
        "main/dashboard.html",
        ca_jour=ca_jour,
        nb_ventes_jour=len(ventes_jour),
        ca_mois=ca_mois,
        ruptures=ruptures,
        faibles=faibles,
        valeur_stock=valeur_stock,
        comptes=comptes,
        inventaires_ouverts=inventaires_ouverts,
        top_produits=top_produits,
        clients_a_credit=clients_a_credit,
        total_credits_du=total_credits_du,
        widgets_ordre=[w.code for w in widgets],
        widgets_actifs={w.code: w.actif for w in widgets},
    )


def _top_produits_du_mois(debut_mois, limite=5):
    """Produits les plus vendus (en quantité) du mois en cours — §9.4/§10.2 spec."""
    lignes = (
        LigneVente.query.join(Vente)
        .filter(Vente.statut == "validee", Vente.created_at >= debut_mois)
        .all()
    )
    quantites = OrderedDict()
    for ligne in lignes:
        quantites[ligne.produit_nom] = quantites.get(ligne.produit_nom, 0) + ligne.quantite

    return sorted(quantites.items(), key=lambda item: item[1], reverse=True)[:limite]
