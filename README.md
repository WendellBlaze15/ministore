# Papier Lab 🌸

A complete, modern e-commerce platform for **Papier Lab** — a small handmade crafts business that sells bookmarks, keychains, polaroid prints, and crafts.

Soft, feminine, Korean-inspired aesthetic with a light-pink theme, beginner-friendly admin, and a clean codebase ready for Vercel deployment.

---

## Tech stack

| Layer       | Tool                                              |
| ----------- | ------------------------------------------------- |
| Backend     | **Python · Flask 3** (Jinja2 templates)           |
| Database    | **Supabase** (Postgres + RLS)                     |
| Auth        | **Supabase Auth** (email + password)              |
| Realtime    | **Supabase Realtime** (live chat)                 |
| Storage     | **Supabase Storage** (product images)             |
| Frontend    | HTML5 · CSS3 · vanilla ES Modules (no framework!) |
| Deployment  | **Vercel** (serverless Python)                    |

---

## Features

### Customer (buyer)
- Register / sign in (Supabase Auth)
- **Password reset via OTP email** — Gmail SMTP sends a 6-digit code; the
  code is HMAC-SHA256 hashed on the server, never stored in plain text
- Browse, search and filter products by category
- Product detail page with multiple images and customisation note
- Persistent localStorage cart with smooth UX
- Checkout with COD or GCash (mockup)
- Live order tracking with a cute timeline (pending → preparing → shipped → delivered)
- Realtime chat with the admin (seen status + timestamps)
- Wishlist support (DB table ready) and dark pastel mode toggle

### Admin
- Secure admin-only dashboard with revenue chart and KPIs
- Add / edit / delete products, upload images to Supabase Storage
- Manage orders and update their status
- Customer directory
- Chat panel — answer customers in realtime

### UX / UI
- Light pink theme · Fraunces (display) + Plus Jakarta Sans (body)
- Rounded corners, pink-tinted soft shadows, smooth hover/scroll animations
- Sparkle accents, polaroid stacks, floating hero artwork
- Toast notifications + skeleton loaders
- Fully responsive on mobile and desktop
- Dark pastel mode

---

## Project structure

```
papier-lab/
├── api/
│   └── index.py                  # Vercel serverless entry (imports the Flask app)
├── app/
│   ├── __init__.py               # Flask application factory
│   ├── config.py                 # Config loaded from env
│   ├── routes/                   # Blueprints — main, auth, products, cart, orders, chat, admin
│   ├── services/
│   │   └── supabase_client.py    # Anon + service-role helpers
│   ├── utils/                    # auth decorators, helpers
│   ├── templates/                # Jinja2 templates (home, shop, cart, chat, admin/*)
│   │   ├── _navbar.html / _footer.html / _product_card.html
│   │   ├── auth/, orders/, chat/, admin/, errors/
│   └── static/
│       ├── css/                  # main.css (theme), pages.css (page-specific)
│       └── js/                   # main.js, cart.js, supabase.js
├── supabase/
│   └── schema.sql                # Full schema + RLS policies + seed
├── .env.example                  # Copy to .env and fill in
├── .gitignore
├── requirements.txt
├── vercel.json                   # Vercel build & route config
├── run.py                        # Local dev server
└── README.md
```

---

## Quick start (local development)

### 1. Clone & install
```bash
git clone <your-repo-url> papier-lab
cd papier-lab
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

### 2. Set up Supabase
Follow the step-by-step guide in [`supabase/SETUP.md`](supabase/SETUP.md). Highlights:
1. Create a free project at [supabase.com](https://supabase.com).
2. Run [`supabase/schema.sql`](supabase/schema.sql) in the **SQL Editor**.
3. Create a public storage bucket called **`product-images`**.
4. (Optional) In **Authentication → Providers**, leave email enabled. Turn *Confirm email* off during development for instant login.
5. Promote your own account to admin (after registering it once on the site):
   ```sql
   update public.profiles
   set role = 'admin'
   where email = 'you@papierlab.shop';
   ```
   Or set `ADMIN_EMAIL` in `.env` — any user with that email becomes admin automatically.

### 3. Configure environment
```bash
cp .env.example .env
```
Open `.env` and paste the values from your Supabase project (`Project Settings → API`).

### 4. Run locally
```bash
python run.py
```
Open <http://localhost:5000>.

---

## Deployment to Vercel

Full guide: [`DEPLOYMENT.md`](DEPLOYMENT.md).

Short version:

1. Push the repo to GitHub.
2. Import it in [vercel.com](https://vercel.com/new).
3. Add the same env vars (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `FLASK_SECRET_KEY`, `ADMIN_EMAIL`, `SUPABASE_STORAGE_BUCKET`).
4. Deploy. Vercel will pick up `vercel.json` and serve `api/index.py` as a Python serverless function.

---

## Security

- Supabase **Row Level Security** is enabled on every table — a customer can never read someone else's orders, and only admins can write products.
- Service-role key never reaches the browser (only used inside Flask).
- Supabase Auth handles password hashing (bcrypt) — plaintext passwords never touch our server.
- `/auth/session` re-verifies every access token by calling `supabase.auth.get_user()` — forged session payloads are rejected.
- `FLASK_SECRET_KEY` signs session cookies (HttpOnly, SameSite=Lax, Secure in production).
- `@require_same_origin` blocks cross-origin POSTs to state-changing JSON endpoints.
- OTP codes for password reset are **HMAC-SHA256 hashed** with `FLASK_SECRET_KEY`, expire in 10 minutes, lock after 5 wrong attempts, and rate-limit re-issue to one per 60 seconds per email.
- Storage policies restrict product-image WRITEs to admins only (defense in depth on top of service-role uploads).
- Server-side input validation on checkout (stock, prices, length limits).
- Image uploads are restricted to safe extensions (`png`, `jpg`, `jpeg`, `webp`, `gif`).
- Admin routes are protected by the `@admin_required` decorator.

---

## Customising

| What                | Where                                                                   |
| ------------------- | ----------------------------------------------------------------------- |
| Brand colours       | CSS variables at the top of `app/static/css/main.css`                   |
| Logo / brand name   | `app/templates/_navbar.html` + `app/templates/_footer.html`             |
| Categories          | `app/routes/main.py` + the `category` CHECK in `supabase/schema.sql`    |
| Shipping fee logic  | `_save_product` in `app/routes/cart.py` (set free-ship threshold there) |
| Home page sections  | `app/templates/home.html` — the hero collage and "our story" polaroid stack pull live products from Supabase (admin manages them) |

---

## Roadmap ideas

- Stripe / PayMongo real payment integration
- Email order confirmations (Resend / SendGrid)
- Product reviews + photos
- Multi-image gallery uploads from admin (table is already there)
- Discount codes
- PWA offline mode

---

## License

MIT — handmade with 🌸 in the Philippines.
