-- Phase 4: Full-text search index using FTS5
-- Indexes section content, section names, reporter names, and todo text

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    type,           -- 'section' or 'todo'
    source_id,      -- section.id or todo.id
    meeting_id,     -- for grouping results by meeting
    meeting_date,   -- for display
    section_name,   -- section name (for context)
    reporter,       -- reporter name
    content         -- the searchable text
);

-- Populate index with existing section data
INSERT INTO search_index (type, source_id, meeting_id, meeting_date, section_name, reporter, content)
SELECT 'section', s.id, m.id, m.date, s.name, s.reporter, s.content
FROM section s JOIN meeting m ON s.meeting_id = m.id
WHERE s.content != '';

-- Populate index with existing todo data
INSERT INTO search_index (type, source_id, meeting_id, meeting_date, section_name, reporter, content)
SELECT 'todo', t.id, m.id, m.date, s.name, s.reporter, t.text
FROM todo t
JOIN section s ON t.section_id = s.id
JOIN meeting m ON s.meeting_id = m.id;
