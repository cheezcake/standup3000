-- Migration 001: User accounts and authentication
-- Adds user table for auth, roles, and session management

CREATE TABLE IF NOT EXISTS user (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    display_name    TEXT NOT NULL,
    email           TEXT UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    is_active       INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    feed_token      TEXT,
    created_at      TEXT NOT NULL,
    last_login      TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_username ON user(username);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_email ON user(email) WHERE email IS NOT NULL;
