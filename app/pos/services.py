from ..caisse.services import crediter_compte, debiter_compte
from ..extensions import db
from ..models import Client, LigneVente, MoyenPaiement, Produit, TypeTarif, Vente, VentePaiement, enregistrer_mouvement


class VenteError(ValueError):
    pass


def enregistrer_vente(data, session, current_user):
    """Valide et enregistre une vente : prix recalculés serveur (jamais depuis le
    client), stock décrémenté, comptes financiers crédités — une seule saisie
    propage caisse + stock (§1, §6, §7.6 spec)."""

    type_tarif = db.session.get(TypeTarif, data.get("type_tarif_id"))
    if type_tarif is None or type_tarif.is_archived:
        raise VenteError("Tarif invalide.")

    lignes_data = data.get("lignes") or []
    if not lignes_data:
        raise VenteError("Le ticket est vide.")

    client = None
    client_id = data.get("client_id")
    if client_id:
        client = db.session.get(Client, client_id)
        if client is None or client.is_archived:
            raise VenteError("Client invalide.")

    vente = Vente(
        caisse_session_id=session.id,
        type_tarif_id=type_tarif.id,
        client_id=client.id if client else None,
        client_nom=client.nom if client else (data.get("client_nom") or "").strip() or None,
        commentaire=(data.get("commentaire") or "").strip() or None,
        created_by_subprofile_id=current_user.id,
        created_by_name=current_user.full_name,
    )
    db.session.add(vente)
    db.session.flush()  # attribue vente.id, référencé par les mouvements de stock

    sous_total = 0
    for ligne_data in lignes_data:
        produit = db.session.get(Produit, ligne_data.get("produit_id"))
        if produit is None or produit.is_archived:
            raise VenteError("Produit invalide.")

        quantite = int(ligne_data.get("quantite") or 0)
        if quantite < 1:
            raise VenteError(f"Quantité invalide pour {produit.name}.")

        offert = bool(ligne_data.get("offert"))
        remise = max(0, int(ligne_data.get("remise") or 0))

        # Un stock affiché à 0 (ou insuffisant) ne bloque plus la vente —
        # l'inventaire réel du magasin peut être en avance sur l'inventaire
        # saisi (retour utilisateur : refaire l'inventaire est la
        # responsabilité du vendeur, pas une raison de bloquer un client au
        # comptoir). enregistrer_mouvement() empêche que le stock affiché
        # passe sous zéro pour autant.

        if produit.prix_libre:
            # Prix libre (ex. Pourboire) : pas de tarif fixe, le montant vient
            # du panier — mais reste un entier positif, jamais négatif ou nul
            # (sauf article offert), pour ne pas fausser le total du ticket.
            prix_unitaire = int(ligne_data.get("prix_unitaire") or 0)
            if prix_unitaire <= 0 and not offert:
                raise VenteError(f"Montant invalide pour {produit.name}.")
        else:
            prix_unitaire = produit.prix_pour(type_tarif.code)
            if prix_unitaire is None:
                raise VenteError(f"Aucun tarif {type_tarif.label} pour {produit.name}.")

        ligne = LigneVente(
            produit_id=produit.id,
            produit_nom=produit.name,
            poste_id=produit.poste_id,
            projet_id=produit.projet_id,
            categorie_id=produit.categorie_id,
            sous_categorie_id=produit.sous_categorie_id,
            quantite=quantite,
            prix_unitaire=prix_unitaire,
            remise=remise,
            offert=offert,
            commentaire=(ligne_data.get("commentaire") or "").strip() or None,
        )
        ligne.calculer_total()
        sous_total += ligne.total_ligne
        if not produit.stock_illimite:
            # Un article offert est une sortie de stock distincte d'une vente
            # payée (§9.5 spec : "cadeaux/dégustations" à distinguer des
            # ventes pour affiner l'analyse des résultats).
            enregistrer_mouvement(
                produit,
                "sortie",
                "offert" if offert else "vente",
                quantite,
                current_user,
                reference_type="vente",
                reference_id=vente.id,
            )
        vente.lignes.append(ligne)

    remise_vente = max(0, int(data.get("remise_vente") or 0))
    total = max(0, sous_total - remise_vente)

    vente.sous_total = sous_total
    vente.remise = remise_vente
    vente.total = total

    paiements_data = data.get("paiements") or []
    a_credit = bool(data.get("a_credit"))
    if a_credit and client is None:
        raise VenteError("La vente à crédit nécessite un client enregistré.")

    if total > 0 and not paiements_data and not a_credit:
        raise VenteError("Aucun moyen de paiement renseigné.")

    total_paye = 0
    paiement_devise_etrangere = False
    for paiement_data in paiements_data:
        montant = int(paiement_data.get("montant") or 0)
        if montant <= 0:
            continue
        moyen = db.session.get(MoyenPaiement, paiement_data.get("moyen_paiement_id"))
        if moyen is None or moyen.is_archived:
            raise VenteError("Moyen de paiement invalide.")
        vente.paiements.append(VentePaiement(moyen_paiement_id=moyen.id, montant=montant))
        crediter_compte(moyen.compte_financier, montant)
        if moyen.compte_financier.devise == "Ar":
            total_paye += montant
        else:
            # Paiement en devise étrangère (ex. euros) : le montant saisi est
            # manuel et définitif, jamais recalculé/comparé au total ariary
            # via le taux de change (retour utilisateur : "c'est l'euro qui
            # doit être pris en compte", "plus de comparaison ariary-euro").
            # Un taux mal renseigné ou un prix négocié différent du calcul
            # théorique ne doit jamais bloquer la vente.
            paiement_devise_etrangere = True

    montant_restant = 0 if paiement_devise_etrangere else total - total_paye
    if montant_restant > 0:
        if not a_credit:
            raise VenteError(
                f"Le total payé ({total_paye}) ne correspond pas au total du ticket ({total})."
            )
        vente.montant_credit = montant_restant
        vente.credit_solde_restant = montant_restant
        client.solde_credit += montant_restant
    elif montant_restant < 0:
        raise VenteError(f"Le total payé ({total_paye}) dépasse le total du ticket ({total}).")

    db.session.commit()
    return vente


