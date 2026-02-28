"""Tests for Phase 4: Search, Analytics, and Export."""
import json
import db


# --- DB-level search tests ---

class TestSearchDB:
    def test_search_returns_section_content(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Deployed the new widget feature")
        results = db.search("widget")
        assert len(results) >= 1
        assert results[0]["type"] == "section"
        assert "widget" in results[0]["snippet"].lower()

    def test_search_returns_todo_content(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Investigate the frobulator issue")
        results = db.search("frobulator")
        assert len(results) >= 1
        assert results[0]["type"] == "todo"

    def test_search_empty_query(self, app):
        results = db.search("")
        assert results == []

    def test_search_no_results(self, app):
        db.create_meeting("2026-03-01")
        results = db.search("xyznonexistent999")
        assert results == []

    def test_search_includes_meeting_date(self, app):
        mid = db.create_meeting("2026-04-10")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Quarterly revenue review")
        results = db.search("revenue")
        assert len(results) >= 1
        assert results[0]["meeting_date"] == "2026-04-10"

    def test_rebuild_search_index(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Alpha bravo charlie")
        # Rebuild should repopulate
        db.rebuild_search_index()
        results = db.search("bravo")
        assert len(results) >= 1


# --- Search route tests ---

class TestSearchRoute:
    def test_search_page_loads(self, logged_in_admin):
        resp = logged_in_admin.get("/search")
        assert resp.status_code == 200
        assert b"Search" in resp.data

    def test_search_with_query(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Deployed the new rocketship")
        resp = logged_in_admin.get("/search?q=rocketship")
        assert resp.status_code == 200
        assert b"rocketship" in resp.data.lower()

    def test_search_no_results(self, logged_in_admin):
        resp = logged_in_admin.get("/search?q=zzzznonexistent")
        assert resp.status_code == 200
        assert b"0 result" in resp.data

    def test_search_empty_query(self, logged_in_admin):
        resp = logged_in_admin.get("/search?q=")
        assert resp.status_code == 200


# --- Export tests ---

class TestExportDB:
    def test_markdown_export_basic(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Some notes here")
        md = db.get_meeting_as_markdown(mid)
        assert md is not None
        assert "# Standup — 2026-03-01" in md
        assert "Some notes here" in md

    def test_markdown_export_includes_todos(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Fix the bug", priority="high")
        md = db.get_meeting_as_markdown(mid)
        assert "Fix the bug" in md
        assert "[HIGH]" in md

    def test_markdown_export_includes_attendance(self, app):
        mid = db.create_meeting("2026-03-01")
        user = db.create_user("alice", "Alice", "pass123")
        db.set_attendance(mid, user["id"], "present")
        md = db.get_meeting_as_markdown(mid)
        assert "Alice" in md
        assert "Present" in md

    def test_markdown_export_nonexistent(self, app):
        md = db.get_meeting_as_markdown(9999)
        assert md is None


class TestExportRoute:
    def test_export_markdown_download(self, logged_in_admin):
        mid = db.create_meeting("2026-03-01")
        resp = logged_in_admin.get(f"/meeting/{mid}/export/markdown")
        assert resp.status_code == 200
        assert resp.mimetype == "text/markdown"
        assert b"# Standup" in resp.data
        assert "attachment" in resp.headers.get("Content-Disposition", "")

    def test_export_markdown_404(self, logged_in_admin):
        resp = logged_in_admin.get("/meeting/9999/export/markdown")
        assert resp.status_code == 404


# --- Analytics DB tests ---

class TestAnalyticsDB:
    def test_kpis_basic(self, app):
        db.create_meeting("2026-03-01")
        kpis = db.analytics_kpis()
        assert kpis["total_meetings"] == 1
        assert "fill_rate" in kpis
        assert "open_todos" in kpis
        assert "overdue_todos" in kpis
        assert "avg_close_days" in kpis

    def test_kpis_with_todos(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Open task")
        kpis = db.analytics_kpis()
        assert kpis["open_todos"] >= 1

    def test_fill_rate_data(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Filled in")
        data = db.analytics_fill_rate()
        assert len(data) >= 1
        assert "date" in data[0]
        assert "fill_pct" in data[0]
        assert "regular_pct" in data[0]

    def test_velocity_data(self, app):
        data = db.analytics_velocity(weeks=4)
        assert len(data) == 4
        assert "created" in data[0]
        assert "completed" in data[0]

    def test_heatmap_no_meetings(self, app):
        data = db.analytics_heatmap()
        assert "meetings" in data
        assert "departments" in data

    def test_heatmap_with_data(self, app):
        db.create_meeting("2026-03-01")
        data = db.analytics_heatmap()
        assert len(data["meetings"]) >= 1
        assert len(data["departments"]) >= 1
        assert "cells" in data["departments"][0]

    def test_by_assignee(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        user = db.create_user("alice", "Alice", "pass123")
        db.add_todo(sections[0]["id"], "Task for Alice", assigned_to=user["id"])
        data = db.analytics_by_assignee()
        assert len(data) >= 1
        names = [item[0] for item in data]
        assert "Alice" in names

    def test_stale_no_stale(self, app):
        data = db.analytics_stale()
        assert isinstance(data, list)

    def test_activity_empty(self, app):
        data = db.analytics_activity()
        assert isinstance(data, list)

    def test_activity_with_data(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Updated content")
        user = db.create_user("bob", "Bob", "pass123")
        db.add_todo(sections[0]["id"], "New task", created_by=user["id"])
        data = db.analytics_activity()
        assert len(data) >= 1
        types = {a["type"] for a in data}
        assert "section_edit" in types or "todo_created" in types


# --- Analytics route tests ---

class TestAnalyticsRoutes:
    def test_analytics_dashboard_loads(self, logged_in_admin):
        resp = logged_in_admin.get("/analytics")
        assert resp.status_code == 200
        assert b"Mission Control" in resp.data

    def test_api_kpis(self, logged_in_admin):
        db.create_meeting("2026-03-01")
        resp = logged_in_admin.get("/api/analytics/kpis",
                                   headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "total_meetings" in data
        assert data["total_meetings"] >= 1

    def test_api_fill_rate(self, logged_in_admin):
        db.create_meeting("2026-03-01")
        resp = logged_in_admin.get("/api/analytics/fill-rate",
                                   headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_api_velocity(self, logged_in_admin):
        resp = logged_in_admin.get("/api/analytics/velocity",
                                   headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)

    def test_api_heatmap(self, logged_in_admin):
        db.create_meeting("2026-03-01")
        resp = logged_in_admin.get("/api/analytics/heatmap",
                                   headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "meetings" in data
        assert "departments" in data

    def test_api_by_assignee(self, logged_in_admin):
        resp = logged_in_admin.get("/api/analytics/by-assignee",
                                   headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)

    def test_api_stale(self, logged_in_admin):
        resp = logged_in_admin.get("/api/analytics/stale",
                                   headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)

    def test_api_activity(self, logged_in_admin):
        resp = logged_in_admin.get("/api/analytics/activity",
                                   headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data, list)

    def test_analytics_requires_login(self, client):
        resp = client.get("/analytics", follow_redirects=False)
        assert resp.status_code == 302

    def test_api_kpis_requires_login(self, client):
        resp = client.get("/api/analytics/kpis")
        assert resp.status_code == 302
