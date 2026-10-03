"""Организации не видят и не могут менять данные друг друга."""

from app.models import User
from app.repositories.users import UserRepository


def test_repository_scoped_to_org(db, orgs):
    repo_a = UserRepository(db, orgs["a"].id)
    assert {u.login for u in repo_a.list()} == {"a_admin", "a_manager", "a_employee"}
    foreign = db.query(User).filter_by(login="b_admin").one()
    assert repo_a.get(foreign.id) is None


def test_repository_add_forces_own_org(db, orgs):
    repo_a = UserRepository(db, orgs["a"].id)
    user = repo_a.add(User(org_id=orgs["b"].id, login="sneaky", password_hash="x", role="employee"))
    assert user.org_id == orgs["a"].id


def test_api_lists_only_own_org_users(client_for, orgs):
    users = client_for("a_admin").get("/api/users").json()
    assert {u["org_id"] for u in users} == {orgs["a"].id}
    assert all(u["login"].startswith("a_") for u in users)


def test_api_cannot_modify_foreign_user(client_for, db):
    foreign = db.query(User).filter_by(login="b_employee").one()
    response = client_for("a_admin").patch(f"/api/users/{foreign.id}", json={"is_active": False})
    assert response.status_code == 404
    db.refresh(foreign)
    assert foreign.is_active is True


def test_created_user_belongs_to_actor_org(client_for, orgs):
    created = client_for("b_admin").post(
        "/api/users", json={"login": "b_new", "password": "long-password", "role": "employee"}
    )
    assert created.json()["org_id"] == orgs["b"].id
