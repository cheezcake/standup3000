from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, session
from auth import admin_required, get_current_user
import db
import secrets

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@admin_required
def require_admin():
    """All admin routes require admin role — enforced here."""
    pass


# --- Dashboard ---

@admin_bp.route("/")
def dashboard():
    user_count = len(db.list_users())
    dept_count = len(db.list_departments(include_archived=False))
    template_count = len(db.list_templates())
    settings = db.get_all_settings()
    return render_template("admin/dashboard.html",
                           user_count=user_count,
                           dept_count=dept_count,
                           template_count=template_count,
                           settings=settings)


# --- User Management ---

@admin_bp.route("/users")
def users_list():
    users = db.list_users()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/new", methods=["GET", "POST"])
def user_create():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip()
        email = request.form.get("email", "").strip() or None
        role = request.form.get("role", "member")
        password = request.form.get("password", "").strip()

        if not username or not display_name or not password:
            flash("Username, display name, and password are required.", "error")
            return render_template("admin/user_form.html", mode="create")

        from auth import _validate_password
        pw_err = _validate_password(password)
        if pw_err:
            flash(pw_err, "error")
            return render_template("admin/user_form.html", mode="create")

        if role not in ("admin", "member"):
            role = "member"

        user = db.create_user(username, display_name, password, role=role, email=email)
        if not user:
            flash("Username or email already exists.", "error")
            return render_template("admin/user_form.html", mode="create")

        flash(f"User '{username}' created.", "success")
        return redirect(url_for("admin.users_list"))

    return render_template("admin/user_form.html", mode="create")


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def user_edit(user_id):
    user = db.get_user(user_id)
    if not user:
        abort(404)

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        email = request.form.get("email", "").strip() or None
        role = request.form.get("role", user["role"])
        is_active = request.form.get("is_active") == "1"

        if not display_name:
            flash("Display name is required.", "error")
            return render_template("admin/user_form.html", mode="edit", edit_user=user)

        if role not in ("admin", "member"):
            role = user["role"]

        # Prevent deactivating yourself
        current = get_current_user()
        if user["id"] == current["id"] and not is_active:
            flash("You cannot deactivate your own account.", "error")
            return render_template("admin/user_form.html", mode="edit", edit_user=user)

        # Prevent removing your own admin role
        if user["id"] == current["id"] and role != "admin":
            flash("You cannot remove your own admin role.", "error")
            return render_template("admin/user_form.html", mode="edit", edit_user=user)

        db.update_user(user_id, display_name=display_name, email=email,
                       role=role, is_active=is_active)
        flash(f"User '{user['username']}' updated.", "success")
        return redirect(url_for("admin.users_list"))

    temp_pw = session.pop("_temp_password", None)
    return render_template("admin/user_form.html", mode="edit", edit_user=user, temp_password=temp_pw)


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
def user_reset_password(user_id):
    user = db.get_user(user_id)
    if not user:
        abort(404)

    temp_password = secrets.token_urlsafe(12)
    db.reset_password(user_id, temp_password)
    flash(f"Password reset for '{user['username']}'. Temporary password has been set — share it securely.", "success")
    session["_temp_password"] = temp_password
    return redirect(url_for("admin.user_edit", user_id=user_id))


# --- Department Management ---

@admin_bp.route("/departments")
def departments_list():
    departments = db.list_departments(include_archived=True)
    return render_template("admin/departments.html", departments=departments)


@admin_bp.route("/departments/new", methods=["GET", "POST"])
def department_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        color = request.form.get("color", "").strip() or None
        is_special = request.form.get("is_special") == "1"

        if not name:
            flash("Department name is required.", "error")
            return render_template("admin/department_form.html", mode="create",
                                   users=db.list_active_users())

        dept = db.create_department(name, color=color, is_special=is_special)
        if not dept:
            flash("A department with that name already exists.", "error")
            return render_template("admin/department_form.html", mode="create",
                                   users=db.list_active_users())

        # Handle reporters
        _save_reporters(dept["id"], request.form)

        flash(f"Department '{name}' created.", "success")
        return redirect(url_for("admin.departments_list"))

    return render_template("admin/department_form.html", mode="create",
                           users=db.list_active_users())


@admin_bp.route("/departments/<int:dept_id>/edit", methods=["GET", "POST"])
def department_edit(dept_id):
    dept = db.get_department(dept_id)
    if not dept:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        color = request.form.get("color", "").strip() or None
        is_special = request.form.get("is_special") == "1"
        is_archived = request.form.get("is_archived") == "1"

        if not name:
            flash("Department name is required.", "error")
            reporters = db.get_department_reporters(dept_id)
            return render_template("admin/department_form.html", mode="edit",
                                   dept=dept, reporters=reporters,
                                   users=db.list_active_users())

        db.update_department(dept_id, name=name, color=color,
                             is_special=is_special, is_archived=is_archived)

        _save_reporters(dept_id, request.form)

        flash(f"Department '{name}' updated.", "success")
        return redirect(url_for("admin.departments_list"))

    reporters = db.get_department_reporters(dept_id)
    return render_template("admin/department_form.html", mode="edit",
                           dept=dept, reporters=reporters,
                           users=db.list_active_users())


