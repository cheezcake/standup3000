"""Tests for meeting routes."""
import db


class TestMeetingRoutes:
    def test_index_redirect_no_meetings(self, logged_in_admin):
        resp = logged_in_admin.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/meetings" in resp.headers["Location"]

    def test_index_redirect_to_latest(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_admin.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert f"/meeting/{mid}" in resp.headers["Location"]

    def test_meetings_list(self, logged_in_admin):
        db.create_meeting("2026-03-01")
        resp = logged_in_admin.get("/meetings")
        assert resp.status_code == 200
        assert b"2026-03-01" in resp.data

    def test_meeting_view(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_admin.get(f"/meeting/{mid}")
        assert resp.status_code == 200
        assert b"2026-03-01" in resp.data

    def test_meeting_view_404(self, logged_in_admin):
        resp = logged_in_admin.get("/meeting/9999")
        assert resp.status_code == 404

    def test_meeting_new_page(self, logged_in_admin):
        resp = logged_in_admin.get("/meeting/new")
        assert resp.status_code == 200

    def test_create_meeting(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "date": "2026-03-15"}
        resp = logged_in_admin.post("/meeting/new", data=data, follow_redirects=False)
        assert resp.status_code == 302
        meeting = db.get_meeting_by_date("2026-03-15")
        assert meeting is not None

    def test_create_duplicate_meeting_redirects(self, logged_in_admin, csrf_data):
        db.create_meeting("2026-03-15")
        data = {**csrf_data, "date": "2026-03-15"}
        resp = logged_in_admin.post("/meeting/new", data=data, follow_redirects=False)
        assert resp.status_code == 302

    def test_create_meeting_empty_date(self, logged_in_admin, csrf_data):
        data = {**csrf_data, "date": ""}
        resp = logged_in_admin.post("/meeting/new", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert db.get_latest_meeting() is None


class TestPresenterMode:
    def test_presenter_page_renders(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_admin.get(f"/meeting/{mid}/present")
        assert resp.status_code == 200
        assert b"Presenting" in resp.data

    def test_presenter_404(self, logged_in_admin):
        resp = logged_in_admin.get("/meeting/9999/present")
        assert resp.status_code == 404

    def test_presenter_includes_settings(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        db.set_setting("presenter.slide_sound", "whoosh")
        resp = logged_in_admin.get(f"/meeting/{mid}/present")
        assert b"whoosh" in resp.data


class TestMeetingLock:
    def test_lock_meeting_as_admin(self, logged_in_admin, csrf_data):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_admin.post(f"/meeting/{mid}/lock", data=csrf_data,
                                     follow_redirects=False)
        assert resp.status_code == 302
        assert db.is_meeting_locked(mid)

    def test_unlock_meeting_as_admin(self, logged_in_admin, admin_user, csrf_data):
        mid = db.create_meeting("2026-03-01")
        db.lock_meeting(mid, admin_user["id"])
        resp = logged_in_admin.post(f"/meeting/{mid}/unlock", data=csrf_data,
                                     follow_redirects=False)
        assert resp.status_code == 302
        assert not db.is_meeting_locked(mid)

    def test_lock_requires_admin(self, logged_in_member, csrf_data):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_member.post(f"/meeting/{mid}/lock", data=csrf_data)
        assert resp.status_code == 403

    def test_unlock_requires_admin(self, logged_in_member, admin_user, csrf_data):
        mid = db.create_meeting("2026-03-01")
        db.lock_meeting(mid, admin_user["id"])
        resp = logged_in_member.post(f"/meeting/{mid}/unlock", data=csrf_data)
        assert resp.status_code == 403

    def test_lock_404(self, logged_in_admin, csrf_data):
        resp = logged_in_admin.post("/meeting/9999/lock", data=csrf_data)
        assert resp.status_code == 404

    def test_locked_meeting_shows_banner(self, logged_in_admin, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.lock_meeting(mid, admin_user["id"])
        resp = logged_in_admin.get(f"/meeting/{mid}")
        assert b"locked" in resp.data.lower()

    def test_locked_meeting_blocks_todo_add(self, logged_in_admin, admin_user, csrf_data):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.lock_meeting(mid, admin_user["id"])
        data = {**csrf_data, "text": "Should fail"}
        resp = logged_in_admin.post(f"/section/{sections[0]['id']}/todos", data=data)
        assert resp.status_code == 403

    def test_locked_meeting_blocks_section_edit(self, logged_in_admin, admin_user):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.lock_meeting(mid, admin_user["id"])
        resp = logged_in_admin.get(f"/section/{sections[0]['id']}/edit")
        assert resp.status_code == 403


class TestAttendanceRoute:
    def test_get_attendance(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_admin.get(f"/meeting/{mid}/attendance")
        assert resp.status_code == 200

    def test_update_attendance_as_admin(self, logged_in_admin, admin_user, csrf_headers):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_admin.put(
            f"/meeting/{mid}/attendance",
            json={"user_id": admin_user["id"], "status": "present"},
            headers=csrf_headers,
        )
        assert resp.status_code == 200
        att = db.get_attendance(mid)
        assert len(att) == 1

    def test_update_attendance_remove(self, logged_in_admin, admin_user, csrf_headers):
        mid = db.create_meeting("2026-03-01")
        db.set_attendance(mid, admin_user["id"], "present")
        resp = logged_in_admin.put(
            f"/meeting/{mid}/attendance",
            json={"user_id": admin_user["id"], "status": "none"},
            headers=csrf_headers,
        )
        assert resp.status_code == 200
        att = db.get_attendance(mid)
        assert len(att) == 0

    def test_update_attendance_requires_admin(self, logged_in_member, member_user, csrf_headers):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_member.put(
            f"/meeting/{mid}/attendance",
            json={"user_id": member_user["id"], "status": "present"},
            headers=csrf_headers,
        )
        assert resp.status_code == 403

    def test_attendance_404(self, logged_in_admin):
        resp = logged_in_admin.get("/meeting/9999/attendance")
        assert resp.status_code == 404

    def test_meeting_view_shows_attendance(self, logged_in_admin, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.set_attendance(mid, admin_user["id"], "present")
        resp = logged_in_admin.get(f"/meeting/{mid}")
        assert admin_user["display_name"].encode() in resp.data


class TestMeetingWithTemplate:
    def test_create_meeting_from_template(self, logged_in_admin, admin_user, csrf_data):
        dept = db.create_department("TestDept")
        tid = db.create_template("TestTemplate", created_by=admin_user["id"],
                                 department_ids=[dept["id"]])
        data = {**csrf_data, "date": "2026-04-15", "template_id": str(tid)}
        resp = logged_in_admin.post("/meeting/new", data=data, follow_redirects=False)
        assert resp.status_code == 302
        meeting = db.get_meeting_by_date("2026-04-15")
        assert meeting is not None
        sections = db.get_sections(meeting["id"])
        assert len(sections) == 1
        assert sections[0]["name"] == "TestDept"
