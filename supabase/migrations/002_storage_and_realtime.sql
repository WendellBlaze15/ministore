-- =====================================================================
-- Papier Lab — Migration 002
-- Tightens storage policies and guarantees realtime is on for messages.
-- Idempotent — safe to run multiple times.
-- =====================================================================

-- ----------------------------------------------------------------------
-- Storage policies for the `product-images` bucket
-- ----------------------------------------------------------------------
-- Anyone can READ images (so the public shop page can show them).
-- Only admins (or the service-role key bypassing RLS) can write.

drop policy if exists "product_images_public_read" on storage.objects;
create policy "product_images_public_read"
  on storage.objects for select to public
  using (bucket_id = 'product-images');

drop policy if exists "product_images_admin_insert" on storage.objects;
create policy "product_images_admin_insert"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'product-images' and public.is_admin());

drop policy if exists "product_images_admin_update" on storage.objects;
create policy "product_images_admin_update"
  on storage.objects for update to authenticated
  using (bucket_id = 'product-images' and public.is_admin())
  with check (bucket_id = 'product-images' and public.is_admin());

drop policy if exists "product_images_admin_delete" on storage.objects;
create policy "product_images_admin_delete"
  on storage.objects for delete to authenticated
  using (bucket_id = 'product-images' and public.is_admin());


-- ----------------------------------------------------------------------
-- Realtime: make sure `messages` is part of the supabase_realtime
-- publication (so the chat page receives live INSERTs/UPDATEs).
-- ----------------------------------------------------------------------
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
     where pubname = 'supabase_realtime'
       and schemaname = 'public'
       and tablename  = 'messages'
  ) then
    execute 'alter publication supabase_realtime add table public.messages';
  end if;
end $$;


-- ----------------------------------------------------------------------
-- Trigger hardening: the on_auth_user_created trigger created the
-- profile with role='customer'. If the upserts from the Flask app
-- already promoted the user to admin, we don't want a re-run of the
-- trigger to demote them. The original function uses ON CONFLICT DO
-- NOTHING which is already safe — this is just a sanity check.
-- ----------------------------------------------------------------------
-- (no-op — left here for documentation)


-- ----------------------------------------------------------------------
-- Helpful indexes that we missed in the first cut
-- ----------------------------------------------------------------------
create index if not exists products_slug_idx        on public.products (slug);
create index if not exists orders_created_idx       on public.orders (created_at desc);
create index if not exists messages_created_idx     on public.messages (created_at);
create index if not exists profiles_role_idx        on public.profiles (role);


-- ----------------------------------------------------------------------
-- Verify everything is fine
-- ----------------------------------------------------------------------
select
  'storage policies' as check,
  count(*) filter (where polname like 'product_images_%') as count
from pg_policy
union all
select 'realtime messages',
  (select count(*) from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'messages')::int;
