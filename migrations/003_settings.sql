-- Migration 003: App settings key-value store
-- Used for presenter sounds, UI sounds, markdown escape mode, etc.

CREATE TABLE IF NOT EXISTS setting (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Seed default settings
INSERT INTO setting (key, value, updated_at) VALUES
    ('presenter.slide_sound',       'champagne',    datetime('now')),
    ('presenter.final_slide_sound', 'airhorn',      datetime('now')),
    ('presenter.confetti',          'on',           datetime('now')),
    ('ui.sounds_enabled',           'on',           datetime('now')),
    ('ui.sound_volume',             '0.3',          datetime('now')),
    ('markdown.escape',             'true',         datetime('now'));
