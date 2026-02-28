import sqlite3
import os
import glob as globmod
import logging
from datetime import datetime
from html import escape as html_escape
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("STANDUP3000_DB", os.path.join(os.path.dirname(__file__), "data", "meetings.db"))
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

# Fallback sections if department table is empty (shouldn't happen after migration 002)
DEFAULT_SECTIONS = [
    ("Engineering", "", False),
    ("Design", "", False),
    ("Product", "", False),
    ("QA", "", False),
    ("Infrastructure", "", False),
    ("Support", "", False),
    ("Operations", "", False),
    ("PTO / Out of Office", "", True),
    ("Shoutouts", "", True),
]


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


# --- Schema & Migrations ---

def init_db():
    """Initialize database: create base tables, then run migrations."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = get_db()
    # Base v1 schema (idempotent)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meeting (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS section (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER NOT NULL REFERENCES meeting(id),
            name TEXT NOT NULL,
            reporter TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL,
            is_special INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS todo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL REFERENCES section(id),
            text TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
    """)
    db.commit()
    db.close()
    # Restrict database file permissions
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    run_migrations()


def run_migrations():
    """Apply pending SQL migrations from migrations/ directory."""
    db = get_db()
    applied = set()
    try:
        rows = db.execute("SELECT version FROM schema_version").fetchall()
        applied = {r["version"] for r in rows}
    except sqlite3.OperationalError:
        pass

    migration_files = sorted(globmod.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    for fpath in migration_files:
        fname = os.path.basename(fpath)
        version = int(fname.split("_")[0])
        if version in applied:
            continue
        with open(fpath) as f:
            sql = f.read()
        try:
            db.executescript(sql)
            db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, datetime.utcnow().isoformat()),
            )
            db.commit()
        except Exception as e:
            db.rollback()
            raise RuntimeError(f"Migration {fname} failed: {e}") from e

    db.close()


# --- Secret Key ---

def get_or_create_secret_key():
    """Return the app secret key, creating it on first run."""
    key_path = os.path.join(os.path.dirname(DB_PATH), ".secret_key")
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(key_path, "w") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    return key


# --- Users ---

def has_any_users():
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM user").fetchone()[0]
    db.close()
    return count > 0


