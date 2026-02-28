"""Tests for db.py — database layer."""
import db


class TestInitAndMigrations:
    def test_init_db_creates_tables(self, app):
        """init_db should create all tables and run migrations."""
        # init_db is called by create_app, so tables should exist
        conn = db.get_db()
        # Check base tables
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        conn.close()
        assert "meeting" in table_names
        assert "section" in table_names
        assert "todo" in table_names
        assert "user" in table_names
        assert "department" in table_names
        assert "setting" in table_names
        assert "schema_version" in table_names

    def test_migrations_are_idempotent(self, app):
        """Running migrations twice should not fail."""
        db.run_migrations()  # Already ran in init_db, run again
        conn = db.get_db()
        versions = conn.execute("SELECT version FROM schema_version").fetchall()
        conn.close()
        assert len(versions) >= 1


class TestSecretKey:
    def test_get_or_create_secret_key(self, app):
        key1 = db.get_or_create_secret_key()
        key2 = db.get_or_create_secret_key()
        assert key1 == key2
        assert len(key1) == 64  # hex(32 bytes)


class TestUsers:
    def test_create_user(self, app):
        user = db.create_user("alice", "Alice", "password123")
        assert user is not None
        assert user["username"] == "alice"
        assert user["display_name"] == "Alice"
        assert user["role"] == "member"
        assert user["is_active"] == 1

    def test_create_admin_user(self, app):
        user = db.create_user("boss", "Boss", "password123", role="admin")
        assert user["role"] == "admin"

    def test_duplicate_username_fails(self, app):
        db.create_user("alice", "Alice", "password123")
        dup = db.create_user("alice", "Alice 2", "password456")
        assert dup is None

    def test_authenticate_user(self, app):
        db.create_user("alice", "Alice", "password123")
        user = db.authenticate_user("alice", "password123")
        assert user is not None
        assert user["username"] == "alice"

    def test_authenticate_wrong_password(self, app):
        db.create_user("alice", "Alice", "password123")
        user = db.authenticate_user("alice", "wrong")
        assert user is None

    def test_authenticate_nonexistent_user(self, app):
        user = db.authenticate_user("ghost", "password123")
        assert user is None

    def test_authenticate_inactive_user(self, app):
        user = db.create_user("alice", "Alice", "password123")
        db.update_user(user["id"], is_active=False)
        result = db.authenticate_user("alice", "password123")
        assert result is None

    def test_has_any_users(self, app):
        assert not db.has_any_users()
        db.create_user("alice", "Alice", "password123")
        assert db.has_any_users()

    def test_list_users(self, app):
        db.create_user("bob", "Bob", "password123")
        db.create_user("alice", "Alice", "password123")
        users = db.list_users()
        assert len(users) == 2
        # Should be sorted by display_name
        assert users[0]["display_name"] == "Alice"

    def test_update_user(self, app):
        user = db.create_user("alice", "Alice", "password123")
        db.update_user(user["id"], display_name="Alice Smith", role="admin")
        updated = db.get_user(user["id"])
        assert updated["display_name"] == "Alice Smith"
        assert updated["role"] == "admin"

    def test_change_password(self, app):
        user = db.create_user("alice", "Alice", "password123")
        db.change_password(user["id"], "newpassword456")
        assert db.authenticate_user("alice", "newpassword456") is not None
        assert db.authenticate_user("alice", "password123") is None

    def test_reset_password_sets_must_change(self, app):
        user = db.create_user("alice", "Alice", "password123")
        db.reset_password(user["id"], "temppass123")
        updated = db.get_user(user["id"])
        assert updated["must_change_password"] == 1
        assert db.authenticate_user("alice", "temppass123") is not None

    def test_change_password_clears_must_change(self, app):
        user = db.create_user("alice", "Alice", "password123")
        db.reset_password(user["id"], "temppass123")
        db.change_password(user["id"], "finalpass456")
        updated = db.get_user(user["id"])
        assert updated["must_change_password"] == 0

    def test_regenerate_feed_token(self, app):
        user = db.create_user("alice", "Alice", "password123")
        old_token = user["feed_token"]
        new_token = db.regenerate_feed_token(user["id"])
        assert new_token != old_token


