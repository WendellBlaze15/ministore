-- =====================================================================
-- Papier Lab — Migration 003
-- Adds the password_reset_codes table used for the OTP-based password
-- reset flow.
--
-- Codes are NEVER stored in plain text — we keep only a SHA-256 HMAC
-- digest. The token row is consumed (used_at set) on first successful
-- verification and discarded after a short expiration.
-- =====================================================================

create table if not exists public.password_reset_codes (
    id          uuid primary key default uuid_generate_v4(),
    email       text not null,
    code_hash   text not null,
    attempts    integer not null default 0,
    expires_at  timestamptz not null,
    used_at     timestamptz,
    created_at  timestamptz not null default now()
);

create index if not exists password_reset_codes_email_idx
    on public.password_reset_codes (lower(email), created_at desc);
create index if not exists password_reset_codes_expires_idx
    on public.password_reset_codes (expires_at);

-- The Flask backend always talks to this table via the service-role key,
-- so RLS is locked down to deny anonymous access entirely.
alter table public.password_reset_codes enable row level security;

drop policy if exists "password_reset_codes_no_anon" on public.password_reset_codes;
create policy "password_reset_codes_no_anon"
  on public.password_reset_codes
  for all to public
  using (false) with check (false);

-- Optional housekeeping: a function to purge expired codes. Call manually
-- from the SQL editor or from a scheduled job.
create or replace function public.purge_expired_reset_codes()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    n integer;
begin
    delete from public.password_reset_codes
     where expires_at < now() - interval '1 day'
        or used_at is not null;
    get diagnostics n = row_count;
    return n;
end;
$$;
