#!/usr/bin/env python3
"""Seed a fresh Standup 3000 database with realistic demo data.

Usage:
    rm -f data/meetings.db data/.secret_key
    python seed_demo.py

Creates users, meetings (4 weeks of history), filled sections,
action items, attendance, and a template. Rebuilds the search index.
"""
import random
import secrets
import sys
from datetime import date, timedelta

import db
from app import create_app

# --- Config ---

TEAM = [
    # (username, display_name, role)
    ("admin",    "Admin",          "admin"),
    ("jchen",    "Jamie Chen",     "member"),
    ("mgarcia",  "Maria Garcia",   "member"),
    ("asingh",   "Arun Singh",     "member"),
    ("lpetrova", "Lena Petrova",   "member"),
    ("tkim",     "Tyler Kim",      "member"),
    ("rwilson",  "Rachel Wilson",  "member"),
    ("dnguyen",  "Dan Nguyen",     "member"),
]

# Realistic section content keyed by department name
SECTION_CONTENT = {
    "Engineering": [
        "Shipped auth microservice v2.1 to staging. Load tests look clean — p99 under 80ms. Preparing prod rollout Thursday.",
        "Finished migrating the payment gateway from Stripe v2 to v3 API. All webhook handlers updated. Need to coordinate cutover window with ops.",
        "Investigating intermittent 502s on the /api/search endpoint. Traced to connection pool exhaustion under concurrent indexing. Fix in review.",
        "Wrapped up the React 19 migration for the dashboard. Server components reduced bundle size by 38%. Rolling out behind feature flag.",
    ],
    "Design": [
        "Finalized the onboarding flow redesign — 5 screens down from 8. Prototype link shared in #design. Feedback welcome by Thursday.",
        "Working on the mobile nav overhaul. Current hamburger menu has low engagement (4% tap rate). Testing bottom tab bar variant.",
        "Completed accessibility audit on the settings pages. Found 12 WCAG AA issues, mostly contrast ratios. Fixes queued for next sprint.",
        "New illustration system is ready — 24 spot illustrations covering empty states, errors, and success moments. Asset library updated.",
    ],
    "Product": [
        "Customer interviews this week: 4 enterprise accounts. Top request is bulk CSV import — adding to Q2 roadmap.",
        "Pricing page A/B test results are in: variant B (toggle annual/monthly) increased conversions 12%. Shipping to 100% next week.",
        "Drafted RFC for the team workspace feature. Estimated 6-week build. Need eng capacity commitment before locking scope.",
        "Churn analysis from January shows 23% of cancellations cite 'missing integrations.' Prioritizing Slack and Notion connectors.",
    ],
    "QA": [
        "Regression suite is green on staging. 847 tests, 2 flaky (both timing-related, tracked in #qa-flaky). Release candidate looks good.",
        "Smoke tests for the new billing flow passed. Edge case around trial-to-paid conversion needed a fix — PR merged this morning.",
        "Added 35 new E2E tests for the workspace feature branch. Coverage on critical paths is now 94%. Performance benchmarks pending.",
        "Load testing the notification service: sustained 10k events/sec with <200ms delivery. Bottleneck is the email provider rate limit.",
    ],
    "Infrastructure": [
        "Kubernetes cluster upgrade to 1.29 complete. Zero downtime. Deprecated PodSecurityPolicy resources cleaned up.",
        "Migrated CI/CD from GitHub Actions to Buildkite. Build times dropped from 18min to 7min. Cost is roughly neutral.",
        "Set up Datadog APM tracing across all services. Already caught a N+1 query in the notifications service.",
        "Database replica lag spike last Tuesday traced to a long-running analytics query. Added query timeout and read replica routing.",
    ],
    "Support": [
        "Ticket volume up 15% this week — mostly questions about the new export feature. Updating the help docs and adding tooltips.",
        "Three P1 incidents this week, all resolved within SLA. Root causes: 1 DNS, 1 bad deploy, 1 third-party API outage.",
        "Customer satisfaction score for February: 4.6/5. Main complaints: slow response on weekends and missing bulk actions.",
        "Created 8 new help center articles covering the API v3 migration. Internal knowledge base also updated.",
    ],
    "Operations": [
        "Monthly AWS bill came in at $42k, down 8% from January. Reserved instance savings kicked in. Next target: right-sizing staging.",
        "SOC 2 Type II audit prep underway. 3 controls need documentation updates. Target completion: end of March.",
        "New hire onboarding: 2 engineers starting Monday. Laptops provisioned, access requests submitted, buddy system assigned.",
        "Vendor review for the log management contract. Evaluating Grafana Cloud vs renewing Datadog. Decision needed by March 15.",
    ],
    "PTO / Out of Office": [
        "Maria — PTO Friday\nTyler — remote (dentist morning)",
        "Arun — OOO Mon-Tue (family)\nRachel — remote all week",
        "Dan — PTO Thursday-Friday\nLena — half day Wednesday",
        "",
    ],
    "Shoutouts": [
        "Huge shoutout to Jamie for debugging the auth issue at 11pm last Tuesday. Saved us a customer escalation.",
        "Props to the QA team for catching the billing edge case before it hit production. Solid work.",
        "Rachel crushed the customer onboarding demo for Acme Corp. They signed the enterprise deal!",
        "Thanks Dan for writing up the incident postmortem so thoroughly. The whole team learned from it.",
    ],
}

