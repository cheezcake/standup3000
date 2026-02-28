"""Tests for auth.py — authentication, CSRF, rate limiting."""
import db


class TestLogin:
    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b"Standup 3000" in resp.data

    def test_first_run_shows_setup(self, client):
        resp = client.get("/login")
        assert b"display_name" in resp.data  # Setup form has display_name field

    def test_first_run_setup_creates_admin(self, client):
        resp = client.post("/login", data={
            "username": "admin",
            "display_name": "Admin User",
            "password": "TestPass!2026",
            "confirm_password": "TestPass!2026",
        }, follow_redirects=False)
        assert resp.status_code == 302
        user = db.get_user_by_username("admin")
        assert user is not None
        assert user["role"] == "admin"

    def test_first_run_short_password_rejected(self, client):
        resp = client.post("/login", data={
            "username": "admin",
            "display_name": "Admin",
            "password": "short",
            "confirm_password": "short",
        })
        assert resp.status_code == 200
        assert not db.has_any_users()

    def test_first_run_password_mismatch_rejected(self, client):
        resp = client.post("/login", data={
            "username": "admin",
            "display_name": "Admin",
            "password": "password123",
            "confirm_password": "password456",
        })
        assert resp.status_code == 200
        assert not db.has_any_users()

    def test_login_success(self, client, admin_user):
        resp = client.post("/login", data={
            "username": "admin",
            "password": "password123",
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_login_wrong_password(self, client, admin_user):
        resp = client.post("/login", data={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client, admin_user):
        resp = client.post("/login", data={
            "username": "ghost",
            "password": "password123",
        })
        assert resp.status_code == 401

    def test_login_redirect_preserves_next(self, client, admin_user):
        resp = client.post("/login?next=/meetings", data={
            "username": "admin",
            "password": "password123",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "/meetings" in resp.headers["Location"]

    def test_login_blocks_open_redirect(self, client, admin_user):
        resp = client.post("/login?next=//evil.com", data={
            "username": "admin",
            "password": "password123",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "evil.com" not in resp.headers["Location"]

    def test_already_logged_in_redirects(self, logged_in_admin):
        resp = logged_in_admin.get("/login", follow_redirects=False)
        assert resp.status_code == 302

    def test_inactive_user_cannot_login(self, client, admin_user):
        # Clear rate limiter from previous test attempts
        from auth import _login_attempts
        _login_attempts.clear()
        db.update_user(admin_user["id"], is_active=False)
        resp = client.post("/login", data={
            "username": "admin",
            "password": "password123",
        })
        assert resp.status_code == 401


class TestLogout:
    def test_logout_clears_session(self, logged_in_admin, csrf_data):
        resp = logged_in_admin.post("/logout", data=csrf_data, follow_redirects=False)
        assert resp.status_code == 302
        # Subsequent request should redirect to login
        resp2 = logged_in_admin.get("/", follow_redirects=False)
        assert resp2.status_code == 302
        assert "/login" in resp2.headers["Location"]


class TestChangePassword:
    def test_change_password_page_renders(self, logged_in_admin):
        resp = logged_in_admin.get("/settings/password")
        assert resp.status_code == 200

    def test_change_password_success(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "current_password": "password123",
                "new_password": "newpassword456", "confirm_password": "newpassword456"}
        resp = logged_in_admin.post("/settings/password", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert db.authenticate_user("admin", "newpassword456") is not None

    def test_change_password_wrong_current(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "current_password": "wrong",
                "new_password": "newpassword456", "confirm_password": "newpassword456"}
        resp = logged_in_admin.post("/settings/password", data=data)
        assert resp.status_code == 200

    def test_change_password_mismatch(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "current_password": "password123",
                "new_password": "newpassword456", "confirm_password": "different789"}
        resp = logged_in_admin.post("/settings/password", data=data)
        assert resp.status_code == 200

    def test_change_password_too_short(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "current_password": "password123",
                "new_password": "short", "confirm_password": "short"}
        resp = logged_in_admin.post("/settings/password", data=data)
        assert resp.status_code == 200

    def test_must_change_password_skips_current(self, client, csrf_data):
        """When must_change_password is set, current password is not required."""
        user = db.create_user("temp", "Temp User", "password123")
        db.reset_password(user["id"], "temppass123")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]
            sess["_csrf_token"] = "test-csrf-token"
        data = {**csrf_data, "new_password": "finalpass789", "confirm_password": "finalpass789"}
        resp = client.post("/settings/password", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert db.authenticate_user("temp", "finalpass789") is not None


class TestCSRF:
    def test_post_without_csrf_blocked(self, logged_in_admin):
        resp = logged_in_admin.post("/meeting/new", data={"date": "2026-03-01"})
        assert resp.status_code == 403

    def test_post_with_csrf_allowed(self, logged_in_admin, csrf_data):
        resp = logged_in_admin.post("/meeting/new",
                                    data={**csrf_data, "date": "2026-03-01"},
                                    follow_redirects=False)
        assert resp.status_code in (200, 302)

    def test_csrf_via_header(self, logged_in_admin, csrf_headers):
        resp = logged_in_admin.put("/todo/9999/toggle", headers=csrf_headers)
        # Should get 404 (todo doesn't exist) rather than 403 (CSRF fail)
        assert resp.status_code == 404


class TestLoginRequired:
    def test_unauthenticated_redirect(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_meetings_require_login(self, client):
        resp = client.get("/meetings", follow_redirects=False)
        assert resp.status_code == 302

    def test_todos_require_login(self, client):
        resp = client.get("/todos", follow_redirects=False)
        assert resp.status_code == 302
