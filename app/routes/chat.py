"""Realtime chat routes (customer <-> admin)."""
import re

from flask import Blueprint, render_template, jsonify, request, current_app

from app.utils.auth import login_required, current_user, is_admin
from app.utils.security import require_same_origin
from app.utils.helpers import allowed_image, safe_filename
from app.services.supabase_client import get_service_client

bp = Blueprint("chat", __name__)

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


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

    # Optional ?order=<id> — prefill a friendly opener referencing the order
    prefill = ""
    raw_order = (request.args.get("order") or "").strip()
    if raw_order and _UUID_RE.match(raw_order):
        svc = get_service_client()
        if svc:
            try:
                row = (
                    svc.table("orders")
                    .select("id, status")
                    .eq("id", raw_order)
                    .eq("user_id", user["id"])
                    .limit(1)
                    .execute()
                ).data or []
                if row:
                    prefill = f"Hi! 🌸 Quick question about my order #{raw_order[:8]} (status: {row[0]['status']})."
            except Exception:
                pass

    return render_template(
        "chat/room.html",
        chat_id=chat_id,
        partner_name="Papier Lab Admin",
        prefill=prefill,
    )


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
    """Send a chat message. Accepts either JSON (text-only) or a multipart
    form (text and/or an image attachment)."""
    user = current_user()
    image_url: str | None = None

    if request.content_type and request.content_type.startswith("multipart/"):
        data = request.form
        chat_id = (data.get("chat_id") or "").strip()
        body = (data.get("body") or "").strip()
        image_file = request.files.get("image")
        svc = get_service_client()
        if image_file and image_file.filename:
            if not allowed_image(image_file.filename):
                return jsonify({"ok": False, "error": "Image must be JPG/PNG/WebP."}), 400
            if not svc:
                return jsonify({"ok": False, "error": "Server not configured."}), 500
            bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "product-images")
            path = f"chat-images/{chat_id}/{safe_filename(image_file.filename)}"
            try:
                try:
                    buckets = svc.storage.list_buckets() or []
                    names = {getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None) for b in buckets}
                    if bucket not in names:
                        svc.storage.create_bucket(bucket, options={"public": True})
                except Exception:
                    pass
                svc.storage.from_(bucket).upload(
                    path=path, file=image_file.read(),
                    file_options={"content-type": image_file.mimetype or "image/jpeg"},
                )
                image_url = svc.storage.from_(bucket).get_public_url(path)
            except Exception as exc:
                current_app.logger.warning("chat image upload failed: %s", exc)
                return jsonify({"ok": False, "error": "Could not upload image. Try again."}), 500
    else:
        data = request.get_json(silent=True) or {}
        chat_id = (data.get("chat_id") or "").strip()
        body = (data.get("body") or "").strip()

    if not chat_id or not _UUID_RE.match(chat_id):
        return jsonify({"ok": False, "error": "Invalid chat."}), 400
    if not body and not image_url:
        return jsonify({"ok": False, "error": "Add a message or an image."}), 400
    if len(body) > 1500:
        return jsonify({"ok": False, "error": "Message too long (max 1500 chars)."}), 400

    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "error": "Server not configured."}), 500

    try:
        chat_owner = (svc.table("chats").select("user_id").eq("id", chat_id).single().execute()).data
        if not chat_owner:
            return jsonify({"ok": False, "error": "Chat not found."}), 404
        if chat_owner["user_id"] != user["id"] and not is_admin():
            return jsonify({"ok": False, "error": "Forbidden."}), 403
    except Exception:
        return jsonify({"ok": False, "error": "Chat not found."}), 404

    record = {
        "chat_id": chat_id,
        "sender_id": user["id"],
        "sender_role": "admin" if is_admin() else "customer",
        "body": body,
    }
    if image_url:
        record["image_url"] = image_url

    try:
        resp = svc.table("messages").insert(record).execute()
        msg = (resp.data or [None])[0]
        return jsonify({"ok": True, "message": msg})
    except Exception as exc:
        # If image_url column not present yet, retry without it (and warn).
        if image_url and "image_url" in str(exc).lower():
            record.pop("image_url", None)
            try:
                resp = svc.table("messages").insert(record).execute()
                return jsonify({"ok": True, "message": (resp.data or [None])[0],
                                "warning": "Migration 009 not applied yet — image attachments require image_url column."})
            except Exception as exc2:
                current_app.logger.warning("send_message retry failed: %s", exc2)
        current_app.logger.warning("send_message failed: %s", exc)
        return jsonify({"ok": False, "error": "Could not send. Please try again."}), 500


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


@bp.route("/messages/<chat_id>")
@login_required
def fetch_messages(chat_id: str):
    """HTTP polling fallback used when Supabase Realtime/CDN isn't reachable."""
    user = current_user()
    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "messages": []}), 500

    try:
        chat = (svc.table("chats").select("user_id").eq("id", chat_id).single().execute()).data
        if not chat:
            return jsonify({"ok": False, "messages": []}), 404
        if chat["user_id"] != user["id"] and not is_admin():
            return jsonify({"ok": False, "messages": []}), 403
    except Exception:
        return jsonify({"ok": False, "messages": []}), 500

    since = request.args.get("since")
    select_cols = "id, body, sender_id, sender_role, seen, created_at, image_url"
    try:
        query = (
            svc.table("messages").select(select_cols)
            .eq("chat_id", chat_id).order("created_at", desc=False).limit(200)
        )
        if since:
            query = query.gt("created_at", since)
        rows = (query.execute()).data or []
    except Exception:
        # Legacy schema without image_url — fall back to text-only.
        try:
            query = (
                svc.table("messages")
                .select("id, body, sender_id, sender_role, seen, created_at")
                .eq("chat_id", chat_id).order("created_at", desc=False).limit(200)
            )
            if since:
                query = query.gt("created_at", since)
            rows = (query.execute()).data or []
        except Exception:
            rows = []
    return jsonify({"ok": True, "messages": rows})
