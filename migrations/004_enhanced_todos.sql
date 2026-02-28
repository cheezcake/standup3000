-- Phase 2: Enhanced action items — assignments, due dates, priority, tracking

ALTER TABLE todo ADD COLUMN assigned_to INTEGER REFERENCES user(id);
ALTER TABLE todo ADD COLUMN due_date TEXT;                           -- YYYY-MM-DD
ALTER TABLE todo ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'; -- 'low' | 'normal' | 'high'
ALTER TABLE todo ADD COLUMN created_by INTEGER REFERENCES user(id);
ALTER TABLE todo ADD COLUMN completed_at TEXT;                       -- ISO timestamp

-- Index for "my todos" queries
CREATE INDEX IF NOT EXISTS idx_todo_assigned_to ON todo(assigned_to);

-- Index for due date filtering
CREATE INDEX IF NOT EXISTS idx_todo_due_date ON todo(due_date);
