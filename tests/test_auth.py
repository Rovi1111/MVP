from app.models import AuditLog, User
from app.security import hash_password, verify_password
from tests.conftest import PASSWORD


def test_password_hash_roundtrip():
    hashed = hash_password("secret-123")
    assert hashed != "secret-123"
    assert verify_password(hashed, "secret-123")
    assert not verify_password(hashed, "other")
    assert not verify_password(None, "secret-123")


def test_login_and_me(client_for):
    client = client_for("a_manager")
    me = client.get("/api/auth/me").json()
    assert me["login"] == "a_manager"
    assert me["organization"] == "Организация А"
    assert "users:manage" in me["permissions"]


def test_login_wrong_password(client_for):
    client = client_for()
    response = client.login("a_admin", "wrong-password")
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный логин или пароль"
    assert client.get("/api/auth/me").status_code == 401


def test_login_unknown_user(client_for):
    assert client_for().login("nobody").status_code == 401


def test_inactive_user_cannot_login_and_loses_session(client_for, db):
    client = client_for("a_employee")
    user = db.query(User).filter_by(login="a_employee").one()
    user.is_active = False
    db.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert client_for().login("a_employee").status_code == 401


def test_session_cookie_is_httponly(client_for):
    response = client_for().login("a_admin")
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("session="))
    assert "httponly" in session_cookie.lower()
    assert PASSWORD not in session_cookie


def test_tampered_session_cookie_rejected(client_for):
    client = client_for("a_admin")
    client.cookies.set("session", client.cookies.get("session")[:-2] + "xx")
    assert client.get("/api/auth/me").status_code == 401


def test_logout(client_for, db):
    client = client_for("a_admin")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    actions = [row.action for row in db.query(AuditLog).order_by(AuditLog.id)]
    assert actions == ["login", "logout"]


def test_csrf_required_for_mutations(client_for):
    client = client_for("a_admin")
    payload = {"login": "new_user", "password": "long-password", "role": "employee"}
    del client.headers["X-CSRF-Token"]
    assert client.post("/api/users", json=payload).status_code == 403
    assert (
        client.post("/api/users", json=payload, headers={"X-CSRF-Token": "bad"}).status_code == 403
    )
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        client.post("/api/users", json=payload, headers={"X-CSRF-Token": token}).status_code == 201
    )


def test_web_login_flow(client_for):
    client = client_for()
    assert client.get("/web/").headers["location"] == "/web/login"
    page = client.get("/web/login")
    assert page.status_code == 200 and "Вход" in page.text
    token = client.get("/api/auth/csrf").json()["csrf_token"]

    no_csrf = client.post("/web/login", data={"login": "a_admin", "password": PASSWORD})
    assert no_csrf.status_code == 403

    bad = client.post(
        "/web/login", data={"login": "a_admin", "password": "nope", "csrf_token": token}
    )
    assert bad.status_code == 401 and "Неверный логин или пароль" in bad.text

    ok = client.post(
        "/web/login", data={"login": "a_admin", "password": PASSWORD, "csrf_token": token}
    )
    assert ok.status_code == 303 and ok.headers["location"] == "/web/"
    home = client.get("/web/")
    assert home.status_code == 200 and "Организация А" in home.text

    out = client.post("/web/logout", data={"csrf_token": token})
    assert out.status_code == 303
    assert client.get("/web/").status_code == 303


def test_htmx_request_gets_hx_redirect_when_unauthenticated(client_for):
    response = client_for().get("/web/", headers={"HX-Request": "true"})
    assert response.headers["HX-Redirect"] == "/web/login"


def test_password_change_invalidates_sessions(client_for):
    admin, employee = client_for("a_admin"), client_for("a_employee")
    employee_id = employee.get("/api/auth/me").json()["id"]
    changed = admin.patch(f"/api/users/{employee_id}", json={"password": "brand-new-password"})
    assert changed.status_code == 200
    assert employee.get("/api/auth/me").status_code == 401
    assert client_for().login("a_employee", "brand-new-password").status_code == 200
