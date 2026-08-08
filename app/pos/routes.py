from flask import abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from ..caisse.services import calculer_theorique, get_open_session
from ..extensions import db
from ..models import Categorie, Client, MoyenPaiement, Poste, Produit, TauxChange, TicketAttente, TypeTarif, Vente
from . import bp
from .services import VenteError, enregistrer_vente


@bp.route("/")
@permission_required("point_de_vente")
def index():
    session = get_open_session()
    if session is None:
        return redirect(url_for("caisse.ouverture"))

    # Tous les postes actifs sont vendables au PDV (choix explicite de
    # l'association : la Boutique/Atelier n'est pas le seul pôle à
    # encaisser). À gauche l'écran affiche les postes, en haut les catégories
    # se filtrent selon le poste sélectionné (§4.3, §6.3 spec).
    postes = Poste.query.filter_by(is_archived=False).order_by(Poste.name).all()
    categories = (
        Categorie.query.filter_by(is_archived=False).order_by(Categorie.poste_id, Categorie.ordre, Categorie.name).all()
    )
    produits = (
        Produit.query.filter_by(is_archived=False)
        .order_by(Produit.name)
        .all()
    )
    type_tarifs = TypeTarif.query.filter_by(is_archived=False).order_by(TypeTarif.ordre).all()
    # Un moyen rattaché au Compte Akiba (pas au tiroir PDV) n'a rien à faire
    # ici : un client ne paie jamais "dans" le compte Akiba directement,
    # seul le tiroir physique reçoit ses paiements (retour utilisateur du
    # 08/08/2026).
    moyens_paiement = (
        MoyenPaiement.query.filter_by(is_archived=False, visible_pdv=True).order_by(MoyenPaiement.name).all()
    )
    clients = Client.query.filter_by(is_archived=False).order_by(Client.nom).all()

    # Dernières ventes de la session, affichées au PDV pour éviter une double
    # saisie (ex. après une hésitation ou un rafraîchissement de page) — §1.6 CDC v1.
    dernieres_ventes = (
        Vente.query.filter_by(caisse_session_id=session.id, statut="validee")
        .order_by(Vente.id.desc())
        .limit(5)
        .all()
    )

    def _prix_disponibles(produit):
        # prix_pour() gère déjà la priorité prix manuel > rabais en % calculé
        # sur le prix de référence (arrondi à la centaine supérieure) — on
        # l'utilise ici pour que le PDV propose bien tous les tarifs vraiment
        # disponibles, pas seulement ceux saisis à la main sur la fiche produit.
        prix = {}
        for tt in type_tarifs:
            montant = produit.prix_pour(tt.code)
            if montant is not None:
                prix[tt.code] = montant
        return prix

    produits_json = [
        {
            "id": p.id,
            "name": p.name,
            "categorie_id": p.categorie_id,
            "posteId": p.poste_id,
            "prixLibre": p.prix_libre,
            "stock_quantite": p.stock_quantite,
            "statut_stock": p.statut_stock,
            "prix": _prix_disponibles(p),
            "photoUrl": url_for("admin.produit_photo", produit_id=p.id) if p.photo_path else None,
            "codeBarres": p.code_barres,
        }
        for p in produits
    ]

    moyens_paiement = sorted(moyens_paiement, key=lambda m: (not m.is_default, m.name))

    return render_template(
        "pos/index.html",
        postes=postes,
        categories=categories,
        produits_json=produits_json,
        type_tarifs=type_tarifs,
        moyens_paiement=moyens_paiement,
        session=session,
        dernieres_ventes=dernieres_ventes,
        clients=clients,
        taux_change=TauxChange.get(),
        caisse_theorique=calculer_theorique(session)["theorique"],
    )


@bp.route("/vente", methods=["POST"])
@permission_required("point_de_vente")
def creer_vente():
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    data = request.get_json(silent=True) or {}
    try:
        vente = enregistrer_vente(data, session, current_user)
    except VenteError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400

    # Le ticket encaissé n'est plus "en attente" : on supprime son brouillon
    # côté serveur pour ne pas le laisser traîner dans la barre d'onglets.
    ticket_id = data.get("ticket_attente_id")
    if ticket_id:
        ticket = db.session.get(TicketAttente, ticket_id)
        if ticket is not None and ticket.caisse_session_id == session.id:
            db.session.delete(ticket)
            db.session.commit()

    return jsonify({"ok": True, "redirect": url_for("pos.recu", vente_id=vente.id, fresh=1)})


def _ticket_to_dict(ticket):
    return {
        "id": ticket.id,
        "nom": ticket.nom,
        "typeTarifId": ticket.type_tarif_id,
        "clientId": ticket.client_id,
        "clientNom": ticket.client_nom,
        "lignes": ticket.lignes,
        "updatedAt": ticket.updated_at.isoformat(),
    }


@bp.route("/tickets")
@permission_required("point_de_vente")
def tickets_liste():
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    tickets = (
        TicketAttente.query.filter_by(caisse_session_id=session.id)
        .order_by(TicketAttente.created_at)
        .all()
    )
    return jsonify({"ok": True, "tickets": [_ticket_to_dict(t) for t in tickets]})


def _appliquer_donnees_ticket(ticket, data):
    ticket.nom = (data.get("nom") or "Ticket").strip()[:80] or "Ticket"
    ticket.type_tarif_id = data.get("type_tarif_id") or None
    ticket.client_id = data.get("client_id") or None
    ticket.client_nom = (data.get("client_nom") or "").strip() or None
    ticket.lignes = data.get("lignes") or []


@bp.route("/tickets", methods=["POST"])
@permission_required("point_de_vente")
def ticket_creer():
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    data = request.get_json(silent=True) or {}
    ticket = TicketAttente(
        caisse_session_id=session.id,
        created_by_subprofile_id=current_user.id,
        created_by_name=current_user.full_name,
    )
    _appliquer_donnees_ticket(ticket, data)
    db.session.add(ticket)
    db.session.commit()
    return jsonify({"ok": True, "ticket": _ticket_to_dict(ticket)})


@bp.route("/tickets/<int:ticket_id>", methods=["POST"])
@permission_required("point_de_vente")
def ticket_enregistrer(ticket_id):
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    ticket = db.session.get(TicketAttente, ticket_id)
    if ticket is None or ticket.caisse_session_id != session.id:
        abort(404)

    data = request.get_json(silent=True) or {}
    _appliquer_donnees_ticket(ticket, data)
    db.session.commit()
    return jsonify({"ok": True, "ticket": _ticket_to_dict(ticket)})


@bp.route("/tickets/<int:ticket_id>/supprimer", methods=["POST"])
@permission_required("point_de_vente")
def ticket_supprimer(ticket_id):
    session = get_open_session()
    if session is None:
        return jsonify({"ok": False, "error": "Aucune session de caisse ouverte."}), 400

    ticket = db.session.get(TicketAttente, ticket_id)
    if ticket is None or ticket.caisse_session_id != session.id:
        abort(404)

    db.session.delete(ticket)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/vente/<int:vente_id>")
@permission_required("point_de_vente")
def recu(vente_id):
    vente = db.session.get(Vente, vente_id)
    if vente is None:
        abort(404)
    # "fresh=1" : on arrive juste après la validation de la vente -> on propose
    # le choix "client suivant / terminer la session" (pas lors d'une simple
    # consultation ultérieure du reçu).
    fresh = request.args.get("fresh") == "1"
    return render_template("pos/recu.html", vente=vente, fresh=fresh)