def annuler_vente(vente, motif, current_user):
    """Annule une vente déjà validée (ex. double saisie par erreur) : reverse
    proprement son impact stock + comptes financiers + crédit client, sans
    jamais supprimer les lignes/paiements d'origine (trace d'audit conservée
    — même esprit que AjustementCompte, jamais une correction silencieuse).
    Réservé au droit "corrections" (app/pos/routes.py)."""
    if vente.statut != "validee":
        raise VenteError("Cette vente est déjà annulée.")
    if vente.facture_id is not None:
        raise VenteError(
            "Cette vente est déjà facturée — elle ne peut pas être annulée directement."
        )
    if not motif or not motif.strip():
        raise VenteError("Un motif est obligatoire pour annuler une vente.")

    # Stock : chaque ligne ayant décrémenté un produit suivi (vente/offert,
    # jamais stock_illimite) reçoit un mouvement d'entrée inverse.
    for ligne in vente.lignes:
        produit = ligne.produit
        if produit is not None and not produit.stock_illimite:
            enregistrer_mouvement(
                produit,
                "entree",
                "correction",
                ligne.quantite,
                current_user,
                commentaire=f"Annulation vente #{vente.id}",
                reference_type="vente",
                reference_id=vente.id,
            )

    # Comptes financiers : chaque paiement encaissé est repris dans sa propre
    # devise, symétriquement à crediter_compte() lors de l'encaissement — les
    # lignes VentePaiement elles-mêmes restent en base (trace d'audit).
    for paiement in vente.paiements:
        debiter_compte(paiement.moyen_paiement.compte_financier, paiement.montant)

    # Crédit client : seulement s'il n'a pas déjà commencé à être remboursé —
    # un reversal FIFO partiel serait trop délicat à défaire automatiquement
    # sans risquer de désynchroniser d'autres ventes à crédit du même client.
    if vente.montant_credit > 0:
        if vente.credit_solde_restant < vente.montant_credit:
            raise VenteError(
                "Cette vente à crédit a déjà commencé à être remboursée — "
                "elle ne peut pas être annulée automatiquement."
            )
        if vente.client is not None:
            vente.client.solde_credit -= vente.credit_solde_restant
        vente.credit_solde_restant = 0

    vente.statut = "annulee"
    vente.commentaire = (
        f"[ANNULÉE] {motif.strip()} — par {current_user.full_name}"
        + (f"\n{vente.commentaire}" if vente.commentaire else "")
    )
    db.session.commit()
    return vente
