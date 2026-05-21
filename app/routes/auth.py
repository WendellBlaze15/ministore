"""Authentication routes.

The browser handles the actual Supabase sign-in via the JS SDK (so realtime &
RLS work seamlessly). After a successful sign-in, JS POSTs the session tokens
to ``/auth/session`` so the Flask backend also knows who the user is.
"""
from __future__ import annotations

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app

from app.utils.auth import (
    store_user_in_session,
    clear_user_session,
    ensure_profile_row,
    current_user,
)

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login():
    if current_user():
        return redirect(url_for("main.home"))
    return render_template("auth/login.html", next=request.args.get("next", ""))


@bp.route("/register")
def register():
    if current_user():
        return redirect(url_for("main.home"))
    return render_template("auth/register.html")


@bp.route("/forgot")
def forgot():
    return render_template("auth/forgot.html")


@bp.route("/session", methods=["POST"])
def create_session():
    """Receive Supabase tokens from the browser and store them in the cookie."""
    data = request.get_json(silent=True) or {}
    user = data.get("user")
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token", "")

    if not user or not access_token:
        return jsonify({"ok": False, "error": "Missing user or access_token"}), 400

    store_user_in_session(user, access_token, refresh_token)

    sess_user = current_user() or {}
    ensure_profile_row(
        user_id=sess_user.get("id", ""),
        email=sess_user.get("email", ""),
        full_name=sess_user.get("name", ""),
        role=sess_user.get("role", "customer"),
    )
    return jsonify({"ok": True, "role": sess_user.get("role")})


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    clear_user_session()
    if request.method == "POST":
        return jsonify({"ok": True})
    flash("You're signed out. See you soon! 💌", "success")
    return redirect(url_for("main.home"))
