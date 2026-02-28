import os
from flask import Flask, render_template, request, redirect, url_for, abort, session, flash, jsonify, Response
from datetime import date, timedelta
import mistune
import nh3
import db
from auth import auth_bp, login_required, admin_required, get_current_user, generate_csrf_token, validate_csrf
from admin import admin_bp


def next_wednesday():
    """Return the next Wednesday (or today if it's Wednesday)."""
    today = date.today()
    days_ahead = 2 - today.weekday()  # Wednesday = 2
    if days_ahead < 0:
        days_ahead += 7
    return (today + timedelta(days=days_ahead)).isoformat()


def create_app():
    app = Flask(__name__)

    # Secret key for sessions
    app.secret_key = db.get_or_create_secret_key()

    # Session config
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("STANDUP3000_SECURE_COOKIES", "0") == "1"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

    # Markdown renderer — escape mode driven by settings
    def get_md():
        escape = db.get_setting("markdown.escape", "true") == "true"
        return mistune.create_markdown(escape=escape)

    @app.template_filter("markdown")
    def markdown_filter(text):
        if not text:
            return ""
        md = get_md()
        return nh3.clean(md(text))

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    # Initialize database + run migrations
    with app.app_context():
        db.init_db()

    # --- Context processors ---

    @app.context_processor
    def inject_globals():
        user = get_current_user()
        return {
            "current_user": user,
            "csrf_token": generate_csrf_token,
            "app_settings": db.get_all_settings(),
            "today": date.today().isoformat(),
        }

    # --- CSRF enforcement ---

    @app.before_request
    def csrf_check():
        # Skip CSRF for static files
        if request.endpoint and request.endpoint == "static":
            return
        validate_csrf()

    # --- Check fresh login for materialization ---

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'"
        )
        if session.pop("_fresh_login", None):
            response.set_cookie("_fresh_login", "1", max_age=10, httponly=False, samesite="Lax")
        return response

    # --- Routes ---

    @app.route("/")
    @login_required
    def index():
        meeting = db.get_latest_meeting()
        if meeting:
            return redirect(url_for("meeting_view", meeting_id=meeting["id"]))
        return redirect(url_for("meetings_list"))

    @app.route("/meeting/<int:meeting_id>")
    @login_required
    def meeting_view(meeting_id):
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        sections = db.get_sections(meeting_id)
        todos_map = db.get_todos_by_meeting(meeting_id)
        user = get_current_user()
        users = db.list_active_users()
        attendance = db.get_attendance(meeting_id)
        att_map = {a["user_id"]: a["status"] for a in attendance}
        return render_template("meeting.html", meeting=meeting, sections=sections,
                               todos_map=todos_map, can_edit=db.can_edit_section,
                               user=user, users=users, attendance=attendance,
                               att_map=att_map)

    @app.route("/meetings")
    @login_required
    def meetings_list():
        meetings = db.list_meetings()
        meeting_info = []
        for m in meetings:
            filled, total = db.get_meeting_fill_status(m["id"])
            open_todos = db.get_meeting_open_todo_count(m["id"])
            meeting_info.append({"meeting": m, "filled": filled, "total": total, "open_todos": open_todos})
        return render_template("meetings.html", meeting_info=meeting_info)

    @app.route("/meeting/new", methods=["GET", "POST"])
    @login_required
    def meeting_new():
        if request.method == "POST":
            meeting_date = request.form.get("date", "").strip()
            copy_from = request.form.get("copy_from", "").strip() or None
            template_id = request.form.get("template_id", "").strip() or None
            if not meeting_date:
                return redirect(url_for("meetings_list"))

            mid = None
            if template_id:
                try:
                    mid = db.create_meeting_from_template(meeting_date, int(template_id))
                except (ValueError, TypeError):
                    pass
            if mid is None:
                mid = db.create_meeting(meeting_date, copy_from=copy_from)

            if mid:
                return redirect(url_for("meeting_view", meeting_id=mid))
            existing = db.get_meeting_by_date(meeting_date)
            if existing:
                return redirect(url_for("meeting_view", meeting_id=existing["id"]))
            return redirect(url_for("meetings_list"))
        suggested_date = next_wednesday()
        prev_meetings = db.list_meetings()
        templates = db.list_templates()
        return render_template("meeting_new.html", suggested_date=suggested_date,
                               prev_meetings=prev_meetings, templates=templates)

    @app.route("/meeting/<int:meeting_id>/present")
    @login_required
    def meeting_present(meeting_id):
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        sections = db.get_sections(meeting_id)
        regular = [s for s in sections if not s["is_special"]]
        special = [s for s in sections if s["is_special"]]
        ordered = regular + special
        todos_map = db.get_todos_by_meeting(meeting_id)
        settings = db.get_all_settings()
        attendance = db.get_attendance(meeting_id)
        return render_template("present.html", meeting=meeting, sections=ordered,
                               todos_map=todos_map, settings=settings,
                               attendance=attendance)

    # --- Todos ---

    @app.route("/todos")
    @login_required
    def todos_dashboard():
        # Parse filters from query string
        assignee_filter = request.args.get("assignee", "")
        priority_filter = request.args.get("priority", "")
        overdue_filter = request.args.get("overdue") == "1"
        show_done = request.args.get("show_done") == "1"

        assigned_to = None
        if assignee_filter == "unassigned":
            assigned_to = "unassigned"
        elif assignee_filter:
            try:
                assigned_to = int(assignee_filter)
            except ValueError:
                pass

        rows = db.get_all_open_todos(
            assigned_to=assigned_to,
            priority=priority_filter or None,
            overdue_only=overdue_filter,
            include_done=show_done,
        )
        grouped = {}
        for r in rows:
            date_key = r["meeting_date"]
            section_key = r["section_name"]
            if date_key not in grouped:
                grouped[date_key] = {}
            if section_key not in grouped[date_key]:
                grouped[date_key][section_key] = {
                    "reporter": r["reporter"],
                    "meeting_id": r["meeting_id"],
                    "todos": [],
                }
            grouped[date_key][section_key]["todos"].append(r)
        users = db.list_active_users()
        return render_template("todos.html", grouped=grouped, users=users,
                               filters={"assignee": assignee_filter,
                                        "priority": priority_filter,
                                        "overdue": overdue_filter,
                                        "show_done": show_done})

    @app.route("/my/todos")
    @login_required
    def my_todos():
        user = get_current_user()
        show_done = request.args.get("show_done") == "1"
        todos = db.get_my_todos(user["id"], include_done=show_done)
        return render_template("my_todos.html", todos=todos, show_done=show_done)

    @app.route("/section/<int:section_id>/todos", methods=["GET"])
    @login_required
    def todo_list(section_id):
        section = db.get_section(section_id)
        if not section:
            abort(404)
        todos = db.get_todos(section_id)
        users = db.list_active_users()
        return render_template("partials/todo_list.html", section=section,
                               todos=todos, users=users)

    @app.route("/section/<int:section_id>/todos", methods=["POST"])
    @login_required
    def todo_add(section_id):
        section = db.get_section(section_id)
        if not section:
            abort(404)
        if db.is_meeting_locked(section["meeting_id"]):
            abort(403)
        user = get_current_user()
        text = request.form.get("text", "").strip()
        if text:
            assigned_to = request.form.get("assigned_to") or None
            if assigned_to:
                try:
                    assigned_to = int(assigned_to)
                except ValueError:
                    assigned_to = None
            due_date = request.form.get("due_date", "").strip() or None
            priority = request.form.get("priority", "normal")
            db.add_todo(section_id, text, assigned_to=assigned_to,
                        due_date=due_date, priority=priority,
                        created_by=user["id"])
        todos = db.get_todos(section_id)
        users = db.list_active_users()
        return render_template("partials/todo_list.html", section=section,
                               todos=todos, users=users)

    @app.route("/todo/<int:todo_id>/toggle", methods=["PUT"])
    @login_required
    def todo_toggle(todo_id):
        todo = db.get_todo(todo_id)
        if not todo:
            abort(404)
        db.toggle_todo(todo_id)
        todo = db.get_todo(todo_id)
        return render_template("partials/todo_item.html", todo=todo)

    @app.route("/todo/<int:todo_id>", methods=["DELETE"])
    @login_required
    def todo_delete(todo_id):
        todo = db.get_todo(todo_id)
        if not todo:
            abort(404)
        db.delete_todo(todo_id)
        return ""

    @app.route("/todo/<int:todo_id>/carry-forward", methods=["POST"])
    @login_required
    def todo_carry_forward(todo_id):
        todo = db.get_todo(todo_id)
        if not todo:
            abort(404)
        latest = db.get_latest_meeting()
        if not latest:
            abort(400)
        new_id = db.carry_forward_todo(todo_id, latest["id"])
        if new_id is None:
            abort(400)
        # Re-render the original section's todo list
        section = db.get_section(todo["section_id"])
        todos = db.get_todos(section["id"])
        users = db.list_active_users()
        return render_template("partials/todo_list.html", section=section,
                               todos=todos, users=users)

    # --- Search ---

    @app.route("/search")
    @login_required
    def search_page():
        query = request.args.get("q", "").strip()
        results = []
        grouped = {}
        if query:
            results = db.search(query)
            for r in results:
                date_key = r["meeting_date"]
                if date_key not in grouped:
                    grouped[date_key] = []
                grouped[date_key].append(r)
        return render_template("search.html", query=query, grouped=grouped,
                               result_count=len(results))

    # --- Export ---

    @app.route("/meeting/<int:meeting_id>/export/markdown")
    @login_required
    def meeting_export_markdown(meeting_id):
        md_text = db.get_meeting_as_markdown(meeting_id)
        if md_text is None:
            abort(404)
        meeting = db.get_meeting(meeting_id)
        filename = f"standup-{meeting['date']}.md"
        return Response(
            md_text,
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # --- Analytics ---

    @app.route("/analytics")
    @login_required
    def analytics_dashboard():
        return render_template("analytics.html")

    @app.route("/api/analytics/kpis")
    @login_required
    def api_analytics_kpis():
        return jsonify(db.analytics_kpis())

    @app.route("/api/analytics/fill-rate")
    @login_required
    def api_analytics_fill_rate():
        return jsonify(db.analytics_fill_rate())

    @app.route("/api/analytics/velocity")
    @login_required
    def api_analytics_velocity():
        return jsonify(db.analytics_velocity())

    @app.route("/api/analytics/heatmap")
    @login_required
    def api_analytics_heatmap():
        return jsonify(db.analytics_heatmap())

    @app.route("/api/analytics/by-assignee")
    @login_required
    def api_analytics_by_assignee():
        data = db.analytics_by_assignee()
        return jsonify([{"name": name, **counts} for name, counts in data])

    @app.route("/api/analytics/stale")
    @login_required
    def api_analytics_stale():
        return jsonify(db.analytics_stale())

    @app.route("/api/analytics/activity")
    @login_required
    def api_analytics_activity():
        return jsonify(db.analytics_activity())

    # --- Meeting Lifecycle ---

    @app.route("/meeting/<int:meeting_id>/lock", methods=["POST"])
    @login_required
    @admin_required
    def meeting_lock(meeting_id):
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        user = get_current_user()
        db.lock_meeting(meeting_id, user["id"])
        flash("Meeting locked.", "success")
        return redirect(url_for("meeting_view", meeting_id=meeting_id))

    @app.route("/meeting/<int:meeting_id>/unlock", methods=["POST"])
    @login_required
    @admin_required
    def meeting_unlock(meeting_id):
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        db.unlock_meeting(meeting_id)
        flash("Meeting unlocked.", "success")
        return redirect(url_for("meeting_view", meeting_id=meeting_id))

    # --- Attendance ---

    @app.route("/meeting/<int:meeting_id>/attendance", methods=["GET"])
    @login_required
    def meeting_attendance(meeting_id):
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        attendance = db.get_attendance(meeting_id)
        users = db.list_active_users()
        # Build lookup of attendance by user_id
        att_map = {a["user_id"]: a["status"] for a in attendance}
        return render_template("partials/attendance.html", meeting=meeting,
                               users=users, att_map=att_map)

    @app.route("/meeting/<int:meeting_id>/attendance", methods=["PUT"])
    @login_required
    def meeting_attendance_update(meeting_id):
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        user = get_current_user()
        if user["role"] != "admin":
            abort(403)
        # Expect JSON: {"user_id": N, "status": "present"|"absent"|"remote"|"none"}
        data = request.get_json(silent=True)
        if not data:
            abort(400)
        user_id = data.get("user_id")
        status = data.get("status", "present")
        if not user_id:
            abort(400)
        if status == "none":
            db.remove_attendance(meeting_id, user_id)
        else:
            db.set_attendance(meeting_id, user_id, status)
        # Return updated attendance partial
        attendance = db.get_attendance(meeting_id)
        users = db.list_active_users()
        att_map = {a["user_id"]: a["status"] for a in attendance}
        return render_template("partials/attendance.html", meeting=meeting,
                               users=users, att_map=att_map)

    # --- HTMX partials ---

    @app.route("/section/<int:section_id>/edit", methods=["GET"])
    @login_required
    def section_edit(section_id):
        section = db.get_section(section_id)
        if not section:
            abort(404)
        user = get_current_user()
        if not db.can_edit_section(user, section):
            abort(403)
        return render_template("partials/section_edit.html", section=section)

    @app.route("/section/<int:section_id>", methods=["GET"])
    @login_required
    def section_view(section_id):
        section = db.get_section(section_id)
        if not section:
            abort(404)
        return render_template("partials/section_view.html", section=section)

    @app.route("/section/<int:section_id>", methods=["PUT"])
    @login_required
    def section_save(section_id):
        section = db.get_section(section_id)
        if not section:
            abort(404)
        user = get_current_user()
        if not db.can_edit_section(user, section):
            abort(403)
        content = request.form.get("content", "")
        db.update_section(section_id, content)
        section = db.get_section(section_id)
        return render_template("partials/section_view.html", section=section)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", port=5000)
