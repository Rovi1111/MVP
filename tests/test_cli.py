from app import cli
from app.models import Organization, User
from app.security import verify_password


def test_create_admin_creates_org_and_user(session_factory, db, capsys):
    argv = ["create-admin", "--org", "Новая", "--login", "root", "--password", "long-password"]
    assert cli.main(argv, session_factory) == 0
    user = db.query(User).filter_by(login="root").one()
    assert user.role == "admin" and user.is_active
    assert verify_password(user.password_hash, "long-password")
    assert db.get(Organization, user.org_id).name == "Новая"
    assert "создан" in capsys.readouterr().out


def test_create_admin_reuses_org_and_rejects_duplicates(session_factory, db, capsys):
    base = ["create-admin", "--org", "Новая", "--password", "long-password", "--login"]
    assert cli.main([*base, "root"], session_factory) == 0
    assert cli.main([*base, "root2"], session_factory) == 0
    assert db.query(Organization).count() == 1
    assert cli.main([*base, "root"], session_factory) == 1
    assert "уже занят" in capsys.readouterr().err


def test_create_admin_rejects_short_password(session_factory, capsys):
    argv = ["create-admin", "--org", "Новая", "--login", "root", "--password", "123"]
    assert cli.main(argv, session_factory) == 1
    assert "не короче" in capsys.readouterr().err
