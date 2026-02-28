# Standup 3000

<p align="center">
  <img src="logo.png" alt="Standup 3000" width="300">
</p>

A self-hosted web app for running recurring team standup meetings. Built for small-to-medium teams who want structured, department-by-department updates with presenter mode, action item tracking, analytics, and full-text search.

No cloud dependencies. No subscriptions. One SQLite file.

## Features

### Meetings
- **Create meetings by date** — one per day, with auto-generated sections for each active department
- **Copy from previous** — pre-fill a new meeting with last week's content
- **Create from template** — reusable meeting layouts with configurable department sets
- **Lock/unlock meetings** — admins can lock a meeting to prevent further edits
- **Markdown export** — download any meeting as a `.md` file with all sections, action items, and attendance

### Sections & Editing
- **Department-based sections** — each meeting gets one section per active department, pre-assigned to a primary reporter
- **Inline editing** — click any section to edit with Markdown. Ctrl+Enter to save. No page reloads (HTMX)
- **Special sections** — PTO, Shoutouts, etc. render separately and don't generate action items
- **Fill status tracking** — see at a glance how many sections have been filled

### Action Items
- **Per-section todos** with priority (low/normal/high), assignee, and due date
- **Carry-forward** — move an unfinished item to the latest meeting with one click
- **Action Items dashboard** (`/todos`) — all open items across all meetings, filterable by priority, assignee, status, and department
- **My Items** (`/my/todos`) — personal view of items assigned to you

### Presenter Mode
- Full-screen slide deck, one slide per section
- Arrow key navigation with confetti transitions
- Attendance bar showing who's present/remote
- Sound effects (optional, configurable volume)

### Attendance
- Track each team member as present, remote, or absent per meeting
- Attendance chips visible on the meeting page and in presenter mode
- Included in Markdown exports

### Analytics Dashboard
- **KPI cards** — total meetings, fill rate trend, open items, avg close time
- **Fill rate chart** — section completion over time (Chart.js)
- **Velocity chart** — items created vs. completed per week
- **Heatmap** — department fill status across recent meetings
- **By-assignee breakdown** — open items per person with priority split
- **Stale items** — action items open longer than 14 days
- **Activity feed** — recent section edits, item creation, completions
- Auto-refresh toggle (60s interval)
- All data served via 7 JSON API endpoints

### Search
- **Full-text search** across all section content and action items (SQLite FTS5)
- Results grouped by meeting date with highlighted snippets
- Search index maintained automatically on every edit

### Admin Panel
- **User management** — create/edit users, assign roles (admin/member), reset passwords
- **Departments** — add, reorder, archive, assign primary and backup reporters, set colors
- **Templates** — create reusable meeting layouts from department subsets
- **Settings** — app-wide configuration (team name, etc.)

### Authentication & Security
- Username/password auth with Werkzeug password hashing (scrypt)
- Role-based access: admin and member roles
- CSRF protection on all forms (hidden token) and AJAX (X-CSRF-Token header)
- Session-based login with auto-generated secret key
- First user to register becomes admin (setup wizard)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Flask 3.1, Python 3.10+ |
| Database | SQLite with WAL mode, FTS5 |
| Frontend | Pico CSS v2 (classless), HTMX 2.0 |
| Charts | Chart.js 4.x (CDN) |
| Markdown | Mistune 3.2 (server-side) |
| Server | Gunicorn (WSGI) |

## Architecture

```
app.py          Main blueprint — meetings, sections, todos, search, analytics (26 routes)
admin.py        Admin blueprint — users, departments, templates, settings (15 routes)
auth.py         Auth blueprint — login, logout, password change (4 routes)
db.py           Database layer — all SQL queries, migrations, search index
conftest.py     Shared test fixtures
seed_demo.py    Demo data seeder
```

### Data Model

```
user
department ──── department_reporter ──── user
  │
meeting_template ──── template_section ──── department
  │
meeting ──── meeting_attendance ──── user
  │
  └── section (linked to department)
        └── todo (assigned_to user, created_by user)

search_index (FTS5 virtual table — sections + todos)
```

11 tables, 6 migrations applied automatically on startup.

### Template Structure

```
templates/
├── base.html                  Layout, nav, CSS, theme toggle
├── login.html                 Login / setup page
├── meeting.html               Single meeting view
├── meeting_new.html           New meeting (fresh / template / copy)
├── meetings.html              Meeting list
├── present.html               Presenter mode
├── todos.html                 Action items dashboard
├── my_todos.html              Personal items view
├── search.html                Full-text search
├── analytics.html             Analytics dashboard (Chart.js)
├── change_password.html       Password change form
├── admin/
│   ├── layout.html            Admin shell with sub-nav
│   ├── dashboard.html         Admin overview stats
│   ├── users.html             User list
│   ├── user_form.html         Create/edit user
│   ├── departments.html       Department list (drag-reorder)
│   ├── department_form.html   Create/edit department
│   ├── templates.html         Template list
│   ├── template_form.html     Create/edit template
│   └── settings.html          App settings
└── partials/
    ├── section_view.html      Section display (HTMX target)
    ├── section_view_inner.html Section content rendered
    ├── section_edit.html      Inline Markdown editor
    ├── todo_list.html         Todo list for a section
    ├── todo_item.html         Single todo row
    └── attendance.html        Attendance panel
```

## Quick Start

```bash
git clone <repo-url> standup3000
cd standup3000
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
gunicorn -w 2 -b 127.0.0.1:8080 "app:create_app()"
```

Open `http://localhost:8080`. The first user you create becomes the admin.

The database (`data/meetings.db`) and secret key (`data/.secret_key`) are created automatically on first run.

### Demo Data

To see the app fully populated with realistic sample data:

```bash
rm -f data/meetings.db data/.secret_key
python seed_demo.py
```

Creates 8 users, 5 meetings with filled sections, 22 action items, attendance records, a locked meeting, and a template. Login: **admin / password**.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STANDUP3000_DB` | `data/meetings.db` | Path to SQLite database file |

### run.sh

```bash
./run.sh            # Uses venv/
```

Binds to `127.0.0.1:8080` (loopback only). For network access, use a reverse proxy.

## Deployment

### Reverse Proxy (Recommended)

For access from other machines, put Gunicorn behind nginx or Caddy:

```nginx
server {
    listen 80;
    server_name standup.internal;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Systemd Service (Linux)

```ini
[Unit]
Description=Standup 3000
After=network.target

[Service]
Type=exec
WorkingDirectory=/opt/standup3000
ExecStart=/opt/standup3000/venv/bin/gunicorn -w 2 -b 127.0.0.1:8080 "app:create_app()"
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Database Backup

The database is a single SQLite file. Copy `data/meetings.db` while the app is running — WAL mode makes this safe.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q                          # 239 tests
python -m pytest --cov=. --cov-report=term   # with coverage (93%)
```

7 test files covering database operations, all route endpoints, authentication, admin flows, search, analytics, and export.

## Security Notes

- **Auth required** — all pages require login. No anonymous access.
- **CSRF protection** — all state-changing requests require a token.
- **Password hashing** — Werkzeug scrypt with per-user salts.
- **Role-based access** — admin-only routes for user/department/template management, meeting lock/unlock.
- **SQLite concurrency** — WAL mode handles concurrent reads well. Fine for teams up to ~50 users. For larger deployments, consider PostgreSQL.
- **No HTTPS** — Gunicorn serves plain HTTP. Terminate TLS at the reverse proxy.
- **Markdown rendering** — section content is rendered with `escape=False` for rich formatting. On untrusted networks, switch to `escape=True` in `app.py`.
