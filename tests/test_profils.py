def test_profils_requiert_permission_admin(client, login_seller):
    response = client.get("/admin/profils")
    assert response.status_code == 403


def test_profils_liste_accessible_admin(client, login_admin, admin_profile):
    response = client.get("/admin/profils")
    assert response.status_code == 200
    assert b"Administrateur" in response.data
    assert "Accès total".encode() in response.data


def test_creer_un_profil_avec_droits_coches(client, login_admin, admin_profile):
    response = client.post(
        "/admin/profils/nouveau",
        data={"name": "Caissier", "icon": "point_of_sale", "permissions": ["point_de_vente", "caisse"]},
    )
    assert response.status_code == 302

    from app.models import Profile

    profil = Profile.query.filter_by(name="Caissier").first()
    assert profil is not None
    assert set(profil.permissions) == {"point_de_vente", "caisse"}
    assert profil.has_permission("point_de_vente")
    assert not profil.has_permission("rh")


def test_creer_un_profil_avec_acces_total(client, login_admin, admin_profile):
    response = client.post(
        "/admin/profils/nouveau",
        data={"name": "Super Admin", "icon": "shield", "acces_total": "1", "permissions": ["achats"]},
    )
    assert response.status_code == 302

    from app.models import Profile

    profil = Profile.query.filter_by(name="Super Admin").first()
    # acces_total prime sur toute case individuelle cochée par erreur en même temps.
    assert profil.permissions == ["*"]
    assert profil.has_permission("rh")  # "*" donne accès à tout


def test_modifier_un_profil_change_ses_droits(client, login_admin, admin_profile, db):
    from app.models import Profile

    profil = Profile(code="comptable_test", name="Comptable Test", icon="calculate")
    profil.permissions = ["rapports"]
    db.session.add(profil)
    db.session.commit()

    response = client.post(
        f"/admin/profils/{profil.id}/modifier",
        data={"name": "Comptable Test", "icon": "calculate", "permissions": ["rapports", "clients"]},
    )
    assert response.status_code == 302

    db.session.refresh(profil)
    assert set(profil.permissions) == {"rapports", "clients"}


def test_impossible_de_retirer_le_seul_profil_admin(client, login_admin, admin_profile, db):
    from app.models import Profile

    profil = db.session.get(Profile, admin_profile)
    assert profil.permissions == ["*"]

    # On tente de retirer l'accès total du seul profil qui l'a, sans rien
    # cocher à la place — doit être refusé, pas silencieusement accepté.
    response = client.post(
        f"/admin/profils/{profil.id}/modifier",
        data={"name": "Administrateur", "icon": "shield_person"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Impossible".encode() in response.data

    db.session.refresh(profil)
    assert profil.permissions == ["*"]  # inchangé


def test_retirer_admin_dun_profil_reste_possible_si_un_autre_lea(client, login_admin, admin_profile, db):
    from app.models import Profile

    autre_admin = Profile(code="autre_admin_test", name="Autre Admin", icon="shield")
    autre_admin.permissions = ["admin"]
    db.session.add(autre_admin)
    db.session.commit()

    profil = db.session.get(Profile, admin_profile)
    response = client.post(
        f"/admin/profils/{profil.id}/modifier",
        data={"name": "Administrateur", "icon": "shield_person", "permissions": ["rapports"]},
    )
    assert response.status_code == 302

    db.session.refresh(profil)
    assert profil.permissions == ["rapports"]