# Realistic action items
ACTION_ITEMS = [
    # (text, priority, dept_keyword, done)
    ("Set up staging environment for payment gateway cutover", "high", "Engineering", False),
    ("Write migration guide for Stripe v2 to v3", "normal", "Engineering", True),
    ("Fix connection pool config for search service", "high", "Engineering", False),
    ("Update API docs for the new auth endpoints", "normal", "Engineering", True),
    ("Benchmark React 19 SSR performance vs baseline", "low", "Engineering", False),
    ("Review onboarding flow prototype and leave comments", "normal", "Design", False),
    ("Create dark mode variants for new illustrations", "low", "Design", False),
    ("Fix contrast ratios on settings page (WCAG AA)", "high", "Design", True),
    ("Schedule customer interviews for workspace feature", "normal", "Product", False),
    ("Ship pricing page variant B to 100%", "high", "Product", True),
    ("Draft Slack integration RFC", "normal", "Product", False),
    ("Investigate flaky E2E tests in CI", "normal", "QA", False),
    ("Add performance benchmarks for notification service", "high", "QA", False),
    ("Write load test scenario for workspace feature", "normal", "QA", False),
    ("Clean up deprecated PodSecurityPolicy manifests", "low", "Infrastructure", True),
    ("Set up Datadog monitors for p99 latency", "normal", "Infrastructure", False),
    ("Add query timeout to analytics read replica", "high", "Infrastructure", True),
    ("Update help docs for new export feature", "normal", "Support", False),
    ("Create runbook for P1 DNS incidents", "low", "Support", False),
    ("Submit SOC 2 documentation updates", "high", "Operations", False),
    ("Complete vendor evaluation for log management", "normal", "Operations", False),
    ("Review and approve new hire access requests", "high", "Operations", True),
]

# --- Helpers ---

def pick(lst):
    return random.choice(lst)

def date_str(d):
    return d.strftime("%Y-%m-%d")

# --- Main ---

