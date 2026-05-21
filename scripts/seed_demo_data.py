from __future__ import annotations
import os, sys, secrets, random, io
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from supabase import create_client

svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

# ------------------------- PRODUCTS -------------------------
DEMO_PRODUCTS = [
    {"slug": "coquette-bow-bookmark", "name": "Coquette Bow Bookmark", "category": "bookmarks",
     "price": 75.00, "stock": 32, "description": "Hand-cut paper bookmark with a soft pink satin bow and a tiny pearl charm. Comes in a cute envelope.",
     "cover_image": "https://images.unsplash.com/photo-1519682337058-a94d519337bc?auto=format&fit=crop&w=800&q=80",
     "is_featured": True},
    {"slug": "strawberry-milk-bookmark", "name": "Strawberry Milk Bookmark", "category": "bookmarks",
     "price": 65.00, "stock": 28, "description": "Pastel watercolor strawberry milk illustration, laminated for daily use. Sparkly heart embellishment.",
     "cover_image": "https://images.unsplash.com/photo-1602080857655-385f6dad5e87?auto=format&fit=crop&w=800&q=80",
     "is_featured": False},
    {"slug": "cloud-pearl-keychain", "name": "Cloud Pearl Keychain", "category": "keychains",
     "price": 145.00, "stock": 18, "description": "Iridescent acrylic cloud charm with a tiny pearl drop. Perfect for bags, keys, or pencil cases.",
     "cover_image": "https://images.unsplash.com/photo-1611923134239-b9be5816e23d?auto=format&fit=crop&w=800&q=80",
     "is_featured": True},
    {"slug": "sanrio-style-charm-keychain", "name": "Pastel Charm Keychain", "category": "keychains",
     "price": 130.00, "stock": 24, "description": "Cute pastel resin charm keychain. Each comes with a soft pink ribbon and beaded chain.",
     "cover_image": "https://images.unsplash.com/photo-1612817288484-6f916006741a?auto=format&fit=crop&w=800&q=80",
     "is_featured": False},
    {"slug": "polaroid-memory-set-10", "name": "Polaroid Memory Set (10 prints)", "category": "polaroids",
     "price": 220.00, "stock": 14, "description": "Set of 10 high-quality matte polaroid prints from your photos. Send us your pics in chat after ordering.",
     "cover_image": "https://images.unsplash.com/photo-1551836022-d5d88e9218df?auto=format&fit=crop&w=800&q=80",
     "is_featured": True},
    {"slug": "vintage-polaroid-pack-6", "name": "Vintage Polaroid Pack (6 prints)", "category": "polaroids",
     "price": 150.00, "stock": 20, "description": "Sepia-toned 6-print polaroid pack with vintage frame edges. Includes a hand-written tag.",
     "cover_image": "https://images.unsplash.com/photo-1542038784456-1ea8e935640e?auto=format&fit=crop&w=800&q=80",
     "is_featured": False},
    {"slug": "mini-bouquet-card", "name": "Mini Bouquet Greeting Card", "category": "crafts",
     "price": 95.00, "stock": 22, "description": "Hand-folded paper card with a dried mini bouquet inside. Customizable greeting on the front.",
     "cover_image": "https://images.unsplash.com/photo-1490750967868-88aa4486c946?auto=format&fit=crop&w=800&q=80",
     "is_featured": False},
    {"slug": "handmade-sticker-pack", "name": "Pastel Sticker Pack (24 pcs)", "category": "crafts",
     "price": 110.00, "stock": 40, "description": "24-piece handmade sticker pack. Glossy laminated finish, weather-resistant, all original art.",
     "cover_image": "https://images.unsplash.com/photo-1606293459209-d6c93f53a3a3?auto=format&fit=crop&w=800&q=80",
     "is_featured": True},
]

print("\n=== SEEDING PRODUCTS ===")
# Respect the deletion ledger — admins explicitly removed these slugs
# so we don't quietly resurrect them.
try:
    banned_slugs = {
        r["slug"] for r in
        (svc.table("banned_product_slugs").select("slug").execute()).data or []
    }
except Exception:
    banned_slugs = set()
if banned_slugs:
    print(f"  ledger blocks: {len(banned_slugs)} slug(s)")

for p in DEMO_PRODUCTS:
    if p["slug"] in banned_slugs:
        print(f"  skipped   {p['slug']} (in deletion ledger)")
        continue
    existing = (svc.table("products").select("id").eq("slug", p["slug"]).limit(1).execute()).data or []
    payload = {**p, "customizable": True, "is_active": True}
    if existing:
        svc.table("products").update(payload).eq("id", existing[0]["id"]).execute()
        print(f"  updated   {p['slug']}")
    else:
        svc.table("products").insert(payload).execute()
        print(f"  inserted  {p['slug']}")

products_db = (svc.table("products").select("id, name, slug, price, stock").execute()).data or []
print(f"  total products now: {len(products_db)}")

