import pytest

from app.permissions import MATRIX, Permission, Role, has_permission

EMPLOYEE_ALLOWED = {
    Permission.DATA_UPLOAD,
    Permission.DATA_MANUAL,
    Permission.ANALYTICS_VIEW,
    Permission.AI_RUN,
    Permission.REPORTS,
}


def test_matrix_covers_all_roles():
    assert set(MATRIX) == set(Role)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MANAGER])
def test_admin_and_manager_can_everything(role):
    assert all(has_permission(role, p) for p in Permission)


@pytest.mark.parametrize("permission", list(Permission))
def test_employee_matrix(permission):
    assert has_permission(Role.EMPLOYEE, permission) == (permission in EMPLOYEE_ALLOWED)


def test_unknown_role_has_no_permissions():
    assert not has_permission("guest", Permission.ANALYTICS_VIEW)


def test_employee_gets_403_on_user_management(client_for):
    client = client_for("a_employee")
    assert client.get("/api/users").status_code == 403
    payload = {"login": "x", "password": "long-password", "role": "admin"}
    assert client.post("/api/users", json=payload).status_code == 403
    assert client.patch("/api/users/1", json={"role": "admin"}).status_code == 403


@pytest.mark.parametrize("login", ["a_admin", "a_manager"])
def test_admin_and_manager_manage_users(client_for, login):
    client = client_for(login)
    assert client.get("/api/users").status_code == 200
    created = client.post(
        "/api/users", json={"login": "newbie", "password": "long-password", "role": "employee"}
    )
    assert created.status_code == 201
    assert "password" not in created.text
    assert client_for().login("newbie", "long-password").status_code == 200


def test_unauthenticated_api_returns_401(client_for):
    assert client_for().get("/api/users").status_code == 401


def test_user_validation_and_conflicts(client_for):
    client = client_for("a_admin")
    short = client.post("/api/users", json={"login": "u", "password": "123", "role": "employee"})
    assert short.status_code == 422
    assert short.json()["errors"][0]["field"] == "password"
    bad_role = client.post(
        "/api/users", json={"login": "u", "password": "long-password", "role": "boss"}
    )
    assert bad_role.status_code == 422
    duplicate = client.post(
        "/api/users", json={"login": "a_manager", "password": "long-password", "role": "employee"}
    )
    assert duplicate.status_code == 409

    me = client.get("/api/auth/me").json()
    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/users/{me['id']}", json={"role": "employee"}).status_code == 409