def seed():
    app = create_app()
    with app.app_context():
        print("Seeding demo data...")

        # 1. Users
        use_demo_pw = "--demo" in sys.argv
        print("  Creating users...")
        credentials = []
        users = {}
        for username, display_name, role in TEAM:
            pw = "password" if use_demo_pw else secrets.token_urlsafe(10)
            u = db.create_user(username, display_name, pw, role=role)
            if u:
                users[username] = u
                credentials.append((username, pw, role))
                print(f"    {display_name} ({role})")
            else:
                print(f"    {display_name} — already exists, skipping")

        user_list = list(users.values())
        member_list = [u for u in user_list if u["role"] == "member"]

        # 2. Assign reporters to departments
        print("  Assigning reporters...")
        depts = db.list_departments(include_archived=False)
        dept_map = {d["name"]: d for d in depts}

        reporter_assignments = {
            "Engineering": "jchen",
            "Design": "lpetrova",
            "Product": "rwilson",
            "QA": "asingh",
            "Infrastructure": "dnguyen",
            "Support": "tkim",
            "Operations": "mgarcia",
        }
        for dept_name, username in reporter_assignments.items():
            if dept_name in dept_map and username in users:
                db.set_department_reporters(
                    dept_map[dept_name]["id"],
                    [(users[username]["id"], True)]
                )
                print(f"    {dept_name} -> {users[username]['display_name']}")

        # 3. Create meetings (4 Mondays + today)
        print("  Creating meetings...")
        today = date.today()
        # Find the last 4 Mondays
        mondays = []
        d = today
        while len(mondays) < 4:
            d -= timedelta(days=1)
            if d.weekday() == 0:  # Monday
                mondays.append(d)
        mondays.reverse()
        meeting_dates = mondays + [today]

        meetings = []
        for md in meeting_dates:
            mid = db.create_meeting(date_str(md))
            if mid:
                meetings.append((mid, md))
                print(f"    {date_str(md)} (id={mid})")

        # 4. Fill sections with content
        print("  Filling sections...")
        for i, (mid, md) in enumerate(meetings):
            sections = db.get_sections(mid)
            for sec in sections:
                content_pool = SECTION_CONTENT.get(sec["name"])
                if content_pool:
                    # Last meeting (today) gets less content to show fill rate variation
                    if md == today and random.random() < 0.3:
                        continue  # Leave some empty for today
                    content = content_pool[i % len(content_pool)]
                    if content:
                        db.update_section(sec["id"], content)

        # 5. Add action items
        print("  Adding action items...")
        for text, priority, dept_keyword, done in ACTION_ITEMS:
            # Put on a random meeting's matching section
            target_meeting = pick(meetings)
            sections = db.get_sections(target_meeting[0])
            target_section = None
            for s in sections:
                if s["name"] == dept_keyword:
                    target_section = s
                    break
            if not target_section:
                target_section = sections[0]

            assignee = pick(member_list) if member_list else None
            creator = pick(user_list) if user_list else None

            # Spread due dates around
            if random.random() < 0.6:
                due = today + timedelta(days=random.randint(-7, 14))
                due_str = date_str(due)
            else:
                due_str = None

            db.add_todo(
                target_section["id"],
                text,
                assigned_to=assignee["id"] if assignee else None,
                due_date=due_str,
                priority=priority,
                created_by=creator["id"] if creator else None,
            )
            if done:
                # Get the todo we just created and toggle it
                conn = db.get_db()
                todo = conn.execute(
                    "SELECT id FROM todo ORDER BY id DESC LIMIT 1"
                ).fetchone()
                conn.close()
                if todo:
                    db.toggle_todo(todo["id"])

        print(f"    {len(ACTION_ITEMS)} action items created")

        # 6. Attendance
        print("  Setting attendance...")
        statuses = ["present", "present", "present", "remote", "absent"]
        for mid, md in meetings:
            for u in user_list:
                status = pick(statuses)
                db.set_attendance(mid, u["id"], status)

        # 7. Lock an older meeting
        if len(meetings) >= 3:
            old_mid = meetings[0][0]
            admin_user = users.get("admin")
            if admin_user:
                db.lock_meeting(old_mid, admin_user["id"])
                print(f"  Locked meeting {meetings[0][1]}")

        # 8. Create a template
        print("  Creating template...")
        regular_depts = [d for d in depts if not d["is_special"]]
        if regular_depts:
            dept_ids = [d["id"] for d in regular_depts[:5]]
            admin_user = users.get("admin")
            tid = db.create_template(
                "Weekly Standup",
                description="Standard weekly standup with core departments",
                created_by=admin_user["id"] if admin_user else None,
                department_ids=dept_ids,
            )
            if tid:
                print(f"    Template 'Weekly Standup' (id={tid})")

        # 9. Backdate some todos for analytics variety
        print("  Backdating items for analytics...")
        conn = db.get_db()
        todos = conn.execute("SELECT id FROM todo").fetchall()
        for todo in todos:
            days_ago = random.randint(0, 28)
            created = today - timedelta(days=days_ago)
            conn.execute(
                "UPDATE todo SET created_at = ? WHERE id = ?",
                (created.isoformat(), todo["id"]),
            )
        # Backdate completed_at too
        done_todos = conn.execute(
            "SELECT id, created_at FROM todo WHERE done = 1"
        ).fetchall()
        for todo in done_todos:
            created = date.fromisoformat(todo["created_at"][:10])
            completed = created + timedelta(days=random.randint(1, 7))
            conn.execute(
                "UPDATE todo SET completed_at = ? WHERE id = ?",
                (completed.isoformat(), todo["id"]),
            )
        conn.commit()
        conn.close()

        # 10. Rebuild search index
        print("  Rebuilding search index...")
        db.rebuild_search_index()

        print(f"\nDone! {len(users)} users, {len(meetings)} meetings, {len(ACTION_ITEMS)} action items.")
        if credentials:
            print("\nCredentials (save these — shown once):")
            print(f"  {'Username':<12} {'Password':<20} Role")
            print(f"  {'-'*12:<12} {'-'*20:<20} ----")
            for uname, pw, role in credentials:
                print(f"  {uname:<12} {pw:<20} {role}")
        if use_demo_pw:
            print("\n  (--demo mode: all passwords are 'password')")


if __name__ == "__main__":
    seed()
