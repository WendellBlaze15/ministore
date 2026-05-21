-- =====================================================================
-- Papier Lab — Migration 007
-- Order reviews: buyers rate + comment on delivered orders so the admin
-- can see customer feedback alongside each order.
-- =====================================================================

create table if not exists public.order_reviews (
  id          uuid primary key default gen_random_uuid(),
  order_id    uuid not null unique references public.orders(id) on delete cascade,
  user_id     uuid not null references public.profiles(id) on delete cascade,
  rating      int  not null check (rating between 1 and 5),
  comment     text default '',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists order_reviews_user_idx  on public.order_reviews (user_id);
create index if not exists order_reviews_order_idx on public.order_reviews (order_id);

alter table public.order_reviews enable row level security;

drop policy if exists "order_reviews_self_read"   on public.order_reviews;
drop policy if exists "order_reviews_self_write"  on public.order_reviews;
drop policy if exists "order_reviews_admin_read"  on public.order_reviews;

-- Customers can manage their own reviews.
create policy "order_reviews_self_read"
  on public.order_reviews for select
  using (auth.uid() = user_id);

create policy "order_reviews_self_write"
  on public.order_reviews for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Admins can read every review.
create policy "order_reviews_admin_read"
  on public.order_reviews for select
  using (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'admin'
    )
  );
