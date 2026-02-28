"""Shared fixtures for Standup 3000 tests."""
import os
import tempfile
import pytest
import db
from app import create_app


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Use a fresh temp database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    # Point migrations to the real directory
    monkeypatch.setattr(db, "MIGRATIONS_DIR", os.path.join(os.path.dirname(__file__), "migrations"))


@pytest.fixture
def app(tmp_path):
    """Create a test Flask app."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def admin_user():
    """Create and return an admin user."""
    user = db.create_user("admin", "Admin User", "password123", role="admin")
    return user


@pytest.fixture
def member_user():
    """Create and return a regular member user."""
    user = db.create_user("member", "Member User", "password123", role="member")
    return user


@pytest.fixture
def logged_in_admin(client, admin_user):
    """Return a client logged in as admin."""
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user["id"]
        sess["_csrf_token"] = "test-csrf-token"
    return client


@pytest.fixture
def logged_in_member(client, member_user):
    """Return a client logged in as member."""
    with client.session_transaction() as sess:
        sess["user_id"] = member_user["id"]
        sess["_csrf_token"] = "test-csrf-token"
    return client


@pytest.fixture
def csrf_data():
    """Return form data dict with CSRF token."""
    return {"_csrf_token": "test-csrf-token"}


@pytest.fixture
def csrf_headers():
    """Return headers dict with CSRF token."""
    return {"X-CSRF-Token": "test-csrf-token"}
