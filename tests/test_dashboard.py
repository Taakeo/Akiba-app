def test_dashboard_sans_credit_client_naffiche_pas_lalerte(client, login_admin, catalogue):
    response = client.get("/")
    assert response.status_code == 200
    assert "client(s) à crédit".encode() not in response.data


def _creer_client_a_credit(db, catalogue, client, nom="Grossiste Endetté", montant=15000):
    from app.models import Client

    c = Client(type_client="grossiste", nom=nom, solde_credit=0)
    db.session.add(c)
    db.session.commit()

    client.post("/caisse/ouverture", data={"fond_ouverture": "0"})
    payload = {
        "type_tarif_id": catalogue["type_tarif_id"],
        "client_id": c.id,
        "lignes": [{"produit_id": catalogue["produit_id"], "quantite": 1, "remise": 0, "offert": False}],
        "paiements": [],
        "a_credit": True,
    }
    client.post("/pos/vente", json=payload)
    return c


def test_dashboard_affiche_lalerte_credits_clients_pour_un_profil_habilite(client, login_admin, catalogue, db):
    # login_admin a "*", donc voit aussi le module Clients — l'alerte doit
    # apparaître puisqu'un vrai crédit existe.
    _creer_client_a_credit(db, catalogue, client)

    response = client.get("/")
    assert response.status_code == 200
    assert "client(s) à crédit".encode() in response.data
    assert "Grossiste Endett".encode() in response.data


def test_dashboard_masque_lalerte_credits_a_un_profil_sans_acces_clients(client, login_seller, catalogue, db):
    # login_seller (Vendeur) n'a pas le droit "clients" — il ne doit pas voir
    # un lien vers un module auquel il n'a de toute façon pas accès.
    _creer_client_a_credit(db, catalogue, client)

    response = client.get("/")
    assert response.status_code == 200
    assert "client(s) à crédit".encode() not in response.data


def test_widgets_tableau_bord_requiert_permission_admin(client, login_seller):
    response = client.get("/admin/tableau-bord")
    assert response.status_code == 403


def test_premier_acces_cree_les_5_widgets_actifs_par_defaut(app, db):
    from app.models import WidgetTableauBord

    with app.app_context():
        widgets = WidgetTableauBord.liste_ordonnee()
        assert len(widgets) == 5
        assert all(w.actif for w in widgets)
        codes = [w.code for w in widgets]
        assert codes == sorted(codes, key=lambda c: [w.code for w in widgets].index(c))  # ordre stable


def test_desactiver_un_widget_le_masque_du_tableau_de_bord(client, login_admin, catalogue):
    response = client.get("/admin/tableau-bord")
    assert response.status_code == 200

    from app.models import WidgetTableauBord

    codes = [w.code for w in WidgetTableauBord.liste_ordonnee()]

    response = client.post(
        "/admin/tableau-bord",
        data={
            "ordre": ",".join(codes),
            "actifs": [c for c in codes if c != "comptes"],  # "comptes" décoché
        },
    )
    assert response.status_code == 302

    dashboard = client.get("/")
    # Le titre "Comptes" du widget est un <h3>, distinct du lien "Comptes" du
    # menu principal (nav) — on cible précisément ce marqueur pour ne pas
    # avoir un faux positif à cause du menu.
    assert b"Comptes</h3>" not in dashboard.data


def test_reordonner_les_widgets_change_lordre_daffichage(client, login_admin, catalogue):
    from app.models import WidgetTableauBord

    widgets = WidgetTableauBord.liste_ordonnee()
    codes = [w.code for w in widgets]
    nouvel_ordre = list(reversed(codes))

    client.post(
        "/admin/tableau-bord",
        data={"ordre": ",".join(nouvel_ordre), "actifs": codes},
    )

    widgets_apres = WidgetTableauBord.query.order_by(WidgetTableauBord.ordre).all()
    assert [w.code for w in widgets_apres] == nouvel_ordre


def test_widget_desactive_reste_masque_meme_avec_le_droit(client, login_admin, catalogue, db):
    from app.models import WidgetTableauBord

    codes = [w.code for w in WidgetTableauBord.liste_ordonnee()]
    client.post(
        "/admin/tableau-bord",
        data={"ordre": ",".join(codes), "actifs": [c for c in codes if c != "stocks"]},
    )

    # login_admin a "*", donc aurait normalement accès au widget Stocks —
    # il doit quand même disparaître puisqu'il est désactivé globalement.
    response = client.get("/")
    assert response.status_code == 200
    assert "Valeur du stock".encode() not in response.data
