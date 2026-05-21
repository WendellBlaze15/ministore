# Supabase setup guide 🌸

Follow these steps once. They take ~10 minutes.

## 1. Create the project

1. Go to <https://supabase.com> → **Start your project** (free tier is fine).
2. Set a database password and pick a region close to you.
3. Wait ~1 minute for the project to provision.

## 2. Apply the schema

1. In the left sidebar click **SQL Editor → + New query**.
2. Open [`schema.sql`](./schema.sql) from this repo and **copy its full contents**.
3. Paste into the SQL editor and press **Run**.

You should see green ticks and a `Success` toast. The script creates:

- `profiles`, `products`, `product_images`, `carts`, `cart_items`, `orders`, `order_items`, `chats`, `messages`, `wishlist`
- A trigger that automatically creates a `profiles` row when a new user signs up
- Row Level Security policies on every table
- A helper `public.is_admin()` function
- 8 sample products (delete or replace later)
- Realtime broadcasting enabled for `messages`

## 3. Create the storage bucket for product images

1. Sidebar → **Storage → New bucket**.
2. Name: **`product-images`**
3. Make it **Public** (toggle on).
4. Click **Create bucket**.

> The bucket name must match `SUPABASE_STORAGE_BUCKET` in your `.env`. Default is `product-images`.

### Optional storage policy

If you want only admins to upload images, paste this in **Storage → Policies**:

```sql
create policy "Admins can upload product images"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'product-images' and public.is_admin()
);
create policy "Admins can update / delete product images"
on storage.objects for update to authenticated
using (bucket_id = 'product-images' and public.is_admin());
create policy "Public read for product images"
on storage.objects for select to public
using (bucket_id = 'product-images');
```

## 4. Configure auth

Sidebar → **Authentication → Providers → Email**

- **Confirm email**: ON in production, OFF in development for instant login.
- Optional: set up a Resend / SMTP provider for password reset emails.

Sidebar → **Authentication → URL Configuration**:

- **Site URL**: `http://localhost:5000` (then `https://yourdomain.com` once deployed).
- **Redirect URLs**: add both `http://localhost:5000/*` and your production URL.

## 5. Make yourself the admin

Easiest way: set `ADMIN_EMAIL=your@email.com` in `.env`. After you register on the site, the Flask backend automatically flips your role to `admin` and stamps the same role into the `profiles` table.

Alternatively, after registering, run this in the SQL editor:

```sql
update public.profiles
set role = 'admin'
where email = 'your@email.com';
```

## 6. Grab the keys

Sidebar → **Project Settings → API**

| Variable                 | Value to copy                            |
| ------------------------ | ---------------------------------------- |
| `SUPABASE_URL`           | **Project URL** (e.g. `https://abc.supabase.co`) |
| `SUPABASE_ANON_KEY`      | The **anon public** key                  |
| `SUPABASE_SERVICE_KEY`   | The **service_role** key (⚠️ server-only) |

Paste them into your `.env` (and into Vercel project settings when deploying).

---

Done! 🌸 You can now run the app with `python run.py`.
