-- =====================================================================
-- Papier Lab — Migration 010
-- Persistent deletion ledger.
--
-- Reality check: my own seed script and any other demo scripts were
-- happily re-creating users + products that the admin had just deleted.
-- This migration adds a small "tombstone" table so we can refuse to
-- re-create anything the admin removed. Admin can undo from the UI.
-- =====================================================================

-- ---------------------------------------------------------------
-- banned_product_slugs: stops the demo seed (or anyone) from
-- re-creating a product slug an admin explicitly deleted.
-- ---------------------------------------------------------------
create table if not exists public.banned_product_slugs (
  slug        text primary key,
  name        text default '',
  reason      text default 'removed by admin',
  banned_at   timestamptz not null default now(),
  banned_by   uuid references auth.users(id) on delete set null
);

alter table public.banned_product_slugs enable row level security;

drop policy if exists "banned_slugs_admin_all" on public.banned_product_slugs;
create policy "banned_slugs_admin_all"
  on public.banned_product_slugs for all
  using (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'admin'
    )
  );

-- ---------------------------------------------------------------
-- Trigger: when a product row is deleted, automatically capture
-- its slug in banned_product_slugs so re-seeding can't bring it
-- back without the admin lifting the block.
-- ---------------------------------------------------------------
create or replace function public.product_after_delete_tombstone()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if old.slug is not null and length(old.slug) > 0 then
    insert into public.banned_product_slugs (slug, name, reason)
    values (old.slug, coalesce(old.name, ''), 'removed by admin')
    on conflict (slug) do nothing;
  end if;
  return old;
end;
$$;

drop trigger if exists products_tombstone on public.products;
create trigger products_tombstone
  after delete on public.products
  for each row execute procedure public.product_after_delete_tombstone();

-- ---------------------------------------------------------------
-- Trigger: when an auth user is deleted, automatically capture
-- their email in banned_emails. Catches deletions done via any
-- channel (Supabase Studio, admin SDK, manual SQL) not just our
-- /admin/users/<id>/delete route.
-- ---------------------------------------------------------------
create or replace function public.auth_user_after_delete_tombstone()
returns trigger
language plpgsql
security definer
set search_path = public, auth
as $$
begin
  if old.email is not null and length(old.email) > 0 then
    insert into public.banned_emails (email, reason)
    values (lower(old.email), 'removed by admin')
    on conflict (email) do nothing;
  end if;
  return old;
end;
$$;

drop trigger if exists banned_emails_tombstone on auth.users;
create trigger banned_emails_tombstone
  after delete on auth.users
  for each row execute procedure public.auth_user_after_delete_tombstone();
