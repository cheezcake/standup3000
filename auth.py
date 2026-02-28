from functools import wraps
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort
from collections import defaultdict
import time
import db

auth_bp = Blueprint("auth", __name__)

# Rate limiting: track login attempts per IP
_login_attempts = defaultdict(list)
RATE_LIMIT = 5
RATE_WINDOW = 60  # seconds
COMMON_PASSWORDS = {
    "password", "12345678", "123456789", "1234567890", "qwerty123",
    "password1", "iloveyou", "sunshine1", "princess1", "football1",
    "abc12345", "monkey123", "shadow123", "master123", "dragon123",
    "qwertyui", "trustno1", "letmein1", "baseball1", "password123",
}


def _validate_password(password):
    """Return error message if password is weak, else None."""
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password.lower() in COMMON_PASSWORDS:
        return "That password is too common. Please choose a stronger one."
    return None


def _is_rate_limited(ip):
    now = time.time()
    attempts = _login_attempts[ip]
    # Prune old attempts
    _login_attempts[ip] = [t for t in attempts if now - t < RATE_WINDOW]
    # Periodic cleanup of stale IPs to prevent memory leak
    if len(_login_attempts) > 1000:
        stale = [k for k, v in _login_attempts.items() if not v or now - v[-1] > RATE_WINDOW]
        for k in stale:
            del _login_attempts[k]
    return len(_login_attempts[ip]) >= RATE_LIMIT


def _record_attempt(ip):
    _login_attempts[ip].append(time.time())


def get_current_user():
    """Return the current logged-in user or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.get_user(user_id)
    if user and user["is_active"]:
        return user
    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        if user["role"] != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, go home
    if get_current_user():
        return redirect(url_for("index"))

    # First-run bootstrap: no users exist yet
    needs_setup = not db.has_any_users()

    if request.method == "POST":
        if needs_setup:
            return _handle_setup(request.form)
        return _handle_login(request.form)

    return render_template("login.html", needs_setup=needs_setup)


def _handle_setup(form):
    username = form.get("username", "").strip()
    display_name = form.get("display_name", "").strip()
    password = form.get("password", "").strip()
    confirm = form.get("confirm_password", "").strip()

    if not username or not display_name or not password:
        flash("All fields are required.", "error")
        return render_template("login.html", needs_setup=True)

    pw_err = _validate_password(password)
    if pw_err:
        flash(pw_err, "error")
        return render_template("login.html", needs_setup=True)

    if password != confirm:
        flash("Passwords do not match.", "error")
        return render_template("login.html", needs_setup=True)

    user = db.create_user(username, display_name, password, role="admin")
    if not user:
        flash("Failed to create account. Username may already exist.", "error")
        return render_template("login.html", needs_setup=True)

    session["user_id"] = user["id"]
    session["_fresh_login"] = True
    session.permanent = True
    return redirect(url_for("index"))


def _handle_login(form):
    ip = request.remote_addr
    if _is_rate_limited(ip):
        flash("Too many login attempts. Please wait a minute.", "error")
        return render_template("login.html", needs_setup=False), 429

    username = form.get("username", "").strip()
    password = form.get("password", "").strip()

    user = db.authenticate_user(username, password)
    _record_attempt(ip)

    if not user:
        flash("Invalid username or password.", "error")
        return render_template("login.html", needs_setup=False), 401

    session["user_id"] = user["id"]
    session["_fresh_login"] = True
    session.permanent = True

    # If must change password, redirect there
    if user["must_change_password"]:
        return redirect(url_for("auth.change_password"))

    next_url = request.form.get("next") or request.args.get("next") or url_for("index")
    # Validate next_url is a safe relative path (no host, no scheme)
    parsed = urlparse(next_url)
    if parsed.netloc or parsed.scheme or not next_url.startswith("/"):
        next_url = url_for("index")
    return redirect(next_url)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/settings/password", methods=["GET", "POST"])
def change_password():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        current = request.form.get("current_password", "").strip()
        new_pass = request.form.get("new_password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()

        # If must_change_password, don't require current password
        if not user["must_change_password"]:
            from werkzeug.security import check_password_hash
            if not check_password_hash(user["password_hash"], current):
                flash("Current password is incorrect.", "error")
                return render_template("change_password.html", user=user)

        pw_err = _validate_password(new_pass)
        if pw_err:
            flash(pw_err, "error")
            return render_template("change_password.html", user=user)

        if new_pass != confirm:
            flash("Passwords do not match.", "error")
            return render_template("change_password.html", user=user)

        db.change_password(user["id"], new_pass)
        flash("Password changed successfully.", "success")
        return redirect(url_for("index"))

    return render_template("change_password.html", user=user)


# --- CSRF Protection ---

def generate_csrf_token():
    if "_csrf_token" not in session:
        import secrets
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def validate_csrf():
    """Check CSRF token on state-changing requests. Call from before_request."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    # Skip for login (no session yet)
    if request.endpoint and request.endpoint in ("auth.login", "auth.logout"):
        return
    token = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
    if not token or token != session.get("_csrf_token"):
        abort(403)
