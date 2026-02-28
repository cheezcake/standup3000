-- Migration 002: Dynamic departments (replaces hardcoded DEFAULT_SECTIONS)
-- Adds department table, department_reporter junction, and links sections to departments

CREATE TABLE IF NOT EXISTS department (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    color           TEXT,
    sort_order      INTEGER NOT NULL,
    is_special      INTEGER NOT NULL DEFAULT 0,
    is_archived     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS department_reporter (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id   INTEGER NOT NULL REFERENCES department(id),
    user_id         INTEGER NOT NULL REFERENCES user(id),
    is_primary      INTEGER NOT NULL DEFAULT 1,
    UNIQUE(department_id, user_id)
);

-- Add department linkage to existing section table
ALTER TABLE section ADD COLUMN department_id INTEGER REFERENCES department(id);
ALTER TABLE section ADD COLUMN reporter_id INTEGER REFERENCES user(id);

-- Seed default departments (generic — customize via Admin > Departments)
INSERT INTO department (name, color, sort_order, is_special, created_at) VALUES
    ('Engineering',         NULL, 0,  0, datetime('now')),
    ('Design',              NULL, 1,  0, datetime('now')),
    ('Product',             NULL, 2,  0, datetime('now')),
    ('QA',                  NULL, 3,  0, datetime('now')),
    ('Infrastructure',      NULL, 4,  0, datetime('now')),
    ('Support',             NULL, 5,  0, datetime('now')),
    ('Operations',          NULL, 6,  0, datetime('now')),
    ('PTO / Out of Office', NULL, 7,  1, datetime('now')),
    ('Shoutouts',           NULL, 8,  1, datetime('now'));

-- Backfill department_id on existing sections by matching name
UPDATE section SET department_id = (
    SELECT d.id FROM department d WHERE d.name = section.name
) WHERE department_id IS NULL;
