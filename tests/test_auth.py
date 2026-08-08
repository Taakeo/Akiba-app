def test_select_profile_lists_profiles(client, seller_profile):
    response = client.get("/auth/")
    assert response.status_code == 200
    assert b"Vendeur" in response.data


def test_select_user_lists_active_subprofiles(client, seller_profile, seller_subprofile):
    response = client.get(f"/auth/profil/{seller_profile}")
    assert response.status_code == 200
    assert "Sarah".encode() in response.data


def test_wrong_pin_shows_error(client, seller_profile, seller_subprofile):
    response = client.post(
        f"/auth/profil/{seller_profile}/utilisateur/{seller_subprofile}",
        data={"pin": "0000"},
    )
    assert response.status_code == 200
    assert "Code PIN incorrect".encode() in response.data


def test_correct_pin_logs_in_and_redirects_to_dashboard(client, seller_profile, seller_subprofile):
    response = client.post(
        f"/auth/profil/{seller_profile}/utilisateur/{seller_subprofile}",
        data={"pin": "1234"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    dashboard = client.get("/", follow_redirects=True)
    assert dashboard.status_code == 200
    assert "Sarah".encode() in dashboard.data


def test_pin_doit_faire_exactement_4_chiffres(client, seller_profile, seller_subprofile):
    for pin_invalide in ["123", "12345", "abcd"]:
        response = client.post(
            f"/auth/profil/{seller_profile}/utilisateur/{seller_subprofile}",
            data={"pin": pin_invalide},
        )
        assert response.status_code == 200
        assert "exactement 4 chiffres".encode() in response.data


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/" in response.headers["Location"]


def test_logout_redirects_to_select_profile(client, seller_profile, seller_subprofile):
    client.post(
        f"/auth/profil/{seller_profile}/utilisateur/{seller_subprofile}",
        data={"pin": "1234"},
    )
    response = client.post("/auth/deconnexion")
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/"


def test_suspended_subprofile_cannot_be_selected(client, app, db, seller_profile, seller_subprofile):
    from app.models import SubProfile

    with app.app_context():
        sub_profile = db.session.get(SubProfile, seller_subprofile)
        sub_profile.suspend()
        db.session.commit()

    response = client.get(f"/auth/profil/{seller_profile}")
    assert "Sarah".encode() not in response.data

    response = client.get(f"/auth/profil/{seller_profile}/utilisateur/{seller_subprofile}")
    assert response.status_code == 404


def test_logo_akiba_present_sur_ecran_de_connexion_et_favicon(client, seller_profile):
    response = client.get("/auth/")
    assert response.status_code == 200
    assert b"vendor/logo/akiba-logo.png" in response.data
    assert b"vendor/logo/akiba.ico" in response.data
