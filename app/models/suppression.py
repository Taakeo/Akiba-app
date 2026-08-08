"""Suppression définitive (en plus de l'archivage) pour le catalogue, les
salariés et les clients — chaque fonction renvoie une raison de blocage
(texte) si l'élément est référencé ailleurs, ou None si la suppression peut
avoir lieu sans casser d'historique. Les utilisateurs (sous-profils) ne
passent pas par ce module : voir app/cli.py::_purger_utilisateurs_suspendus,
dont la suppression manuelle réutilise exactement la même logique (FK
nullable + nom figé, jamais de blocage)."""

from ..extensions import db
from .achat import Achat, AchatRecurrent
from .catalogue import PrixProduit, Produit, SousCategorie
from .client import ClientPaiement
from .finance import AjustementCompte, CaisseSession, MoyenPaiement
from .inventaire import InventaireLigne
from .production import Fabrication
from .rh import Absence, RemunerationSalarie, Salarie
from .stock import MouvementStock
from .ventes import LigneVente, Vente


def _existe(query):
    return db.session.query(query.exists()).scalar()


def verifier_suppression_produit(produit):
    if _existe(Achat.query.filter_by(produit_id=produit.id)):
        return "un achat référence ce produit"
    if _existe(InventaireLigne.query.filter_by(produit_id=produit.id)):
        return "un inventaire référence ce produit"
    if _existe(Fabrication.query.filter_by(produit_id=produit.id)):
        return "une fabrication référence ce produit"
    if _existe(MouvementStock.query.filter_by(produit_id=produit.id)):
        return "un mouvement de stock référence ce produit"
    if _existe(LigneVente.query.filter_by(produit_id=produit.id)):
        return "une vente référence ce produit"
    if _existe(AchatRecurrent.query.filter_by(produit_id=produit.id)):
        return "un modèle d'achat récurrent référence ce produit"
    return None


def verifier_suppression_categorie(categorie):
    if _existe(Produit.query.filter_by(categorie_id=categorie.id)):
        return "un produit est classé dans cette catégorie"
    if _existe(SousCategorie.query.filter_by(categorie_id=categorie.id)):
        return "des sous-catégories dépendent encore de cette catégorie"
    if _existe(Achat.query.filter_by(categorie_id=categorie.id)):
        return "un achat référence cette catégorie"
    if _existe(LigneVente.query.filter_by(categorie_id=categorie.id)):
        return "une vente référence cette catégorie"
    if _existe(AchatRecurrent.query.filter_by(categorie_id=categorie.id)):
        return "un modèle d'achat récurrent référence cette catégorie"
    return None


def verifier_suppression_sous_categorie(sous_categorie):
    if _existe(Produit.query.filter_by(sous_categorie_id=sous_categorie.id)):
        return "un produit est classé dans cette sous-catégorie"
    if _existe(Achat.query.filter_by(sous_categorie_id=sous_categorie.id)):
        return "un achat référence cette sous-catégorie"
    if _existe(LigneVente.query.filter_by(sous_categorie_id=sous_categorie.id)):
        return "une vente référence cette sous-catégorie"
    if _existe(AchatRecurrent.query.filter_by(sous_categorie_id=sous_categorie.id)):
        return "un modèle d'achat récurrent référence cette sous-catégorie"
    return None


def verifier_suppression_poste(poste):
    if _existe(Produit.query.filter_by(poste_id=poste.id)):
        return "un produit est rattaché à ce poste"
    if _existe(Achat.query.filter_by(poste_id=poste.id)):
        return "un achat référence ce poste"
    if _existe(LigneVente.query.filter_by(poste_id=poste.id)):
        return "une vente référence ce poste"
    if _existe(AchatRecurrent.query.filter_by(poste_id=poste.id)):
        return "un modèle d'achat récurrent référence ce poste"
    if _existe(Salarie.query.filter_by(poste_id=poste.id)):
        return "un salarié est rattaché à ce poste"
    return None


def verifier_suppression_projet(projet):
    if _existe(Produit.query.filter_by(projet_id=projet.id)):
        return "un produit est rattaché à ce projet"
    if _existe(Achat.query.filter_by(projet_id=projet.id)):
        return "un achat référence ce projet"
    if _existe(LigneVente.query.filter_by(projet_id=projet.id)):
        return "une vente référence ce projet"
    if _existe(AchatRecurrent.query.filter_by(projet_id=projet.id)):
        return "un modèle d'achat récurrent référence ce projet"
    if _existe(Salarie.query.filter_by(projet_id=projet.id)):
        return "un salarié est rattaché à ce projet"
    return None


def verifier_suppression_fournisseur(fournisseur):
    if _existe(Achat.query.filter_by(fournisseur_id=fournisseur.id)):
        return "un achat référence ce fournisseur"
    if _existe(Produit.query.filter_by(fournisseur_principal_id=fournisseur.id)):
        return "un produit a ce fournisseur comme fournisseur principal"
    if _existe(AchatRecurrent.query.filter_by(fournisseur_id=fournisseur.id)):
        return "un modèle d'achat récurrent référence ce fournisseur"
    return None


def verifier_suppression_tarif(tarif):
    if _existe(PrixProduit.query.filter_by(type_tarif_id=tarif.id)):
        return "un prix de produit est défini pour ce tarif"
    if _existe(Vente.query.filter_by(type_tarif_id=tarif.id)):
        return "une vente a été faite avec ce tarif"
    return None


def verifier_suppression_salarie(salarie):
    if _existe(RemunerationSalarie.query.filter_by(salarie_id=salarie.id)):
        return "des rémunérations sont enregistrées pour ce salarié"
    if _existe(Absence.query.filter_by(salarie_id=salarie.id)):
        return "des absences sont enregistrées pour ce salarié"
    return None


def verifier_suppression_compte_financier(compte):
    if _existe(MoyenPaiement.query.filter_by(compte_financier_id=compte.id)):
        return "un moyen de paiement est rattaché à ce compte"
    if _existe(CaisseSession.query.filter_by(compte_financier_id=compte.id)):
        return "une session de caisse a été ouverte sur ce compte"
    if _existe(AjustementCompte.query.filter_by(compte_financier_id=compte.id)):
        return "un ajustement de solde est enregistré pour ce compte"
    return None


def verifier_suppression_client(client):
    if _existe(Vente.query.filter_by(client_id=client.id)):
        return "des ventes sont rattachées à ce client"
    if _existe(ClientPaiement.query.filter_by(client_id=client.id)):
        return "des paiements de crédit sont rattachés à ce client"
    if client.solde_credit:
        return "ce client a un solde de crédit dû"
    return None