class TestDepartments:
    def test_seed_departments_exist(self, app):
        """Migrations should seed default departments."""
        depts = db.list_departments(include_archived=False)
        assert len(depts) >= 7  # We seed 9 default departments

    def test_create_department(self, app):
        dept = db.create_department("New Dept", color="#ff0000", is_special=False)
        assert dept is not None
        assert dept["name"] == "New Dept"
        assert dept["color"] == "#ff0000"

    def test_create_duplicate_department_fails(self, app):
        db.create_department("UniqueTeam")
        dup = db.create_department("UniqueTeam")
        assert dup is None

    def test_update_department(self, app):
        dept = db.create_department("TestDept")
        db.update_department(dept["id"], name="Renamed", is_archived=True)
        updated = db.get_department(dept["id"])
        assert updated["name"] == "Renamed"
        assert updated["is_archived"] == 1

    def test_archived_departments_hidden_by_default(self, app):
        dept = db.create_department("Archive Me")
        db.update_department(dept["id"], is_archived=True)
        active = db.list_departments(include_archived=False)
        all_depts = db.list_departments(include_archived=True)
        active_names = [d["name"] for d in active]
        all_names = [d["name"] for d in all_depts]
        assert "Archive Me" not in active_names
        assert "Archive Me" in all_names

    def test_reorder_departments(self, app):
        d1 = db.create_department("Dept A")
        d2 = db.create_department("Dept B")
        d3 = db.create_department("Dept C")
        db.reorder_departments([d3["id"], d1["id"], d2["id"]])
        updated = db.get_department(d3["id"])
        assert updated["sort_order"] == 0
        updated = db.get_department(d1["id"])
        assert updated["sort_order"] == 1

    def test_department_reporters(self, app):
        dept = db.create_department("Reporters Test")
        u1 = db.create_user("rep1", "Reporter One", "password123")
        u2 = db.create_user("rep2", "Reporter Two", "password123")
        db.set_department_reporters(dept["id"], [(u1["id"], True), (u2["id"], False)])
        reporters = db.get_department_reporters(dept["id"])
        assert len(reporters) == 2
        primary = [r for r in reporters if r["is_primary"]]
        assert len(primary) == 1
        assert primary[0]["username"] == "rep1"

    def test_replace_reporters(self, app):
        dept = db.create_department("Replace Test")
        u1 = db.create_user("rep1", "Reporter One", "password123")
        u2 = db.create_user("rep2", "Reporter Two", "password123")
        db.set_department_reporters(dept["id"], [(u1["id"], True)])
        db.set_department_reporters(dept["id"], [(u2["id"], True)])
        reporters = db.get_department_reporters(dept["id"])
        assert len(reporters) == 1
        assert reporters[0]["username"] == "rep2"


class TestSettings:
    def test_default_settings_seeded(self, app):
        """Migration 003 seeds default settings."""
        settings = db.get_all_settings()
        assert "presenter.slide_sound" in settings
        assert settings["presenter.slide_sound"] == "champagne"
        assert settings["presenter.confetti"] == "on"

    def test_get_setting_default(self, app):
        val = db.get_setting("nonexistent.key", "fallback")
        assert val == "fallback"

    def test_set_setting(self, app):
        db.set_setting("test.key", "test_value")
        assert db.get_setting("test.key") == "test_value"

    def test_set_setting_upsert(self, app):
        db.set_setting("test.key", "val1")
        db.set_setting("test.key", "val2")
        assert db.get_setting("test.key") == "val2"


class TestMeetings:
    def test_create_meeting(self, app):
        mid = db.create_meeting("2026-03-01")
        assert mid is not None
        meeting = db.get_meeting(mid)
        assert meeting["date"] == "2026-03-01"

    def test_create_duplicate_meeting_fails(self, app):
        db.create_meeting("2026-03-01")
        mid2 = db.create_meeting("2026-03-01")
        assert mid2 is None

    def test_meeting_creates_sections_from_departments(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        depts = db.list_departments(include_archived=False)
        assert len(sections) == len(depts)

    def test_copy_meeting(self, app):
        mid1 = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid1)
        db.update_section(sections[0]["id"], "Some content here")
        mid2 = db.create_meeting("2026-03-08", copy_from="2026-03-01")
        sections2 = db.get_sections(mid2)
        assert len(sections2) == len(sections)
        assert sections2[0]["content"] == "Some content here"

    def test_get_latest_meeting(self, app):
        db.create_meeting("2026-03-01")
        db.create_meeting("2026-03-08")
        latest = db.get_latest_meeting()
        assert latest["date"] == "2026-03-08"

    def test_list_meetings_descending(self, app):
        db.create_meeting("2026-03-01")
        db.create_meeting("2026-03-08")
        meetings = db.list_meetings()
        assert meetings[0]["date"] == "2026-03-08"
        assert meetings[1]["date"] == "2026-03-01"

    def test_get_meeting_fill_status(self, app):
        mid = db.create_meeting("2026-03-01")
        filled, total = db.get_meeting_fill_status(mid)
        assert filled == 0
        assert total > 0
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "content")
        filled, total = db.get_meeting_fill_status(mid)
        assert filled == 1


