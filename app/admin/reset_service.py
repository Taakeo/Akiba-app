"""Réinitialisation avant le lancement réel en production (retour utilisateur :
le client teste l'appli avec des données fictives avant de démarrer réellement
en boutique et veut repartir "avec toute sa db mais avec des chiffres concrets
qui seront incrémentés au fur et à mesure de ses ventes depuis sa première
vraie utilisation"). Vide l'historique financier/transactionnel de test tout
en conservant catalogue, prix, stock, comptes/moyens de paiement, clients et
utilisateurs — "tout est conservé sauf les données d'économie (hors prix)"
(réponse utilisateur exacte). Toujours précédé d'une sauvegarde complète : en
cas d'échec de celle-ci, rien n'est jamais effacé."""

from ..extensions import db
from ..models import (
    Absence,
    Achat,
    AchatDocument,
    AjustementCompte,
    CaisseSession,
    Client,
    ClientPaiement,
    CompteFinancier,
    Fabrication,
    Inventaire,
    InventaireLigne,
    LigneVente,
    MouvementCaisse,
    MouvementStock,
    Produit,
    RemunerationSalarie,
    TicketAttente,
    Vente,
    VenteExterne,
    VentePaiement,
)
from .backup_service import BackupError, creer_sauvegarde, log_audit


class ReinitialisationError(ValueError):
    pass


def resume_avant_reinitialisation():
    """Chiffres réels de la base actuelle, affichés sur l'écran de
    confirmation pour remplacer une explication abstraite par une preuve
    concrète (retour utilisateur : confusion/peur que "l'inventaire bouge" —
    montrer que le catalogue et le stock resteront identiques, chiffres à
    l'appui, rassure mieux qu'un texte générique)."""
    total_articles_stock = (
        db.session.query(db.func.coalesce(db.func.sum(Produit.stock_quantite), 0))
        .filter(Produit.is_archived.is_(False), Produit.stock_illimite.is_(False))
        .scalar()
    )
    return {
        "nb_produits": Produit.query.filter_by(is_archived=False).count(),
        "total_articles_stock": total_articles_stock,
        "nb_ventes": Vente.query.count(),
        "nb_achats": Achat.query.count(),
        "nb_ventes_externes": VenteExterne.query.count(),
        "nb_fabrications": Fabrication.query.count(),
        "nb_sessions_caisse": CaisseSession.query.count(),
    }


def reinitialiser_pour_production(app, current_user):
    try:
        horodatage = creer_sauvegarde(app, current_user)
    except BackupError as exc:
        raise ReinitialisationError(f"Sauvegarde impossible ({exc}) — rien n'a été effacé.") from exc

    try:
        # Ordre enfants -> parents (contraintes de clé étrangère).
        LigneVente.query.delete()
        VentePaiement.query.delete()
        Vente.query.delete()
        TicketAttente.query.delete()
        AchatDocument.query.delete()
        Achat.query.delete()
        VenteExterne.query.delete()
        MouvementStock.query.delete()
        MouvementCaisse.query.delete()
        CaisseSession.query.delete()
        AjustementCompte.query.delete()
        RemunerationSalarie.query.delete()
        Absence.query.delete()
        InventaireLigne.query.delete()
        Inventaire.query.delete()
        Fabrication.query.delete()
        ClientPaiement.query.delete()

        # Accumulateurs stockés (pas recalculés automatiquement par les
        # suppressions ci-dessus) — sans ça, des soldes "fantômes" resteraient
        # sans aucun historique pour les justifier.
        for compte in CompteFinancier.query.all():
            compte.solde = 0
        for client in Client.query.all():
            client.solde_credit = 0

        # Le stock lui-même est conservé tel quel (réponse utilisateur), mais
        # son historique de mouvements est maintenant vide — un mouvement de
        # "solde de départ" est journalisé pour chaque produit non vide, sans
        # toucher à stock_quantite (déjà la bonne valeur), pour que Stocks ->
        # Mouvements reste cohérent avec le stock affiché.
        for produit in Produit.query.all():
            if not produit.stock_illimite and produit.stock_quantite != 0:
                db.session.add(
                    MouvementStock(
                        produit_id=produit.id,
                        type_mouvement="entree",
                        motif="correction",
                        quantite=produit.stock_quantite,
                        commentaire="Solde de départ — lancement en production",
                        created_by_subprofile_id=current_user.id,
                        created_by_name=current_user.full_name,
                    )
                )

        # FactureCompteur.dernier_numero est délibérément laissé tel quel —
        # jamais remis à zéro, pour ne jamais risquer de dupliquer un numéro
        # de facture déjà émis, même pendant la phase de test.

        log_audit(app, "reinitialisation_production", horodatage, current_user)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ReinitialisationError(
            f"La réinitialisation a échoué et a été annulée (rien n'a été perdu) : {exc}"
        ) from exc

    return horodatage
