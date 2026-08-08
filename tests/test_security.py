def test_inactivity_script_present_when_authenticated(client, login_seller):
    response = client.get("/")
    assert response.status_code == 200
    assert b"inactivity.js" in response.data
    assert b'id="auto-logout-form"' in response.data


def test_inactivity_script_absent_when_anonymous(client):
    response = client.get("/auth/")
    assert response.status_code == 200
    assert b"inactivity.js" not in response.data


def test_auto_logout_form_posts_to_logout(client, login_seller):
    response = client.get("/")
    assert response.status_code == 200
    assert b'action="/auth/deconnexion"' in response.data
