"""Tests for section HTMX routes and permissions."""
import db


class TestSectionView:
    def test_section_view(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        resp = logged_in_admin.get(f"/section/{sections[0]['id']}")
        assert resp.status_code == 200

    def test_section_view_404(self, logged_in_admin):
        resp = logged_in_admin.get("/section/9999")
        assert resp.status_code == 404


class TestSectionEdit:
    def test_section_edit_as_admin(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        resp = logged_in_admin.get(f"/section/{sections[0]['id']}/edit")
        assert resp.status_code == 200
        assert b"textarea" in resp.data

    def test_section_edit_403_for_non_reporter(self, logged_in_member):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        resp = logged_in_member.get(f"/section/{sections[0]['id']}/edit")
        assert resp.status_code == 403

    def test_section_edit_allowed_for_reporter(self, client, csrf_data):
        user = db.create_user("reporter", "Reporter", "password123")
        dept = db.create_department("My Section")
        db.set_department_reporters(dept["id"], [(user["id"], True)])
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        my_section = next(s for s in sections if s["department_id"] == dept["id"])

        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]
            sess["_csrf_token"] = "test-csrf-token"

        resp = client.get(f"/section/{my_section['id']}/edit")
        assert resp.status_code == 200

    def test_section_edit_404(self, logged_in_admin):
        resp = logged_in_admin.get("/section/9999/edit")
        assert resp.status_code == 404


class TestSectionSave:
    def test_section_save_as_admin(self, logged_in_admin, csrf_headers):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        resp = logged_in_admin.put(f"/section/{sections[0]['id']}",
                                   data={"content": "Updated content"},
                                   headers=csrf_headers)
        assert resp.status_code == 200
        section = db.get_section(sections[0]["id"])
        assert section["content"] == "Updated content"

    def test_section_save_403_for_non_reporter(self, logged_in_member, csrf_headers):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        resp = logged_in_member.put(f"/section/{sections[0]['id']}",
                                    data={"content": "Unauthorized"},
                                    headers=csrf_headers)
        assert resp.status_code == 403

    def test_section_save_404(self, logged_in_admin, csrf_headers):
        resp = logged_in_admin.put("/section/9999",
                                   data={"content": "test"},
                                   headers=csrf_headers)
        assert resp.status_code == 404
