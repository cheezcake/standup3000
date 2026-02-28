"""Tests for admin.py — admin panel routes."""
import db


class TestAdminAccess:
    def test_admin_dashboard_requires_admin(self, logged_in_member):
        resp = logged_in_member.get("/admin/")
        assert resp.status_code == 403

    def test_admin_dashboard_accessible_by_admin(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/")
        assert resp.status_code == 200

    def test_admin_requires_login(self, client):
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


class TestUserManagement:
    def test_users_list(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/users")
        assert resp.status_code == 200
        assert b"Admin User" in resp.data

    def test_create_user(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "username": "newuser", "display_name": "New User",
                "password": "TestPass!2026", "role": "member"}
        resp = logged_in_admin.post("/admin/users/new", data=data, follow_redirects=False)
        assert resp.status_code == 302
        user = db.get_user_by_username("newuser")
        assert user is not None
        assert user["role"] == "member"

    def test_create_user_short_password(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "username": "newuser", "display_name": "New",
                "password": "short", "role": "member"}
        resp = logged_in_admin.post("/admin/users/new", data=data)
        assert resp.status_code == 200  # Re-renders form
        assert db.get_user_by_username("newuser") is None

    def test_create_user_missing_fields(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "username": "", "display_name": "", "password": "password123"}
        resp = logged_in_admin.post("/admin/users/new", data=data)
        assert resp.status_code == 200

    def test_edit_user(self, logged_in_admin, member_user, csrf_data):
        data = {**csrf_data, "display_name": "Updated Name", "role": "member",
                "is_active": "1", "email": "new@example.com"}
        resp = logged_in_admin.post(f"/admin/users/{member_user['id']}/edit",
                                    data=data, follow_redirects=False)
        assert resp.status_code == 302
        updated = db.get_user(member_user["id"])
        assert updated["display_name"] == "Updated Name"
        assert updated["email"] == "new@example.com"

    def test_edit_user_404(self, logged_in_admin, csrf_data):
        resp = logged_in_admin.get("/admin/users/9999/edit")
        assert resp.status_code == 404

    def test_cannot_deactivate_self(self, logged_in_admin, admin_user, csrf_data):
        data = {**csrf_data, "display_name": "Admin User", "role": "admin"}
        # Note: is_active NOT in form means it will be False
        resp = logged_in_admin.post(f"/admin/users/{admin_user['id']}/edit",
                                    data=data)
        assert resp.status_code == 200  # Re-renders form with error
        user = db.get_user(admin_user["id"])
        assert user["is_active"] == 1  # Still active

    def test_cannot_remove_own_admin_role(self, logged_in_admin, admin_user, csrf_data):
        data = {**csrf_data, "display_name": "Admin User", "role": "member", "is_active": "1"}
        resp = logged_in_admin.post(f"/admin/users/{admin_user['id']}/edit", data=data)
        assert resp.status_code == 200
        user = db.get_user(admin_user["id"])
        assert user["role"] == "admin"

    def test_reset_password(self, logged_in_admin, member_user, csrf_data):
        resp = logged_in_admin.post(f"/admin/users/{member_user['id']}/reset-password",
                                    data=csrf_data, follow_redirects=False)
        assert resp.status_code == 302
        updated = db.get_user(member_user["id"])
        assert updated["must_change_password"] == 1

    def test_reset_password_404(self, logged_in_admin, csrf_data):
        resp = logged_in_admin.post("/admin/users/9999/reset-password", data=csrf_data)
        assert resp.status_code == 404


class TestDepartmentManagement:
    def test_departments_list(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/departments")
        assert resp.status_code == 200

    def test_create_department(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "name": "New Team", "color": "#00ff00"}
        resp = logged_in_admin.post("/admin/departments/new", data=data, follow_redirects=False)
        assert resp.status_code == 302
        dept = db.get_department(db.list_departments(include_archived=True)[-1]["id"])
        assert dept["name"] == "New Team"

    def test_create_department_missing_name(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "name": ""}
        resp = logged_in_admin.post("/admin/departments/new", data=data)
        assert resp.status_code == 200

    def test_edit_department(self, logged_in_admin, csrf_data):
        dept = db.create_department("Edit Me")
        data = {**csrf_data, "name": "Edited", "color": "#ff0000"}
        resp = logged_in_admin.post(f"/admin/departments/{dept['id']}/edit",
                                    data=data, follow_redirects=False)
        assert resp.status_code == 302
        updated = db.get_department(dept["id"])
        assert updated["name"] == "Edited"

    def test_edit_department_404(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/departments/9999/edit")
        assert resp.status_code == 404

    def test_archive_department(self, logged_in_admin, csrf_data):
        dept = db.create_department("Archive Me")
        data = {**csrf_data, "name": "Archive Me", "is_archived": "1"}
        resp = logged_in_admin.post(f"/admin/departments/{dept['id']}/edit",
                                    data=data, follow_redirects=False)
        assert resp.status_code == 302
        updated = db.get_department(dept["id"])
        assert updated["is_archived"] == 1

    def test_reorder_departments(self, logged_in_admin, csrf_headers):
        depts = db.list_departments(include_archived=True)
        if len(depts) >= 2:
            order = [depts[1]["id"], depts[0]["id"]] + [d["id"] for d in depts[2:]]
            resp = logged_in_admin.put("/admin/departments/reorder",
                                       json={"order": order},
                                       headers=csrf_headers)
            assert resp.status_code == 200

    def test_create_department_with_reporters(self, logged_in_admin, member_user, csrf_data):
        data = {**csrf_data, "name": "Reporter Team",
                "primary_reporter": str(member_user["id"])}
        resp = logged_in_admin.post("/admin/departments/new", data=data, follow_redirects=False)
        assert resp.status_code == 302


class TestSettingsManagement:
    def test_settings_page_renders(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/settings")
        assert resp.status_code == 200

    def test_save_settings(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "presenter.slide_sound": "whoosh",
                "presenter.confetti": "off", "ui.sounds_enabled": "off",
                "ui.sound_volume": "0.5", "markdown.escape": "false",
                "presenter.final_slide_sound": "gong"}
        resp = logged_in_admin.post("/admin/settings", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert db.get_setting("presenter.slide_sound") == "whoosh"
        assert db.get_setting("presenter.confetti") == "off"
        assert db.get_setting("ui.sound_volume") == "0.5"


class TestTemplateManagement:
    def test_templates_list_page(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/templates")
        assert resp.status_code == 200

    def test_template_create_page(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/templates/new")
        assert resp.status_code == 200

    def test_create_template(self, logged_in_admin, csrf_data):
        dept = db.create_department("TestDept")
        data = {**csrf_data, "name": "Weekly", "description": "Standard weekly",
                "departments": [str(dept["id"])]}
        resp = logged_in_admin.post("/admin/templates/new", data=data,
                                     follow_redirects=False)
        assert resp.status_code == 302
        templates = db.list_templates()
        assert len(templates) == 1
        assert templates[0]["name"] == "Weekly"

    def test_create_template_no_name(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "name": ""}
        resp = logged_in_admin.post("/admin/templates/new", data=data)
        assert resp.status_code == 200  # Re-renders form
        assert len(db.list_templates()) == 0

    def test_create_duplicate_template(self, logged_in_admin, admin_user, csrf_data):
        db.create_template("Existing", created_by=admin_user["id"])
        data = {**csrf_data, "name": "Existing"}
        resp = logged_in_admin.post("/admin/templates/new", data=data)
        assert resp.status_code == 200  # Re-renders with error

    def test_edit_template_page(self, logged_in_admin, admin_user):
        tid = db.create_template("Edit Me", created_by=admin_user["id"])
        resp = logged_in_admin.get(f"/admin/templates/{tid}/edit")
        assert resp.status_code == 200
        assert b"Edit Me" in resp.data

    def test_edit_template(self, logged_in_admin, admin_user, csrf_data):
        tid = db.create_template("Old", created_by=admin_user["id"])
        data = {**csrf_data, "name": "New", "description": "Updated"}
        resp = logged_in_admin.post(f"/admin/templates/{tid}/edit", data=data,
                                     follow_redirects=False)
        assert resp.status_code == 302
        template = db.get_template(tid)
        assert template["name"] == "New"

    def test_delete_template(self, logged_in_admin, admin_user, csrf_data):
        tid = db.create_template("Delete Me", created_by=admin_user["id"])
        resp = logged_in_admin.post(f"/admin/templates/{tid}/delete", data=csrf_data,
                                     follow_redirects=False)
        assert resp.status_code == 302
        assert db.get_template(tid) is None

    def test_delete_template_404(self, logged_in_admin, csrf_data):
        resp = logged_in_admin.post("/admin/templates/9999/delete", data=csrf_data)
        assert resp.status_code == 404

    def test_save_template_from_meeting(self, logged_in_admin, csrf_data):
        mid = db.create_meeting("2026-03-01")
        data = {**csrf_data, "meeting_id": str(mid), "name": "From March"}
        resp = logged_in_admin.post("/admin/templates/save-from-meeting", data=data,
                                     follow_redirects=False)
        assert resp.status_code == 302
        templates = db.list_templates()
        assert any(t["name"] == "From March" for t in templates)

    def test_templates_require_admin(self, logged_in_member):
        resp = logged_in_member.get("/admin/templates")
        assert resp.status_code == 403
