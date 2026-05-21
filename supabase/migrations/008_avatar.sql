-- =====================================================================
-- Papier Lab — Migration 008
-- Add avatar_url column to profiles so both admins and buyers can
-- upload a profile picture. Stored in the same Supabase Storage bucket
-- used for product images.
-- =====================================================================

alter table public.profiles
  add column if not exists avatar_url text;

comment on column public.profiles.avatar_url
  is 'Public URL of the user''s avatar image stored in Supabase Storage.';