class TestSections:
    def test_get_sections_ordered(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        orders = [s["sort_order"] for s in sections]
        assert orders == sorted(orders)

    def test_update_section(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.update_section(sections[0]["id"], "Updated content")
        section = db.get_section(sections[0]["id"])
        assert section["content"] == "Updated content"
        assert section["updated_at"] is not None


class TestPermissions:
    def test_admin_can_edit_any_section(self, app):
        admin = db.create_user("admin", "Admin", "password123", role="admin")
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        assert db.can_edit_section(admin, sections[0])

    def test_reporter_can_edit_own_section(self, app):
        user = db.create_user("reporter", "Reporter", "password123")
        dept = db.create_department("Test Section")
        db.set_department_reporters(dept["id"], [(user["id"], True)])
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        # Find the section for this department
        section = next(s for s in sections if s["department_id"] == dept["id"])
        assert db.can_edit_section(user, section)

    def test_non_reporter_cannot_edit_section(self, app):
        user = db.create_user("other", "Other", "password123")
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        # User is not a reporter for any seeded department
        assert not db.can_edit_section(user, sections[0])

    def test_backup_reporter_can_edit_section(self, app):
        user = db.create_user("backup", "Backup", "password123")
        dept = db.create_department("Backup Test")
        db.set_department_reporters(dept["id"], [(user["id"], False)])  # backup
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        section = next(s for s in sections if s["department_id"] == dept["id"])
        assert db.can_edit_section(user, section)


class TestTodos:
    def test_add_and_get_todos(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        sid = sections[0]["id"]
        db.add_todo(sid, "First task")
        db.add_todo(sid, "Second task")
        todos = db.get_todos(sid)
        assert len(todos) == 2
        assert todos[0]["text"] == "First task"

    def test_toggle_todo(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Toggle me")
        todos = db.get_todos(sections[0]["id"])
        assert todos[0]["done"] == 0
        db.toggle_todo(todos[0]["id"])
        todo = db.get_todo(todos[0]["id"])
        assert todo["done"] == 1
        db.toggle_todo(todos[0]["id"])
        todo = db.get_todo(todos[0]["id"])
        assert todo["done"] == 0

    def test_delete_todo(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Delete me")
        todos = db.get_todos(sections[0]["id"])
        db.delete_todo(todos[0]["id"])
        assert len(db.get_todos(sections[0]["id"])) == 0

    def test_get_todos_by_meeting(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Task A")
        db.add_todo(sections[1]["id"], "Task B")
        todos_map = db.get_todos_by_meeting(mid)
        assert sections[0]["id"] in todos_map
        assert sections[1]["id"] in todos_map

    def test_get_all_open_todos(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Open task")
        db.add_todo(sections[0]["id"], "Done task")
        todos = db.get_todos(sections[0]["id"])
        db.toggle_todo(todos[1]["id"])
        open_todos = db.get_all_open_todos()
        assert len(open_todos) == 1
        assert open_todos[0]["text"] == "Open task"

    def test_meeting_open_todo_count(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Task 1")
        db.add_todo(sections[0]["id"], "Task 2")
        assert db.get_meeting_open_todo_count(mid) == 2
        todos = db.get_todos(sections[0]["id"])
        db.toggle_todo(todos[0]["id"])
        assert db.get_meeting_open_todo_count(mid) == 1


class TestEnhancedTodos:
    """Phase 2: assignment, due dates, priority, carry-forward."""

    def test_add_todo_with_assignment(self, app):
        user = db.create_user("alice", "Alice", "password123")
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Assigned task",
                    assigned_to=user["id"], created_by=user["id"])
        todos = db.get_todos(sections[0]["id"])
        assert todos[0]["assigned_to"] == user["id"]
        assert todos[0]["assignee_name"] == "Alice"
        assert todos[0]["created_by"] == user["id"]

    def test_add_todo_with_due_date(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Due soon", due_date="2026-03-15")
        todos = db.get_todos(sections[0]["id"])
        assert todos[0]["due_date"] == "2026-03-15"

    def test_add_todo_with_priority(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Urgent", priority="high")
        db.add_todo(sections[0]["id"], "Meh", priority="low")
        todos = db.get_todos(sections[0]["id"])
        assert todos[0]["priority"] == "high"
        assert todos[1]["priority"] == "low"

    def test_invalid_priority_defaults_to_normal(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Bad priority", priority="ULTRA")
        todos = db.get_todos(sections[0]["id"])
        assert todos[0]["priority"] == "normal"

    def test_toggle_sets_completed_at(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Track completion")
        todos = db.get_todos(sections[0]["id"])
        assert todos[0]["completed_at"] is None
        db.toggle_todo(todos[0]["id"])
        todo = db.get_todo(todos[0]["id"])
        assert todo["completed_at"] is not None
        # Untoggle clears completed_at
        db.toggle_todo(todos[0]["id"])
        todo = db.get_todo(todos[0]["id"])
        assert todo["completed_at"] is None

    def test_get_my_todos(self, app):
        user = db.create_user("alice", "Alice", "password123")
        other = db.create_user("bob", "Bob", "password123")
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Alice's task", assigned_to=user["id"])
        db.add_todo(sections[0]["id"], "Bob's task", assigned_to=other["id"])
        db.add_todo(sections[0]["id"], "Unassigned")
        my = db.get_my_todos(user["id"])
        assert len(my) == 1
        assert my[0]["text"] == "Alice's task"

    def test_get_my_todos_include_done(self, app):
        user = db.create_user("alice", "Alice", "password123")
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Done task", assigned_to=user["id"])
        todos = db.get_todos(sections[0]["id"])
        db.toggle_todo(todos[0]["id"])
        assert len(db.get_my_todos(user["id"])) == 0
        assert len(db.get_my_todos(user["id"], include_done=True)) == 1

    def test_filter_by_assignee(self, app):
        user = db.create_user("alice", "Alice", "password123")
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Alice's", assigned_to=user["id"])
        db.add_todo(sections[0]["id"], "Unassigned")
        results = db.get_all_open_todos(assigned_to=user["id"])
        assert len(results) == 1
        assert results[0]["text"] == "Alice's"

    def test_filter_unassigned(self, app):
        user = db.create_user("alice", "Alice", "password123")
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Alice's", assigned_to=user["id"])
        db.add_todo(sections[0]["id"], "Unassigned")
        results = db.get_all_open_todos(assigned_to="unassigned")
        assert len(results) == 1
        assert results[0]["text"] == "Unassigned"

    def test_filter_by_priority(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "High", priority="high")
        db.add_todo(sections[0]["id"], "Normal", priority="normal")
        results = db.get_all_open_todos(priority="high")
        assert len(results) == 1
        assert results[0]["text"] == "High"

    def test_filter_include_done(self, app):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        db.add_todo(sections[0]["id"], "Open")
        db.add_todo(sections[0]["id"], "Done")
        todos = db.get_todos(sections[0]["id"])
        db.toggle_todo(todos[1]["id"])
        results_open = db.get_all_open_todos(include_done=False)
        results_all = db.get_all_open_todos(include_done=True)
        assert len(results_open) == 1
        assert len(results_all) == 2

    def test_carry_forward(self, app):
        mid1 = db.create_meeting("2026-03-01")
        mid2 = db.create_meeting("2026-03-08")
        sections1 = db.get_sections(mid1)
        user = db.create_user("alice", "Alice", "password123")
        db.add_todo(sections1[0]["id"], "Carry me",
                    assigned_to=user["id"], priority="high", due_date="2026-03-15")
        todos = db.get_todos(sections1[0]["id"])
        new_id = db.carry_forward_todo(todos[0]["id"], mid2)
        assert new_id is not None
        # Original marked done
        original = db.get_todo(todos[0]["id"])
        assert original["done"] == 1
        assert original["completed_at"] is not None
        # New todo created in target meeting
        new_todo = db.get_todo(new_id)
        assert new_todo["text"] == "Carry me"
        assert new_todo["assigned_to"] == user["id"]
        assert new_todo["priority"] == "high"
        assert new_todo["due_date"] == "2026-03-15"

    def test_carry_forward_nonexistent_todo(self, app):
        mid = db.create_meeting("2026-03-01")
        result = db.carry_forward_todo(9999, mid)
        assert result is None

    def test_carry_forward_no_matching_section(self, app):
        """If target meeting has no matching section, carry-forward returns None."""
        mid1 = db.create_meeting("2026-03-01")
        sections1 = db.get_sections(mid1)
        db.add_todo(sections1[0]["id"], "Orphan task")
        todos = db.get_todos(sections1[0]["id"])
        # Create a meeting with no sections (edge case: manually create empty meeting)
        conn = db.get_db()
        conn.execute("INSERT INTO meeting (date, created_at) VALUES ('2026-04-01', '2026-04-01')")
        conn.commit()
        empty_meeting = conn.execute("SELECT * FROM meeting WHERE date = '2026-04-01'").fetchone()
        conn.close()
        result = db.carry_forward_todo(todos[0]["id"], empty_meeting["id"])
        assert result is None


class TestMeetingLifecycle:
    """Phase 3: meeting lock/unlock."""

    def test_lock_meeting(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        assert not db.is_meeting_locked(mid)
        result = db.lock_meeting(mid, admin_user["id"])
        assert result is True
        assert db.is_meeting_locked(mid)
        meeting = db.get_meeting(mid)
        assert meeting["status"] == "locked"
        assert meeting["locked_by"] == admin_user["id"]
        assert meeting["locked_at"] is not None

    def test_lock_already_locked(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.lock_meeting(mid, admin_user["id"])
        result = db.lock_meeting(mid, admin_user["id"])
        assert result is True  # Idempotent

    def test_unlock_meeting(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.lock_meeting(mid, admin_user["id"])
        result = db.unlock_meeting(mid)
        assert result is True
        assert not db.is_meeting_locked(mid)
        meeting = db.get_meeting(mid)
        assert meeting["status"] == "open"
        assert meeting["locked_by"] is None

    def test_lock_nonexistent(self, app, admin_user):
        assert db.lock_meeting(9999, admin_user["id"]) is False

    def test_unlock_nonexistent(self, app):
        assert db.unlock_meeting(9999) is False

    def test_locked_meeting_blocks_section_edit(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        sections = db.get_sections(mid)
        # Admin can edit when unlocked
        assert db.can_edit_section(admin_user, sections[0]) is True
        db.lock_meeting(mid, admin_user["id"])
        # Refresh section
        section = db.get_section(sections[0]["id"])
        assert db.can_edit_section(admin_user, section) is False

    def test_is_meeting_locked_nonexistent(self, app):
        assert db.is_meeting_locked(9999) is False


class TestTemplates:
    """Phase 3: meeting templates."""

    def test_create_template(self, app, admin_user):
        tid = db.create_template("Weekly Standup", description="Standard format",
                                 created_by=admin_user["id"])
        assert tid is not None
        template = db.get_template(tid)
        assert template["name"] == "Weekly Standup"
        assert template["description"] == "Standard format"
        assert template["created_by"] == admin_user["id"]

    def test_create_template_with_departments(self, app, admin_user):
        dept1 = db.create_department("TestDeptAlpha")
        dept2 = db.create_department("TestDeptBeta")
        tid = db.create_template("Full", created_by=admin_user["id"],
                                 department_ids=[dept1["id"], dept2["id"]])
        sections = db.get_template_sections(tid)
        assert len(sections) == 2
        assert sections[0]["department_name"] == "TestDeptAlpha"
        assert sections[1]["department_name"] == "TestDeptBeta"
        assert sections[0]["sort_order"] == 0
        assert sections[1]["sort_order"] == 1

    def test_create_duplicate_template(self, app, admin_user):
        db.create_template("Unique", created_by=admin_user["id"])
        result = db.create_template("Unique", created_by=admin_user["id"])
        assert result is None

    def test_list_templates(self, app, admin_user):
        db.create_template("Template A", created_by=admin_user["id"])
        db.create_template("Template B", created_by=admin_user["id"])
        templates = db.list_templates()
        assert len(templates) == 2
        # Should have creator_name from JOIN
        assert templates[0]["creator_name"] is not None

    def test_update_template(self, app, admin_user):
        tid = db.create_template("Old Name", created_by=admin_user["id"])
        result = db.update_template(tid, name="New Name", description="Updated")
        assert result is True
        template = db.get_template(tid)
        assert template["name"] == "New Name"
        assert template["description"] == "Updated"

    def test_update_template_departments(self, app, admin_user):
        dept1 = db.create_department("Dept A")
        dept2 = db.create_department("Dept B")
        tid = db.create_template("Test", created_by=admin_user["id"],
                                 department_ids=[dept1["id"]])
        sections = db.get_template_sections(tid)
        assert len(sections) == 1
        db.update_template(tid, department_ids=[dept2["id"]])
        sections = db.get_template_sections(tid)
        assert len(sections) == 1
        assert sections[0]["department_name"] == "Dept B"

    def test_delete_template(self, app, admin_user):
        tid = db.create_template("Deleteme", created_by=admin_user["id"])
        db.delete_template(tid)
        assert db.get_template(tid) is None

    def test_save_template_from_meeting(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        tid = db.save_template_from_meeting(mid, "From Meeting",
                                            created_by=admin_user["id"])
        assert tid is not None
        template = db.get_template(tid)
        assert template["name"] == "From Meeting"
        sections = db.get_template_sections(tid)
        # Should have sections from the meeting
        assert len(sections) > 0

    def test_create_meeting_from_template(self, app, admin_user):
        dept = db.create_department("TemplateDeptX")
        tid = db.create_template("Custom", created_by=admin_user["id"],
                                 department_ids=[dept["id"]])
        mid = db.create_meeting_from_template("2026-04-01", tid)
        assert mid is not None
        meeting = db.get_meeting(mid)
        assert meeting["template_id"] == tid
        sections = db.get_sections(mid)
        assert len(sections) == 1
        assert sections[0]["name"] == "TemplateDeptX"

    def test_create_meeting_from_template_duplicate_date(self, app, admin_user):
        dept = db.create_department("Eng")
        tid = db.create_template("T", created_by=admin_user["id"],
                                 department_ids=[dept["id"]])
        db.create_meeting("2026-04-01")
        mid = db.create_meeting_from_template("2026-04-01", tid)
        assert mid is None  # Duplicate date


class TestAttendance:
    """Phase 3: attendance tracking."""

    def test_set_and_get_attendance(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.set_attendance(mid, admin_user["id"], "present")
        att = db.get_attendance(mid)
        assert len(att) == 1
        assert att[0]["user_id"] == admin_user["id"]
        assert att[0]["status"] == "present"
        assert att[0]["display_name"] == admin_user["display_name"]

    def test_update_attendance(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.set_attendance(mid, admin_user["id"], "present")
        db.set_attendance(mid, admin_user["id"], "remote")
        att = db.get_attendance(mid)
        assert len(att) == 1
        assert att[0]["status"] == "remote"

    def test_remove_attendance(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.set_attendance(mid, admin_user["id"], "present")
        db.remove_attendance(mid, admin_user["id"])
        att = db.get_attendance(mid)
        assert len(att) == 0

    def test_get_attendance_for_user(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        assert db.get_attendance_for_user(mid, admin_user["id"]) is None
        db.set_attendance(mid, admin_user["id"], "present")
        record = db.get_attendance_for_user(mid, admin_user["id"])
        assert record is not None
        assert record["status"] == "present"

    def test_invalid_attendance_status(self, app, admin_user):
        mid = db.create_meeting("2026-03-01")
        db.set_attendance(mid, admin_user["id"], "invalid")
        att = db.get_attendance(mid)
        assert att[0]["status"] == "present"  # Falls back to present

    def test_multiple_attendees(self, app, admin_user, member_user):
        mid = db.create_meeting("2026-03-01")
        db.set_attendance(mid, admin_user["id"], "present")
        db.set_attendance(mid, member_user["id"], "remote")
        att = db.get_attendance(mid)
        assert len(att) == 2
