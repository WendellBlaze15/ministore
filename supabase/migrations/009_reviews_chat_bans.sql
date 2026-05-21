-- =====================================================================
-- Papier Lab — Migration 009
-- - Product reviews (5-star + optional photo). Different from order_reviews
--   which lives off an order; this one is per product so the studio can
--   show ratings on the product detail page.
-- - Chat images: add image_url to messages so admin + customer can drop
--   pictures into the conversation.
-- - Banned emails: when an admin deletes a buyer we lock the email so
--   that exact address can't immediately re-register and "come back".
-- =====================================================================

-- ---------------------------------------------------------------
-- product_reviews
-- ---------------------------------------------------------------
create table if not exists public.product_reviews (
  id          uuid primary key default gen_random_uuid(),
  product_id  uuid not null references public.products(id) on delete cascade,
  user_id     uuid not null references auth.users(id)      on delete cascade,
  rating      int  not null check (rating between 1 and 5),
  body        text default '',
  image_url   text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (product_id, user_id)
);

create index if not exists product_reviews_product_idx on public.product_reviews (product_id);
create index if not exists product_reviews_user_idx    on public.product_reviews (user_id);

alter table public.product_reviews enable row level security;

drop policy if exists "product_reviews_public_read"  on public.product_reviews;
drop policy if exists "product_reviews_self_write"   on public.product_reviews;
drop policy if exists "product_reviews_admin_all"    on public.product_reviews;

-- Anyone (even guests) can read approved reviews — they're shown on the
-- public product page.
create policy "product_reviews_public_read"
  on public.product_reviews for select
  using (true);

-- Owners can insert / update / delete their own review.
create policy "product_reviews_self_write"
  on public.product_reviews for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Admins can do anything (moderate / delete spam).
create policy "product_reviews_admin_all"
  on public.product_reviews for all
  using (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'admin'
    )
  );

-- Make product_reviews stream over Supabase Realtime so the product page
-- updates the star average live as new reviews drop in.
do $$ begin
  alter publication supabase_realtime add table public.product_reviews;
exception when others then null;
end $$;

-- ---------------------------------------------------------------
-- messages: image attachments
-- ---------------------------------------------------------------
alter table public.messages
  add column if not exists image_url text;

comment on column public.messages.image_url is
  'Public URL of an attached image in Supabase Storage (chat-images path).';

-- The legacy NOT NULL on body has to allow empty strings now so that
-- image-only messages can be sent. We keep NOT NULL but allow length=0.
do $$ begin
  alter table public.messages alter column body drop not null;
exception when others then null;
end $$;

-- ---------------------------------------------------------------
-- banned_emails: prevent re-registration of deleted accounts
-- ---------------------------------------------------------------
create table if not exists public.banned_emails (
  email       text primary key,
  reason      text default 'removed by admin',
  banned_at   timestamptz not null default now(),
  banned_by   uuid references auth.users(id) on delete set null
);

alter table public.banned_emails enable row level security;

drop policy if exists "banned_emails_admin_all" on public.banned_emails;
create policy "banned_emails_admin_all"
  on public.banned_emails for all
  using (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'admin'
    )
  );