def create_user(username, display_name, password, role="member", email=None):
    db = get_db()
    now = datetime.utcnow().isoformat()
    password_hash = generate_password_hash(password)
    feed_token = secrets.token_hex(16)
    try:
        db.execute(
            """INSERT INTO user (username, display_name, email, password_hash, role, feed_token, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (username, display_name, email, password_hash, role, feed_token, now),
        )
        db.commit()
        user = db.execute("SELECT * FROM user WHERE username = ?", (username,)).fetchone()
        db.close()
        return user
    except sqlite3.IntegrityError:
        db.close()
        return None


def get_user(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
    db.close()
    return user


def get_user_by_username(username):
    db = get_db()
    user = db.execute("SELECT * FROM user WHERE username = ?", (username,)).fetchone()
    db.close()
    return user


def authenticate_user(username, password):
    """Return user row if credentials valid, else None."""
    user = get_user_by_username(username)
    if not user:
        return None
    if not user["is_active"]:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    # Update last_login
    db = get_db()
    db.execute("UPDATE user SET last_login = ? WHERE id = ?", (datetime.utcnow().isoformat(), user["id"]))
    db.commit()
    db.close()
    return user


def list_users():
    db = get_db()
    users = db.execute("SELECT * FROM user ORDER BY display_name").fetchall()
    db.close()
    return users


def list_active_users():
    db = get_db()
    users = db.execute("SELECT * FROM user WHERE is_active = 1 ORDER BY display_name").fetchall()
    db.close()
    return users


def update_user(user_id, display_name=None, email=None, role=None, is_active=None):
    db = get_db()
    fields = []
    values = []
    if display_name is not None:
        fields.append("display_name = ?")
        values.append(display_name)
    if email is not None:
        fields.append("email = ?")
        values.append(email if email else None)
    if role is not None:
        fields.append("role = ?")
        values.append(role)
    if is_active is not None:
        fields.append("is_active = ?")
        values.append(int(is_active))
    if not fields:
        db.close()
        return
    values.append(user_id)
    db.execute(f"UPDATE user SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    db.close()


def change_password(user_id, new_password):
    db = get_db()
    password_hash = generate_password_hash(new_password)
    db.execute(
        "UPDATE user SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (password_hash, user_id),
    )
    db.commit()
    db.close()


def reset_password(user_id, temp_password):
    db = get_db()
    password_hash = generate_password_hash(temp_password)
    db.execute(
        "UPDATE user SET password_hash = ?, must_change_password = 1 WHERE id = ?",
        (password_hash, user_id),
    )
    db.commit()
    db.close()


def regenerate_feed_token(user_id):
    db = get_db()
    token = secrets.token_hex(16)
    db.execute("UPDATE user SET feed_token = ? WHERE id = ?", (token, user_id))
    db.commit()
    db.close()
    return token


# --- Departments ---

def list_departments(include_archived=False):
    db = get_db()
    if include_archived:
        departments = db.execute("SELECT * FROM department ORDER BY sort_order").fetchall()
    else:
        departments = db.execute(
            "SELECT * FROM department WHERE is_archived = 0 ORDER BY sort_order"
        ).fetchall()
    db.close()
    return departments


def get_department(dept_id):
    db = get_db()
    dept = db.execute("SELECT * FROM department WHERE id = ?", (dept_id,)).fetchone()
    db.close()
    return dept


def create_department(name, color=None, is_special=False):
    db = get_db()
    now = datetime.utcnow().isoformat()
    max_order = db.execute("SELECT COALESCE(MAX(sort_order), -1) FROM department").fetchone()[0]
    try:
        db.execute(
            "INSERT INTO department (name, color, sort_order, is_special, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, color, max_order + 1, int(is_special), now),
        )
        db.commit()
        dept = db.execute("SELECT * FROM department WHERE name = ?", (name,)).fetchone()
        db.close()
        return dept
    except sqlite3.IntegrityError:
        db.close()
        return None


def update_department(dept_id, name=None, color=None, is_special=None, is_archived=None):
    db = get_db()
    fields = []
    values = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if color is not None:
        fields.append("color = ?")
        values.append(color)
    if is_special is not None:
        fields.append("is_special = ?")
        values.append(int(is_special))
    if is_archived is not None:
        fields.append("is_archived = ?")
        values.append(int(is_archived))
    if not fields:
        db.close()
        return
    values.append(dept_id)
    db.execute(f"UPDATE department SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    db.close()


def reorder_departments(dept_ids):
    """Set sort_order based on position in the list."""
    db = get_db()
    for i, dept_id in enumerate(dept_ids):
        db.execute("UPDATE department SET sort_order = ? WHERE id = ?", (i, dept_id))
    db.commit()
    db.close()


def get_department_reporters(dept_id):
    """Return list of user rows assigned as reporters for a department."""
    db = get_db()
    reporters = db.execute(
        """SELECT u.*, dr.is_primary
           FROM department_reporter dr
           JOIN user u ON dr.user_id = u.id
           WHERE dr.department_id = ?
           ORDER BY dr.is_primary DESC, u.display_name""",
        (dept_id,),
    ).fetchall()
    db.close()
    return reporters


def set_department_reporters(dept_id, reporter_entries):
    """Replace all reporters for a department.
    reporter_entries: list of (user_id, is_primary) tuples
    """
    db = get_db()
    db.execute("DELETE FROM department_reporter WHERE department_id = ?", (dept_id,))
    for user_id, is_primary in reporter_entries:
        db.execute(
            "INSERT INTO department_reporter (department_id, user_id, is_primary) VALUES (?, ?, ?)",
            (dept_id, user_id, int(is_primary)),
        )
    db.commit()
    db.close()


# --- Settings ---

def get_setting(key, default=None):
    db = get_db()
    row = db.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    db.close()
    if row:
        return row["value"]
    return default


def get_all_settings():
    db = get_db()
    rows = db.execute("SELECT key, value FROM setting ORDER BY key").fetchall()
    db.close()
    return {r["key"]: r["value"] for r in rows}


def set_setting(key, value):
    db = get_db()
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, now),
    )
    db.commit()
    db.close()


# --- Meetings ---

def create_meeting(meeting_date, copy_from=None):
    db = get_db()
    now = datetime.utcnow().isoformat()
    try:
        db.execute("INSERT INTO meeting (date, created_at) VALUES (?, ?)", (meeting_date, now))
        meeting = db.execute("SELECT * FROM meeting WHERE date = ?", (meeting_date,)).fetchone()

        if copy_from:
            prev = db.execute("SELECT * FROM meeting WHERE date = ?", (copy_from,)).fetchone()
            if prev:
                prev_sections = db.execute(
                    "SELECT * FROM section WHERE meeting_id = ? ORDER BY sort_order", (prev["id"],)
                ).fetchall()
                for s in prev_sections:
                    db.execute(
                        """INSERT INTO section (meeting_id, name, reporter, sort_order, is_special,
                           content, department_id, reporter_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (meeting["id"], s["name"], s["reporter"], s["sort_order"],
                         s["is_special"], s["content"], s["department_id"], s["reporter_id"]),
                    )
                db.commit()
                db.close()
                return meeting["id"]

        # Create sections from department table
        departments = db.execute(
            "SELECT * FROM department WHERE is_archived = 0 ORDER BY sort_order"
        ).fetchall()

        if departments:
            for dept in departments:
                # Get primary reporter display name
                reporter_row = db.execute(
                    """SELECT u.display_name, u.id FROM department_reporter dr
                       JOIN user u ON dr.user_id = u.id
                       WHERE dr.department_id = ? AND dr.is_primary = 1
                       LIMIT 1""",
                    (dept["id"],),
                ).fetchone()
                reporter_name = reporter_row["display_name"] if reporter_row else ""
                reporter_id = reporter_row["id"] if reporter_row else None
                db.execute(
                    """INSERT INTO section (meeting_id, name, reporter, sort_order, is_special,
                       content, department_id, reporter_id)
                       VALUES (?, ?, ?, ?, ?, '', ?, ?)""",
                    (meeting["id"], dept["name"], reporter_name, dept["sort_order"],
                     dept["is_special"], dept["id"], reporter_id),
                )
        else:
            # Fallback for fresh installs before departments are seeded
            for i, (name, reporter, is_special) in enumerate(DEFAULT_SECTIONS):
                db.execute(
                    "INSERT INTO section (meeting_id, name, reporter, sort_order, is_special, content) VALUES (?, ?, ?, ?, ?, '')",
                    (meeting["id"], name, reporter, i, int(is_special)),
                )

        db.commit()
        mid = meeting["id"]
    except sqlite3.IntegrityError:
        mid = None
    db.close()
    return mid


def get_meeting(meeting_id):
    db = get_db()
    meeting = db.execute("SELECT * FROM meeting WHERE id = ?", (meeting_id,)).fetchone()
    db.close()
    return meeting


def get_meeting_by_date(meeting_date):
    db = get_db()
    meeting = db.execute("SELECT * FROM meeting WHERE date = ?", (meeting_date,)).fetchone()
    db.close()
    return meeting


def get_latest_meeting():
    db = get_db()
    meeting = db.execute("SELECT * FROM meeting ORDER BY date DESC LIMIT 1").fetchone()
    db.close()
    return meeting


def list_meetings():
    db = get_db()
    meetings = db.execute("SELECT * FROM meeting ORDER BY date DESC").fetchall()
    db.close()
    return meetings


# --- Sections ---

def get_sections(meeting_id):
    db = get_db()
    sections = db.execute(
        "SELECT * FROM section WHERE meeting_id = ? ORDER BY sort_order", (meeting_id,)
    ).fetchall()
    db.close()
    return sections


def get_section(section_id):
    db = get_db()
    section = db.execute("SELECT * FROM section WHERE id = ?", (section_id,)).fetchone()
    db.close()
    return section


def update_section(section_id, content):
    db = get_db()
    now = datetime.utcnow().isoformat()
    db.execute("UPDATE section SET content = ?, updated_at = ? WHERE id = ?", (content, now, section_id))
    # Update search index
    _update_section_index(db, section_id)
    db.commit()
    db.close()


def _update_section_index(db, section_id):
    """Update the FTS5 search index for a section."""
    try:
        db.execute("DELETE FROM search_index WHERE type = 'section' AND source_id = ?",
                   (str(section_id),))
        section = db.execute("SELECT * FROM section WHERE id = ?", (section_id,)).fetchone()
        if section and section["content"]:
            meeting = db.execute("SELECT * FROM meeting WHERE id = ?",
                                 (section["meeting_id"],)).fetchone()
            if meeting:
                db.execute(
                    """INSERT INTO search_index (type, source_id, meeting_id, meeting_date,
                       section_name, reporter, content)
                       VALUES ('section', ?, ?, ?, ?, ?, ?)""",
                    (str(section_id), str(meeting["id"]), meeting["date"],
                     section["name"], section["reporter"], section["content"]),
                )
    except Exception as e:
        logger.debug("FTS index update (section) skipped: %s", e)


def can_edit_section(user, section):
    """Check if a user has permission to edit a section.

    Returns False if the meeting is locked (regardless of role).
    """
    # Check meeting lock status
    if is_meeting_locked(section["meeting_id"]):
        return False
    if user["role"] == "admin":
        return True
    if section["reporter_id"] and section["reporter_id"] == user["id"]:
        return True
    if section["department_id"]:
        db = get_db()
        is_reporter = db.execute(
            "SELECT 1 FROM department_reporter WHERE department_id = ? AND user_id = ?",
            (section["department_id"], user["id"]),
        ).fetchone()
        db.close()
        if is_reporter:
            return True
    return False


def get_meeting_fill_status(meeting_id):
    """Return count of sections with content for a meeting."""
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM section WHERE meeting_id = ?", (meeting_id,)).fetchone()[0]
    filled = db.execute(
        "SELECT COUNT(*) FROM section WHERE meeting_id = ? AND content != ''", (meeting_id,)
    ).fetchone()[0]
    db.close()
    return filled, total


# --- Todos ---

def get_todos(section_id):
    db = get_db()
    todos = db.execute(
        """SELECT t.*, u.display_name as assignee_name
           FROM todo t
           LEFT JOIN user u ON t.assigned_to = u.id
           WHERE t.section_id = ?
           ORDER BY t.done, t.created_at""",
        (section_id,),
    ).fetchall()
    db.close()
    return todos


def get_todo(todo_id):
    db = get_db()
    todo = db.execute("SELECT * FROM todo WHERE id = ?", (todo_id,)).fetchone()
    db.close()
    return todo


def add_todo(section_id, text, assigned_to=None, due_date=None, priority="normal", created_by=None):
    db = get_db()
    now = datetime.utcnow().isoformat()
    if priority not in ("low", "normal", "high"):
        priority = "normal"
    db.execute(
        """INSERT INTO todo (section_id, text, assigned_to, due_date, priority, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (section_id, text, assigned_to, due_date, priority, created_by, now),
    )
    todo_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    _update_todo_index(db, todo_id)
    db.commit()
    db.close()


def toggle_todo(todo_id):
    db = get_db()
    todo = db.execute("SELECT done FROM todo WHERE id = ?", (todo_id,)).fetchone()
    if not todo:
        db.close()
        return
    now = datetime.utcnow().isoformat()
    if todo["done"]:
        # Uncomplete
        db.execute("UPDATE todo SET done = 0, completed_at = NULL WHERE id = ?", (todo_id,))
    else:
        # Complete
        db.execute("UPDATE todo SET done = 1, completed_at = ? WHERE id = ?", (now, todo_id))
    db.commit()
    db.close()


def delete_todo(todo_id):
    db = get_db()
    try:
        db.execute("DELETE FROM search_index WHERE type = 'todo' AND source_id = ?",
                   (str(todo_id),))
    except Exception as e:
        logger.debug("FTS index delete (todo) skipped: %s", e)
    db.execute("DELETE FROM todo WHERE id = ?", (todo_id,))
    db.commit()
    db.close()


def get_todos_by_meeting(meeting_id):
    """Return todos grouped by section_id for a meeting."""
    db = get_db()
    todos = db.execute(
        """SELECT t.* FROM todo t
           JOIN section s ON t.section_id = s.id
           WHERE s.meeting_id = ?
           ORDER BY t.done, t.created_at""",
        (meeting_id,),
    ).fetchall()
    db.close()
    result = {}
    for t in todos:
        sid = t["section_id"]
        if sid not in result:
            result[sid] = []
        result[sid].append(t)
    return result


def get_all_open_todos(assigned_to=None, priority=None, overdue_only=False, include_done=False):
    """Return todos with meeting and section info for the dashboard.

    Filters:
        assigned_to: user ID or 'unassigned'
        priority: 'low', 'normal', 'high'
        overdue_only: only items past due_date
        include_done: if True, return all items (not just open)
    """
    db = get_db()
    conditions = []
    params = []

    if not include_done:
        conditions.append("t.done = 0")

    if assigned_to == "unassigned":
        conditions.append("t.assigned_to IS NULL")
    elif assigned_to:
        conditions.append("t.assigned_to = ?")
        params.append(assigned_to)

    if priority:
        conditions.append("t.priority = ?")
        params.append(priority)

    if overdue_only:
        conditions.append("t.due_date IS NOT NULL AND t.due_date < date('now') AND t.done = 0")

    where = " AND ".join(conditions) if conditions else "1=1"

    todos = db.execute(
        f"""SELECT t.id, t.text, t.done, t.created_at, t.assigned_to,
                   t.due_date, t.priority, t.completed_at, t.created_by,
                   s.id as section_id, s.name as section_name, s.reporter,
                   m.id as meeting_id, m.date as meeting_date,
                   u.display_name as assignee_name
            FROM todo t
            JOIN section s ON t.section_id = s.id
            JOIN meeting m ON s.meeting_id = m.id
            LEFT JOIN user u ON t.assigned_to = u.id
            WHERE {where}
            ORDER BY m.date DESC, s.sort_order, t.created_at""",
        params,
    ).fetchall()
    db.close()
    return todos


def get_my_todos(user_id, include_done=False):
    """Return todos assigned to a specific user, across all meetings."""
    db = get_db()
    done_filter = "" if include_done else "AND t.done = 0"
    todos = db.execute(
        f"""SELECT t.*, s.name as section_name, s.reporter,
                   m.id as meeting_id, m.date as meeting_date
            FROM todo t
            JOIN section s ON t.section_id = s.id
            JOIN meeting m ON s.meeting_id = m.id
            WHERE t.assigned_to = ? {done_filter}
            ORDER BY
                CASE WHEN t.due_date IS NOT NULL AND t.due_date < date('now') THEN 0 ELSE 1 END,
                t.due_date IS NULL,
                t.due_date,
                CASE t.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                t.created_at""",
        (user_id,),
    ).fetchall()
    db.close()
    return todos


def carry_forward_todo(todo_id, target_meeting_id):
    """Copy a todo to the corresponding section in the target meeting, mark original done.

    Returns the new todo ID or None if the section doesn't exist in the target meeting.
    """
    db = get_db()
    original = db.execute("SELECT * FROM todo WHERE id = ?", (todo_id,)).fetchone()
    if not original:
        db.close()
        return None

    # Find the original section's department
    orig_section = db.execute("SELECT * FROM section WHERE id = ?", (original["section_id"],)).fetchone()
    if not orig_section:
        db.close()
        return None

    # Find matching section in target meeting (by department_id or name fallback)
    target_section = None
    if orig_section["department_id"]:
        target_section = db.execute(
            "SELECT * FROM section WHERE meeting_id = ? AND department_id = ?",
            (target_meeting_id, orig_section["department_id"]),
        ).fetchone()
    if not target_section:
        target_section = db.execute(
            "SELECT * FROM section WHERE meeting_id = ? AND name = ?",
            (target_meeting_id, orig_section["name"]),
        ).fetchone()
    if not target_section:
        db.close()
        return None

    now = datetime.utcnow().isoformat()

    # Create new todo in target section
    db.execute(
        """INSERT INTO todo (section_id, text, assigned_to, due_date, priority, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (target_section["id"], original["text"], original["assigned_to"],
         original["due_date"], original["priority"], original["created_by"], now),
    )
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Mark original as done
    db.execute("UPDATE todo SET done = 1, completed_at = ? WHERE id = ?", (now, todo_id))

    db.commit()
    db.close()
    return new_id


def get_meeting_open_todo_count(meeting_id):
    db = get_db()
    count = db.execute(
        """SELECT COUNT(*) FROM todo t
           JOIN section s ON t.section_id = s.id
           WHERE s.meeting_id = ? AND t.done = 0""",
        (meeting_id,),
    ).fetchone()[0]
    db.close()
    return count


# --- Meeting Lifecycle ---

def lock_meeting(meeting_id, user_id):
    """Lock a meeting so it becomes read-only. Returns True on success."""
    db = get_db()
    meeting = db.execute("SELECT * FROM meeting WHERE id = ?", (meeting_id,)).fetchone()
    if not meeting:
        db.close()
        return False
    if meeting["status"] == "locked":
        db.close()
        return True  # Already locked
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE meeting SET status = 'locked', locked_by = ?, locked_at = ? WHERE id = ?",
        (user_id, now, meeting_id),
    )
    db.commit()
    db.close()
    return True


def unlock_meeting(meeting_id):
    """Unlock a locked meeting. Returns True on success."""
    db = get_db()
    meeting = db.execute("SELECT * FROM meeting WHERE id = ?", (meeting_id,)).fetchone()
    if not meeting:
        db.close()
        return False
    db.execute(
        "UPDATE meeting SET status = 'open', locked_by = NULL, locked_at = NULL WHERE id = ?",
        (meeting_id,),
    )
    db.commit()
    db.close()
    return True


def is_meeting_locked(meeting_id):
    """Check if a meeting is locked."""
    db = get_db()
    meeting = db.execute("SELECT status FROM meeting WHERE id = ?", (meeting_id,)).fetchone()
    db.close()
    if not meeting:
        return False
    return meeting["status"] == "locked"


# --- Meeting Templates ---

def create_template(name, description="", created_by=None, department_ids=None):
    """Create a meeting template with optional section definitions.

    department_ids: list of department IDs in desired order.
    """
    db = get_db()
    now = datetime.utcnow().isoformat()
    try:
        db.execute(
            "INSERT INTO meeting_template (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
            (name, description, created_by, now),
        )
        template = db.execute("SELECT * FROM meeting_template WHERE name = ?", (name,)).fetchone()
        if department_ids:
            for i, dept_id in enumerate(department_ids):
                db.execute(
                    "INSERT INTO template_section (template_id, department_id, sort_order) VALUES (?, ?, ?)",
                    (template["id"], dept_id, i),
                )
        db.commit()
        tid = template["id"]
    except sqlite3.IntegrityError:
        db.rollback()
        db.close()
        return None
    db.close()
    return tid


def save_template_from_meeting(meeting_id, name, description="", created_by=None):
    """Save the section layout of an existing meeting as a template."""
    db = get_db()
    now = datetime.utcnow().isoformat()
    sections = db.execute(
        "SELECT * FROM section WHERE meeting_id = ? ORDER BY sort_order",
        (meeting_id,),
    ).fetchall()
    try:
        db.execute(
            "INSERT INTO meeting_template (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
            (name, description, created_by, now),
        )
        template = db.execute("SELECT * FROM meeting_template WHERE name = ?", (name,)).fetchone()
        for s in sections:
            dept_id = s["department_id"]
            if not dept_id:
                continue  # Skip sections without departments
            db.execute(
                "INSERT INTO template_section (template_id, department_id, sort_order, default_content) VALUES (?, ?, ?, ?)",
                (template["id"], dept_id, s["sort_order"], s["content"]),
            )
        db.commit()
        tid = template["id"]
    except sqlite3.IntegrityError:
        db.rollback()
        db.close()
        return None
    db.close()
    return tid


def get_template(template_id):
    db = get_db()
    template = db.execute("SELECT * FROM meeting_template WHERE id = ?", (template_id,)).fetchone()
    db.close()
    return template


def get_template_sections(template_id):
    """Return template sections with department info."""
    db = get_db()
    sections = db.execute(
        """SELECT ts.*, d.name as department_name, d.is_special, d.color
           FROM template_section ts
           JOIN department d ON ts.department_id = d.id
           WHERE ts.template_id = ?
           ORDER BY ts.sort_order""",
        (template_id,),
    ).fetchall()
    db.close()
    return sections


def list_templates():
    db = get_db()
    templates = db.execute(
        """SELECT t.*, u.display_name as creator_name
           FROM meeting_template t
           LEFT JOIN user u ON t.created_by = u.id
           ORDER BY t.name""",
    ).fetchall()
    db.close()
    return templates


def update_template(template_id, name=None, description=None, department_ids=None):
    """Update template metadata and optionally replace sections."""
    db = get_db()
    fields = []
    values = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if description is not None:
        fields.append("description = ?")
        values.append(description)
    if fields:
        values.append(template_id)
        try:
            db.execute(f"UPDATE meeting_template SET {', '.join(fields)} WHERE id = ?", values)
        except sqlite3.IntegrityError:
            db.rollback()
            db.close()
            return False
    if department_ids is not None:
        db.execute("DELETE FROM template_section WHERE template_id = ?", (template_id,))
        for i, dept_id in enumerate(department_ids):
            db.execute(
                "INSERT INTO template_section (template_id, department_id, sort_order) VALUES (?, ?, ?)",
                (template_id, dept_id, i),
            )
    db.commit()
    db.close()
    return True


def delete_template(template_id):
    db = get_db()
    db.execute("DELETE FROM meeting_template WHERE id = ?", (template_id,))
    db.commit()
    db.close()


def create_meeting_from_template(meeting_date, template_id):
    """Create a meeting using a template's section layout."""
    db = get_db()
    now = datetime.utcnow().isoformat()
    try:
        db.execute(
            "INSERT INTO meeting (date, created_at, template_id) VALUES (?, ?, ?)",
            (meeting_date, now, template_id),
        )
        meeting = db.execute("SELECT * FROM meeting WHERE date = ?", (meeting_date,)).fetchone()

        template_sections = db.execute(
            "SELECT * FROM template_section WHERE template_id = ? ORDER BY sort_order",
            (template_id,),
        ).fetchall()

        for ts in template_sections:
            dept = db.execute("SELECT * FROM department WHERE id = ?", (ts["department_id"],)).fetchone()
            if not dept or dept["is_archived"]:
                continue
            # Get primary reporter
            reporter_row = db.execute(
                """SELECT u.display_name, u.id FROM department_reporter dr
                   JOIN user u ON dr.user_id = u.id
                   WHERE dr.department_id = ? AND dr.is_primary = 1
                   LIMIT 1""",
                (dept["id"],),
            ).fetchone()
            reporter_name = reporter_row["display_name"] if reporter_row else ""
            reporter_id = reporter_row["id"] if reporter_row else None
            db.execute(
                """INSERT INTO section (meeting_id, name, reporter, sort_order, is_special,
                   content, department_id, reporter_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (meeting["id"], dept["name"], reporter_name, ts["sort_order"],
                 dept["is_special"], ts["default_content"], dept["id"], reporter_id),
            )

        db.commit()
        mid = meeting["id"]
    except sqlite3.IntegrityError:
        db.rollback()
        mid = None
    db.close()
    return mid


# --- Attendance ---

def set_attendance(meeting_id, user_id, status="present"):
    """Set or update attendance for a user at a meeting.

    status: 'present', 'absent', or 'remote'
    """
    if status not in ("present", "absent", "remote"):
        status = "present"
    db = get_db()
    db.execute(
        """INSERT INTO meeting_attendance (meeting_id, user_id, status)
           VALUES (?, ?, ?)
           ON CONFLICT(meeting_id, user_id) DO UPDATE SET status = excluded.status""",
        (meeting_id, user_id, status),
    )
    db.commit()
    db.close()


def remove_attendance(meeting_id, user_id):
    """Remove attendance record (user not tracked for this meeting)."""
    db = get_db()
    db.execute(
        "DELETE FROM meeting_attendance WHERE meeting_id = ? AND user_id = ?",
        (meeting_id, user_id),
    )
    db.commit()
    db.close()


def get_attendance(meeting_id):
    """Return attendance records for a meeting with user info."""
    db = get_db()
    rows = db.execute(
        """SELECT ma.*, u.display_name, u.username
           FROM meeting_attendance ma
           JOIN user u ON ma.user_id = u.id
           WHERE ma.meeting_id = ?
           ORDER BY u.display_name""",
        (meeting_id,),
    ).fetchall()
    db.close()
    return rows


def get_attendance_for_user(meeting_id, user_id):
    """Return a single attendance record or None."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM meeting_attendance WHERE meeting_id = ? AND user_id = ?",
        (meeting_id, user_id),
    ).fetchone()
    db.close()
    return row


# --- Search Index Helpers ---

def _update_todo_index(db, todo_id):
    """Update the FTS5 search index for a todo item."""
    try:
        db.execute("DELETE FROM search_index WHERE type = 'todo' AND source_id = ?",
                   (str(todo_id),))
        todo = db.execute("SELECT * FROM todo WHERE id = ?", (todo_id,)).fetchone()
        if todo:
            section = db.execute("SELECT * FROM section WHERE id = ?",
                                 (todo["section_id"],)).fetchone()
            if section:
                meeting = db.execute("SELECT * FROM meeting WHERE id = ?",
                                     (section["meeting_id"],)).fetchone()
                if meeting:
                    db.execute(
                        """INSERT INTO search_index (type, source_id, meeting_id, meeting_date,
                           section_name, reporter, content)
                           VALUES ('todo', ?, ?, ?, ?, ?, ?)""",
                        (str(todo_id), str(meeting["id"]), meeting["date"],
                         section["name"], section["reporter"], todo["text"]),
                    )
    except Exception as e:
        logger.debug("FTS index update (todo) skipped: %s", e)


def rebuild_search_index():
    """Rebuild the entire FTS5 search index from scratch."""
    db = get_db()
    try:
        db.execute("DELETE FROM search_index")
        db.execute(
            """INSERT INTO search_index (type, source_id, meeting_id, meeting_date,
               section_name, reporter, content)
               SELECT 'section', s.id, m.id, m.date, s.name, s.reporter, s.content
               FROM section s JOIN meeting m ON s.meeting_id = m.id
               WHERE s.content != ''"""
        )
        db.execute(
            """INSERT INTO search_index (type, source_id, meeting_id, meeting_date,
               section_name, reporter, content)
               SELECT 'todo', t.id, m.id, m.date, s.name, s.reporter, t.text
               FROM todo t
               JOIN section s ON t.section_id = s.id
               JOIN meeting m ON s.meeting_id = m.id"""
        )
        db.commit()
    except Exception:
        db.rollback()
    db.close()


# --- Full-Text Search ---

def search(query, limit=50):
    """Search across sections and todos using FTS5.

    Returns list of dicts with: type, source_id, meeting_id, meeting_date,
    section_name, reporter, snippet.
    """
    if not query or not query.strip():
        return []
    db = get_db()
    try:
        # FTS5 query — escape special chars for safety
        safe_query = query.strip().replace('"', '""')
        # Use Unicode private-use-area placeholders so we can HTML-escape
        # the surrounding content and then restore only the mark tags
        _MARK_OPEN = "\ue000"
        _MARK_CLOSE = "\ue001"
        results = db.execute(
            """SELECT type, source_id, meeting_id, meeting_date, section_name, reporter,
                      snippet(search_index, 6, ?, ?, '...', 40) as snippet,
                      rank
               FROM search_index
               WHERE search_index MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (_MARK_OPEN, _MARK_CLOSE, f'"{safe_query}"', limit),
        ).fetchall()
        db.close()
        sanitized = []
        for r in results:
            d = dict(r)
            s = html_escape(d.get("snippet") or "")
            s = s.replace(html_escape(_MARK_OPEN), "<mark>").replace(html_escape(_MARK_CLOSE), "</mark>")
            d["snippet"] = s
            sanitized.append(d)
        return sanitized
    except Exception:
        db.close()
        return []


# --- Analytics ---

def analytics_kpis():
    """Return the four KPI metrics for the analytics dashboard."""
    db = get_db()

    # Total meetings
    total_meetings = db.execute("SELECT COUNT(*) FROM meeting").fetchone()[0]
    # Meetings this month
    meetings_this_month = db.execute(
        "SELECT COUNT(*) FROM meeting WHERE date >= date('now', 'start of month')"
    ).fetchone()[0]

    # Fill rate across last 10 meetings
    last_10 = db.execute(
        "SELECT id FROM meeting ORDER BY date DESC LIMIT 10"
    ).fetchall()
    if last_10:
        ids = [r["id"] for r in last_10]
        placeholders = ",".join("?" * len(ids))
        total_sections = db.execute(
            f"SELECT COUNT(*) FROM section WHERE meeting_id IN ({placeholders})", ids
        ).fetchone()[0]
        filled_sections = db.execute(
            f"SELECT COUNT(*) FROM section WHERE meeting_id IN ({placeholders}) AND content != ''", ids
        ).fetchone()[0]
        fill_rate = round(filled_sections / total_sections * 100) if total_sections else 0
    else:
        fill_rate = 0

    # Previous 10 fill rate for trend
    prev_10 = db.execute(
        "SELECT id FROM meeting ORDER BY date DESC LIMIT 10 OFFSET 10"
    ).fetchall()
    if prev_10:
        prev_ids = [r["id"] for r in prev_10]
        pp = ",".join("?" * len(prev_ids))
        pt = db.execute(
            f"SELECT COUNT(*) FROM section WHERE meeting_id IN ({pp})", prev_ids
        ).fetchone()[0]
        pf = db.execute(
            f"SELECT COUNT(*) FROM section WHERE meeting_id IN ({pp}) AND content != ''", prev_ids
        ).fetchone()[0]
        prev_fill_rate = round(pf / pt * 100) if pt else 0
    else:
        prev_fill_rate = None

    # Open action items
    open_todos = db.execute("SELECT COUNT(*) FROM todo WHERE done = 0").fetchone()[0]
    overdue_todos = db.execute(
        "SELECT COUNT(*) FROM todo WHERE done = 0 AND due_date IS NOT NULL AND due_date < date('now')"
    ).fetchone()[0]

    # Average close time (days from created_at to completed_at)
    avg_row = db.execute(
        """SELECT AVG(julianday(completed_at) - julianday(created_at)) as avg_days
           FROM todo WHERE done = 1 AND completed_at IS NOT NULL"""
    ).fetchone()
    avg_close_days = round(avg_row["avg_days"], 1) if avg_row["avg_days"] else None

    db.close()
    return {
        "total_meetings": total_meetings,
        "meetings_this_month": meetings_this_month,
        "fill_rate": fill_rate,
        "fill_rate_trend": "up" if prev_fill_rate is not None and fill_rate > prev_fill_rate
                           else "down" if prev_fill_rate is not None and fill_rate < prev_fill_rate
                           else "flat",
        "open_todos": open_todos,
        "overdue_todos": overdue_todos,
        "avg_close_days": avg_close_days,
    }


def analytics_fill_rate(limit=20):
    """Return per-meeting fill rate data for the time series chart."""
    db = get_db()
    meetings = db.execute(
        "SELECT id, date FROM meeting ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    result = []
    for m in reversed(meetings):
        total = db.execute(
            "SELECT COUNT(*) FROM section WHERE meeting_id = ?", (m["id"],)
        ).fetchone()[0]
        filled = db.execute(
            "SELECT COUNT(*) FROM section WHERE meeting_id = ? AND content != ''", (m["id"],)
        ).fetchone()[0]
        regular_total = db.execute(
            "SELECT COUNT(*) FROM section WHERE meeting_id = ? AND is_special = 0", (m["id"],)
        ).fetchone()[0]
        regular_filled = db.execute(
            "SELECT COUNT(*) FROM section WHERE meeting_id = ? AND is_special = 0 AND content != ''",
            (m["id"],)
        ).fetchone()[0]
        result.append({
            "date": m["date"],
            "fill_pct": round(filled / total * 100) if total else 0,
            "regular_pct": round(regular_filled / regular_total * 100) if regular_total else 0,
        })
    db.close()
    return result


def analytics_velocity(weeks=12):
    """Return weekly created/completed action item counts."""
    db = get_db()
    result = []
    for i in range(weeks - 1, -1, -1):
        created = db.execute(
            """SELECT COUNT(*) FROM todo
               WHERE date(created_at) >= date('now', ?)
               AND date(created_at) < date('now', ?)""",
            (f"-{i*7+6} days", f"-{i*7-1} days"),
        ).fetchone()[0]
        completed = db.execute(
            """SELECT COUNT(*) FROM todo
               WHERE completed_at IS NOT NULL
               AND date(completed_at) >= date('now', ?)
               AND date(completed_at) < date('now', ?)""",
            (f"-{i*7+6} days", f"-{i*7-1} days"),
        ).fetchone()[0]
        result.append({
            "week_start": f"-{i}w",
            "created": created,
            "completed": completed,
        })
    db.close()
    return result


def analytics_heatmap(limit=15):
    """Return section fill heatmap: departments x meetings."""
    db = get_db()
    meetings = db.execute(
        "SELECT id, date FROM meeting ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    meetings = list(reversed(meetings))

    departments = db.execute(
        "SELECT id, name, is_special FROM department WHERE is_archived = 0 ORDER BY sort_order"
    ).fetchall()

    matrix = []
    for dept in departments:
        row = {"department": dept["name"], "is_special": bool(dept["is_special"]), "cells": []}
        for m in meetings:
            section = db.execute(
                "SELECT content FROM section WHERE meeting_id = ? AND department_id = ?",
                (m["id"], dept["id"]),
            ).fetchone()
            if section is None:
                status = "missing"
            elif section["content"]:
                status = "filled"
            else:
                status = "empty"
            row["cells"].append({"date": m["date"], "status": status})
        matrix.append(row)
    db.close()
    return {"meetings": [m["date"] for m in meetings], "departments": matrix}


def analytics_by_assignee():
    """Return open action items grouped by assignee with priority breakdown."""
    db = get_db()
    rows = db.execute(
        """SELECT u.display_name as name, t.priority, COUNT(*) as count
           FROM todo t
           LEFT JOIN user u ON t.assigned_to = u.id
           WHERE t.done = 0
           GROUP BY t.assigned_to, t.priority
           ORDER BY COUNT(*) DESC"""
    ).fetchall()
    db.close()

    # Group by assignee
    assignees = {}
    for r in rows:
        name = r["name"] or "Unassigned"
        if name not in assignees:
            assignees[name] = {"high": 0, "normal": 0, "low": 0, "total": 0}
        assignees[name][r["priority"]] += r["count"]
        assignees[name]["total"] += r["count"]

    # Sort by total descending
    return sorted(assignees.items(), key=lambda x: x[1]["total"], reverse=True)


def analytics_stale(days=14):
    """Return action items open longer than `days` days."""
    db = get_db()
    rows = db.execute(
        """SELECT t.id, t.text, t.created_at, t.due_date, t.priority,
                  u.display_name as assignee_name,
                  s.name as section_name,
                  m.date as meeting_date,
                  CAST(julianday('now') - julianday(t.created_at) AS INTEGER) as age_days
           FROM todo t
           JOIN section s ON t.section_id = s.id
           JOIN meeting m ON s.meeting_id = m.id
           LEFT JOIN user u ON t.assigned_to = u.id
           WHERE t.done = 0
           AND julianday('now') - julianday(t.created_at) >= ?
           ORDER BY t.created_at ASC""",
        (days,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def analytics_activity(limit=20):
    """Return recent activity: section edits, todos created/completed/deleted.

    Note: since we don't have a dedicated activity log, we approximate from
    updated_at/created_at/completed_at timestamps.
    """
    db = get_db()
    activities = []

    # Recent section edits
    edits = db.execute(
        """SELECT s.name as section_name, s.updated_at, m.date as meeting_date,
                  s.reporter as actor
           FROM section s
           JOIN meeting m ON s.meeting_id = m.id
           WHERE s.updated_at IS NOT NULL AND s.content != ''
           ORDER BY s.updated_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    for e in edits:
        activities.append({
            "type": "section_edit",
            "text": f"Updated {e['section_name']}",
            "actor": e["actor"] or "Someone",
            "meeting_date": e["meeting_date"],
            "timestamp": e["updated_at"],
        })

    # Recent todos created
    created = db.execute(
        """SELECT t.text, t.created_at, u.display_name as actor,
                  s.name as section_name, m.date as meeting_date
           FROM todo t
           JOIN section s ON t.section_id = s.id
           JOIN meeting m ON s.meeting_id = m.id
           LEFT JOIN user u ON t.created_by = u.id
           ORDER BY t.created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    for c in created:
        activities.append({
            "type": "todo_created",
            "text": f"Created: {c['text'][:50]}",
            "actor": c["actor"] or "Someone",
            "meeting_date": c["meeting_date"],
            "timestamp": c["created_at"],
        })

    # Recent todos completed
    completed = db.execute(
        """SELECT t.text, t.completed_at, u.display_name as actor,
                  s.name as section_name, m.date as meeting_date
           FROM todo t
           JOIN section s ON t.section_id = s.id
           JOIN meeting m ON s.meeting_id = m.id
           LEFT JOIN user u ON t.assigned_to = u.id
           WHERE t.completed_at IS NOT NULL
           ORDER BY t.completed_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    for c in completed:
        activities.append({
            "type": "todo_completed",
            "text": f"Completed: {c['text'][:50]}",
            "actor": c["actor"] or "Someone",
            "meeting_date": c["meeting_date"],
            "timestamp": c["completed_at"],
        })

    # Sort all by timestamp descending, take top N
    activities.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return activities[:limit]


# --- Export ---

def get_meeting_as_markdown(meeting_id):
    """Export a meeting as a Markdown string."""
    db = get_db()
    meeting = db.execute("SELECT * FROM meeting WHERE id = ?", (meeting_id,)).fetchone()
    if not meeting:
        db.close()
        return None

    sections = db.execute(
        "SELECT * FROM section WHERE meeting_id = ? ORDER BY sort_order",
        (meeting_id,),
    ).fetchall()

    lines = [f"# Standup — {meeting['date']}", ""]

    # Attendance
    attendance = db.execute(
        """SELECT u.display_name, ma.status
           FROM meeting_attendance ma
           JOIN user u ON ma.user_id = u.id
           WHERE ma.meeting_id = ?
           ORDER BY u.display_name""",
        (meeting_id,),
    ).fetchall()
    if attendance:
        present = [a["display_name"] for a in attendance if a["status"] == "present"]
        remote = [a["display_name"] for a in attendance if a["status"] == "remote"]
        absent = [a["display_name"] for a in attendance if a["status"] == "absent"]
        if present:
            lines.append(f"**Present:** {', '.join(present)}")
        if remote:
            lines.append(f"**Remote:** {', '.join(remote)}")
        if absent:
            lines.append(f"**Absent:** {', '.join(absent)}")
        lines.append("")

    for section in sections:
        prefix = "## " if not section["is_special"] else "### "
        lines.append(f"{prefix}{section['name']}")
        if section["reporter"]:
            lines.append(f"*Reporter: {section['reporter']}*")
        lines.append("")
        if section["content"]:
            lines.append(section["content"])
        else:
            lines.append("*No notes.*")
        lines.append("")

        # Todos for this section
        todos = db.execute(
            "SELECT * FROM todo WHERE section_id = ? ORDER BY done, created_at",
            (section["id"],),
        ).fetchall()
        if todos:
            lines.append("**Action Items:**")
            for t in todos:
                check = "x" if t["done"] else " "
                extra = ""
                if t["priority"] == "high":
                    extra += " [HIGH]"
                if t["due_date"]:
                    extra += f" (due {t['due_date']})"
                lines.append(f"- [{check}] {t['text']}{extra}")
            lines.append("")

    db.close()
    return "\n".join(lines)
