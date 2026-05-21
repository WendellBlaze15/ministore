"""Realtime chat routes (customer <-> admin)."""
from flask import Blueprint, render_template, jsonify, request

from app.utils.auth import login_required, current_user, is_admin
from app.utils.security import require_same_origin
from app.services.supabase_client import get_service_client

bp = Blueprint("chat", __name__)


def _ensure_chat_for_user(user_id: str) -> str | None:
    svc = get_service_client()
    if not svc:
        return None
    try:
        existing = (
            svc.table("chats")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        ).data or []
        if existing:
            return existing[0]["id"]
        created = svc.table("chats").insert({"user_id": user_id}).execute()
        return (created.data or [{}])[0].get("id")
    except Exception:
        return None


@bp.route("/")
@login_required
def room():
    user = current_user()
    chat_id = _ensure_chat_for_user(user["id"])
    return render_template("chat/room.html", chat_id=chat_id, partner_name="Papier Lab Admin")


@bp.route("/admin/<chat_id>")
@login_required
def admin_room(chat_id: str):
    if not is_admin():
        return jsonify({"ok": False, "error": "Forbidden"}), 403

    svc = get_service_client()
    partner_name = "Customer"
    if svc:
        try:
            chat = (
                svc.table("chats")
                .select("user_id")
                .eq("id", chat_id)
                .single()
                .execute()
            ).data
            uid = (chat or {}).get("user_id")
            if uid:
                prof = (
                    svc.table("profiles")
                    .select("full_name, email")
                    .eq("id", uid)
                    .single()
                    .execute()
                ).data or {}
                partner_name = prof.get("full_name") or prof.get("email") or "Customer"
        except Exception:
            pass

    return render_template("chat/room.html", chat_id=chat_id, partner_name=partner_name, is_admin_view=True)


@bp.route("/send", methods=["POST"])
@login_required
@require_same_origin
def send_message():
    user = current_user()
    data = request.get_json(silent=True) or {}
    chat_id = (data.get("chat_id") or "").strip()
    body = (data.get("body") or "").strip()
    if not chat_id or not body:
        return jsonify({"ok": False, "error": "Missing chat or body"}), 400
    if len(body) > 1500:
        return jsonify({"ok": False, "error": "Message too long"}), 400

    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "error": "Server not configured"}), 500

    try:
        resp = svc.table("messages").insert(
            {
                "chat_id": chat_id,
                "sender_id": user["id"],
                "sender_role": "admin" if is_admin() else "customer",
                "body": body,
            }
        ).execute()
        msg = (resp.data or [None])[0]
        return jsonify({"ok": True, "message": msg})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/seen", methods=["POST"])
@login_required
@require_same_origin
def mark_seen():
    data = request.get_json(silent=True) or {}
    chat_id = (data.get("chat_id") or "").strip()
    if not chat_id:
        return jsonify({"ok": False}), 400
    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False}), 500
    try:
        opposite_role = "customer" if is_admin() else "admin"
        svc.table("messages").update({"seen": True}).match(
            {"chat_id": chat_id, "sender_role": opposite_role, "seen": False}
        ).execute()
    except Exception:
        pass
    return jsonify({"ok": True})
