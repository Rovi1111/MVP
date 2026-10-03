import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, make_engine
from app.main import create_app
from app.models import Organization, User
from app.permissions import Role
from app.services.users import build_user

PASSWORD = "test-password-1"


@pytest.fixture
def session_factory():
    # Одна in-memory БД на тест; StaticPool — чтобы все сессии видели одно соединение
    engine = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def app(session_factory):
    app = create_app()

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


def make_org(db, name: str) -> Organization:
    org = Organization(name=name)
    db.add(org)
    db.flush()
    return org


def make_user(db, org: Organization, login: str, role: Role) -> User:
    user = build_user(db, org.id, login, PASSWORD, role, full_name=login)
    db.commit()
    return user


@pytest.fixture
def orgs(db):
    """Две организации, в каждой по пользователю каждой роли: a_admin, b_employee и т. д."""
    result = {}
    for prefix, name in (("a", "Организация А"), ("b", "Организация Б")):
        org = make_org(db, name)
        result[prefix] = org
        for role in Role:
            make_user(db, org, f"{prefix}_{role.value}", role)
    return result


class ApiClient(TestClient):
    """TestClient, который после входа сам подставляет CSRF-заголовок."""

    def login(self, login: str, password: str = PASSWORD):
        response = self.post("/api/auth/login", json={"login": login, "password": password})
        if response.status_code == 200:
            self.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return response


@pytest.fixture
def client_for(app, orgs):
    """Фабрика клиентов: client_for("a_admin") — клиент с выполненным входом."""

    def factory(login: str | None = None) -> ApiClient:
        client = ApiClient(app, follow_redirects=False)
        if login:
            assert client.login(login).status_code == 200
        return client

    return factory
