# Deploying Papier Lab to Vercel 🌷

Vercel runs the Flask app as a Python serverless function via `api/index.py`,
and serves static assets from `app/static`. Everything is already configured in
`vercel.json` — you just need to push the repo and add your environment
variables.

## 1. Push to GitHub

```bash
git init
git add .
git commit -m "Papier Lab — initial commit 🌸"
git branch -M main
git remote add origin https://github.com/<you>/papier-lab.git
git push -u origin main
```

> ⚠️ Make sure `.env` is in `.gitignore` (it is). Never commit real keys.

## 2. Create the Vercel project

1. Go to <https://vercel.com/new>.
2. Pick **Import Git Repository** → choose the repo you just pushed.
3. Vercel will auto-detect the build:
   - Framework Preset: **Other**
   - Build Command: *(leave blank)*
   - Output Directory: *(leave blank — `vercel.json` handles it)*
4. Click **Deploy**.

## 3. Add environment variables

In your Vercel project → **Settings → Environment Variables**, add the same
variables as `.env.example`:

| Key                       | Where to get it / value                                            |
| ------------------------- | ------------------------------------------------------------------ |
| `FLASK_SECRET_KEY`        | Any long random string (e.g. `python -c "import secrets;print(secrets.token_hex(32))"`) |
| `SUPABASE_URL`            | Supabase Project Settings → API → Project URL                      |
| `SUPABASE_ANON_KEY`       | Supabase Project Settings → API → anon public key                  |
| `SUPABASE_SERVICE_KEY`    | Supabase Project Settings → API → service_role key (server only!)  |
| `SUPABASE_STORAGE_BUCKET` | `product-images` (or whatever bucket you created)                  |
| `ADMIN_EMAIL`             | The email of the account that should be admin                       |
| `APP_URL`                 | `https://<your-domain>.vercel.app`                                  |

After saving the env vars, click **Redeploy** so they take effect.

## 4. Add your Vercel URL to Supabase

In Supabase → **Authentication → URL Configuration**:

- Add your Vercel URL to **Site URL** and **Redirect URLs**.

Without this, magic links and password resets won't redirect back to your app.

## 5. (Optional) Add a custom domain

In Vercel → **Settings → Domains** → add your domain. Update your DNS, wait a
few minutes, and you're live on something like `papierlab.shop` 🌸.

---

## Local-vs-production differences

- Vercel runs Python in a serverless environment. Cold starts take ~1 second.
- The `MAX_CONTENT_LENGTH` is set to 8 MB — Vercel's hard limit on serverless
  function payloads is ~4.5 MB. If you expect bigger product images, upload
  them directly to Supabase Storage from the admin form (we do exactly that —
  the file is forwarded to the storage bucket, not stored on the function disk).
- For very high traffic, consider hosting on **Fly.io** or **Render** instead
  of Vercel serverless — Flask runs more cheaply on a long-lived container.

---

## Troubleshooting

**"Supabase not configured" toast on login**
→ Env vars aren't set in Vercel, or you forgot to redeploy after adding them.

**Admin links / data return 403**
→ Your profile's `role` is still `customer`. Set `ADMIN_EMAIL` in env, sign out
and back in. Or run the SQL `update public.profiles set role='admin' where email='…';`

**Chat doesn't send / no realtime updates**
→ Make sure `messages` is in the `supabase_realtime` publication (the SQL file
does this automatically). In Supabase → **Database → Replication** verify it's
listed.

**Storage uploads fail**
→ Verify the bucket name matches `SUPABASE_STORAGE_BUCKET` and the bucket is
public (or that you applied the optional storage policies above).
