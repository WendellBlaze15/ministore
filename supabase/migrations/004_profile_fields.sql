-- =====================================================================
-- Papier Lab — Migration 004
-- Extends the profiles table with the extra customer information
-- captured during registration & checkout.
--
-- All new columns are nullable so existing rows are unaffected.
-- =====================================================================

alter table public.profiles
  add column if not exists username       text,
  add column if not exists contact_number text,
  add column if not exists address        text;

-- Case-insensitive uniqueness for usernames when set. Allows nulls
-- (multiple buyers can leave the field blank).
create unique index if not exists profiles_username_unique
  on public.profiles (lower(username))
  where username is not null and length(trim(username)) > 0;

create index if not exists profiles_contact_idx on public.profiles (contact_number);