# ------------------------- CUSTOMERS -------------------------
DEMO_CUSTOMERS = [
    {"email": "andrea.demo@papierlab.shop", "name": "Andrea Cruz", "contact": "09171234567",
     "address": "123 Rosal St., Mabolo, Cebu City, Cebu", "username": "andrea_paperlover"},
    {"email": "jen.demo@papierlab.shop", "name": "Jen Reyes", "contact": "09281234567",
     "address": "45 Sunflower Ave., Project 6, Quezon City", "username": "jen_inks"},
    {"email": "mika.demo@papierlab.shop", "name": "Mika Santos", "contact": "09391234567",
     "address": "9 Magnolia Lane, Poblacion, Davao City", "username": "mika_polaroids"},
]
PWD = "DemoBuyer123!"
print("\n=== SEEDING CUSTOMERS ===")
# Respect the email banlist — same idea as banned_product_slugs.
try:
    banned_emails = {
        (r.get("email") or "").lower() for r in
        (svc.table("banned_emails").select("email").execute()).data or []
    }
except Exception:
    banned_emails = set()
if banned_emails:
    print(f"  ledger blocks: {len(banned_emails)} email(s)")

existing_users = svc.auth.admin.list_users()
existing_by_email = {(getattr(u, 'email', '') or '').lower(): u for u in existing_users}
customer_ids = []
for c in DEMO_CUSTOMERS:
    em = c["email"].lower()
    if em in banned_emails:
        print(f"  skipped   {em} (in banned_emails)")
        continue
    if em in existing_by_email:
        user = existing_by_email[em]
        print(f"  exists    {em}")
    else:
        created = svc.auth.admin.create_user({
            "email": em, "password": PWD, "email_confirm": True,
            "user_metadata": {"full_name": c["name"], "username": c["username"],
                              "contact_number": c["contact"], "address": c["address"]},
        })
        user = getattr(created, "user", None) or created
        print(f"  created   {em}")
    customer_ids.append(user.id)
    svc.table("profiles").update({
        "full_name": c["name"], "username": c["username"],
        "contact_number": c["contact"], "address": c["address"],
        "email": em, "role": "customer",
    }).eq("id", user.id).execute()

# ------------------------- ORDERS -------------------------
print("\n=== SEEDING ORDERS ===")
status_pool = ["pending", "preparing", "shipped", "delivered", "delivered", "delivered", "preparing", "shipped"]
payment_pool = ["cod", "gcash"]
existing_orders = (svc.table("orders").select("id").execute()).data or []
if len(existing_orders) >= 8:
    print(f"  already have {len(existing_orders)} orders, skipping")
else:
    now = datetime.now(timezone.utc)
    for i in range(10):
        uid = random.choice(customer_ids)
        cust = next(c for c in DEMO_CUSTOMERS if customer_ids[DEMO_CUSTOMERS.index(c)] == uid)
        chosen = random.sample(products_db, k=random.randint(1, 3))
        items_payload = []
        total = 0.0
        for p in chosen:
            qty = random.randint(1, 3)
            line = {"product_id": p["id"], "name": p["name"], "quantity": qty, "unit_price": float(p["price"])}
            items_payload.append(line)
            total += qty * float(p["price"])
        when = now - timedelta(days=random.randint(0, 28), hours=random.randint(0, 23))
        order = (svc.table("orders").insert({
            "user_id": uid,
            "full_name": cust["name"],
            "contact_number": cust["contact"],
            "address": cust["address"],
            "payment_method": random.choice(payment_pool),
            "status": status_pool[i % len(status_pool)],
            "total": round(total, 2),
            "created_at": when.isoformat(),
        }).execute()).data[0]
        for it in items_payload:
            svc.table("order_items").insert({**it, "order_id": order["id"]}).execute()
        print(f"  order #{order['id'][:8]}  {cust['name']:14s} ₱{total:7.2f}  {order['status']}")

# ------------------------- CHATS + MESSAGES -------------------------
print("\n=== SEEDING CHATS + MESSAGES ===")
admin_users = (svc.table("profiles").select("id").eq("role", "admin").limit(1).execute()).data or []
admin_id = admin_users[0]["id"] if admin_users else None

for uid in customer_ids:
    existing_chat = (svc.table("chats").select("id").eq("user_id", uid).limit(1).execute()).data or []
    if existing_chat:
        chat_id = existing_chat[0]["id"]
    else:
        chat = (svc.table("chats").insert({"user_id": uid}).execute()).data[0]
        chat_id = chat["id"]

    msg_count = (svc.table("messages").select("id", count="exact").eq("chat_id", chat_id).execute()).count or 0
    if msg_count >= 2:
        continue

    samples = [
        ("customer", uid, "Hi! Can I customize my order with my name printed in pink?"),
        ("admin",    admin_id, "Hi Andrea! Yes that's no problem at all 🌸 just send us the name and we'll add it before shipping."),
        ("customer", uid, "Yay thank you! Pls put the name 'Andrea' in cursive."),
        ("admin",    admin_id, "Got it! We'll ship tomorrow ♡"),
    ]
    for role, sender, body in samples:
        if sender is None:
            continue
        svc.table("messages").insert({
            "chat_id": chat_id, "sender_id": sender, "sender_role": role,
            "body": body, "seen": role == "admin",
        }).execute()
    print(f"  seeded chat for user {uid[:8]}")

print("\n=== DONE — dashboards should now have content ===")
print(f"Login demo customer: andrea.demo@papierlab.shop  password: {PWD}")