@admin_bp.route("/departments/reorder", methods=["PUT"])
def departments_reorder():
    dept_ids = request.json.get("order", [])
    if dept_ids:
        db.reorder_departments(dept_ids)
    return jsonify({"ok": True})


def _save_reporters(dept_id, form):
    """Extract reporter user IDs from form and save."""
    primary_id = form.get("primary_reporter")
    backup_ids = form.getlist("backup_reporters")

    entries = []
    if primary_id:
        entries.append((int(primary_id), True))
    for bid in backup_ids:
        if bid and bid != primary_id:
            entries.append((int(bid), False))

    db.set_department_reporters(dept_id, entries)


# --- Settings ---

@admin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        # Presenter settings
        for key in ("presenter.slide_sound", "presenter.final_slide_sound",
                     "presenter.confetti", "ui.sounds_enabled", "ui.sound_volume",
                     "markdown.escape"):
            val = request.form.get(key)
            if val is not None:
                db.set_setting(key, val.strip())

        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    all_settings = db.get_all_settings()
    return render_template("admin/settings.html", settings=all_settings)


# --- Meeting Templates ---

@admin_bp.route("/templates")
def templates_list():
    templates = db.list_templates()
    return render_template("admin/templates.html", templates=templates)


@admin_bp.route("/templates/new", methods=["GET", "POST"])
def template_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        dept_ids = request.form.getlist("departments")

        if not name:
            flash("Template name is required.", "error")
            departments = db.list_departments(include_archived=False)
            return render_template("admin/template_form.html", mode="create",
                                   departments=departments)

        user = get_current_user()
        dept_ids_int = [int(d) for d in dept_ids if d]
        tid = db.create_template(name, description=description,
                                 created_by=user["id"],
                                 department_ids=dept_ids_int)
        if not tid:
            flash("A template with that name already exists.", "error")
            departments = db.list_departments(include_archived=False)
            return render_template("admin/template_form.html", mode="create",
                                   departments=departments)

        flash(f"Template '{name}' created.", "success")
        return redirect(url_for("admin.templates_list"))

    departments = db.list_departments(include_archived=False)
    return render_template("admin/template_form.html", mode="create",
                           departments=departments)


@admin_bp.route("/templates/<int:template_id>/edit", methods=["GET", "POST"])
def template_edit(template_id):
    template = db.get_template(template_id)
    if not template:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        dept_ids = request.form.getlist("departments")

        if not name:
            flash("Template name is required.", "error")
            departments = db.list_departments(include_archived=False)
            template_sections = db.get_template_sections(template_id)
            selected = [ts["department_id"] for ts in template_sections]
            return render_template("admin/template_form.html", mode="edit",
                                   template=template, departments=departments,
                                   selected_depts=selected)

        dept_ids_int = [int(d) for d in dept_ids if d]
        result = db.update_template(template_id, name=name, description=description,
                                    department_ids=dept_ids_int)
        if not result:
            flash("A template with that name already exists.", "error")
        else:
            flash(f"Template '{name}' updated.", "success")
        return redirect(url_for("admin.templates_list"))

    departments = db.list_departments(include_archived=False)
    template_sections = db.get_template_sections(template_id)
    selected = [ts["department_id"] for ts in template_sections]
    return render_template("admin/template_form.html", mode="edit",
                           template=template, departments=departments,
                           selected_depts=selected)


@admin_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
def template_delete(template_id):
    template = db.get_template(template_id)
    if not template:
        abort(404)
    db.delete_template(template_id)
    flash(f"Template '{template['name']}' deleted.", "success")
    return redirect(url_for("admin.templates_list"))


@admin_bp.route("/templates/save-from-meeting", methods=["POST"])
def template_save_from_meeting():
    meeting_id = request.form.get("meeting_id")
    name = request.form.get("name", "").strip()
    if not meeting_id or not name:
        flash("Meeting and template name are required.", "error")
        return redirect(request.referrer or url_for("admin.templates_list"))
    user = get_current_user()
    tid = db.save_template_from_meeting(int(meeting_id), name, created_by=user["id"])
    if not tid:
        flash("A template with that name already exists.", "error")
    else:
        flash(f"Template '{name}' saved from meeting.", "success")
    return redirect(url_for("admin.templates_list"))
