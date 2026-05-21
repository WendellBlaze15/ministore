create table if not exists public.signup_codes (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  email       text not null,
  code_hash   text not null,
  attempts    int  not null default 0,
  expires_at  timestamptz not null,
  used_at     timestamptz,
  created_at  timestamptz not null default now()
);

create index if not exists signup_codes_email_idx on public.signup_codes (email);
create index if not exists signup_codes_user_idx  on public.signup_codes (user_id);

alter table public.signup_codes enable row level security;

drop policy if exists "signup_codes_no_anon" on public.signup_codes;
create policy "signup_codes_no_anon"
  on public.signup_codes
  for all
  to anon, authenticated
  using (false)
  with check (false);

create or replace function public.purge_expired_signup_codes()
returns void
language sql
as $$
  delete from public.signup_codes
   where (used_at is not null and used_at < now() - interval '7 days')
      or expires_at < now() - interval '1 day';
$$;
