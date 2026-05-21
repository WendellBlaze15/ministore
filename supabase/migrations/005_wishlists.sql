-- =====================================================================
-- Papier Lab — Migration 005
-- Wishlist table for customers to save products for later.
-- =====================================================================

create table if not exists public.wishlists (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles(id) on delete cascade,
  product_id  uuid not null references public.products(id) on delete cascade,
  created_at  timestamptz not null default now(),
  unique (user_id, product_id)
);

create index if not exists wishlists_user_idx on public.wishlists (user_id);

alter table public.wishlists enable row level security;

-- Customers can read/manage their own wishlist entries.
drop policy if exists "wishlists_self_read"   on public.wishlists;
drop policy if exists "wishlists_self_insert" on public.wishlists;
drop policy if exists "wishlists_self_delete" on public.wishlists;

create policy "wishlists_self_read"
  on public.wishlists for select
  using (auth.uid() = user_id);

create policy "wishlists_self_insert"
  on public.wishlists for insert
  with check (auth.uid() = user_id);

create policy "wishlists_self_delete"
  on public.wishlists for delete
  using (auth.uid() = user_id);
