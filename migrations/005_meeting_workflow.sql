-- Phase 3: Meeting Workflow — lifecycle, templates, attendance

-- Meeting lifecycle
ALTER TABLE meeting ADD COLUMN status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE meeting ADD COLUMN locked_by INTEGER REFERENCES user(id);
ALTER TABLE meeting ADD COLUMN locked_at TEXT;
ALTER TABLE meeting ADD COLUMN template_id INTEGER REFERENCES meeting_template(id);

-- Meeting templates
CREATE TABLE IF NOT EXISTS meeting_template (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_by  INTEGER REFERENCES user(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_section (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id     INTEGER NOT NULL REFERENCES meeting_template(id) ON DELETE CASCADE,
    department_id   INTEGER NOT NULL REFERENCES department(id),
    sort_order      INTEGER NOT NULL,
    default_content TEXT NOT NULL DEFAULT ''
);

-- Attendance tracking
CREATE TABLE IF NOT EXISTS meeting_attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES user(id),
    status      TEXT NOT NULL DEFAULT 'present',
    UNIQUE(meeting_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_attendance_meeting ON meeting_attendance(meeting_id);
