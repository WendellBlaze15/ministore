-- =====================================================================
-- Papier Lab - Supabase Schema
-- Run this in the Supabase SQL editor (one project, fresh database).
-- =====================================================================

create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- profiles  (mirrors auth.users with role + display name)
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
    id          uuid primary key references auth.users (id) on delete cascade,
    email       text unique,
    full_name   text,
    role        text not null default 'customer' check (role in ('customer', 'admin')),
    created_at  timestamptz not null default now()
);

-- Auto-create a profile row when a new auth user is created.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email, full_name, role)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
        coalesce(new.raw_user_meta_data->>'role', 'customer')
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

-- ---------------------------------------------------------------------
-- products
-- ---------------------------------------------------------------------
create table if not exists public.products (
    id            uuid primary key default uuid_generate_v4(),
    name          text not null,
    slug          text unique not null,
    description   text default '',
    price         numeric(10,2) not null default 0,
    stock         integer not null default 0,
    category      text not null check (category in ('bookmarks', 'keychains', 'polaroids', 'crafts')),
    cover_image   text,
    customizable  boolean not null default true,
    is_active     boolean not null default true,
    is_featured   boolean not null default false,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index if not exists products_category_idx on public.products (category);
create index if not exists products_active_idx on public.products (is_active);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists products_touch_updated on public.products;
create trigger products_touch_updated
    before update on public.products
    for each row execute procedure public.touch_updated_at();

-- ---------------------------------------------------------------------
-- product_images  (multi-image gallery)
-- ---------------------------------------------------------------------
create table if not exists public.product_images (
    id          uuid primary key default uuid_generate_v4(),
    product_id  uuid not null references public.products (id) on delete cascade,
    url         text not null,
    position    integer not null default 0,
    created_at  timestamptz not null default now()
);

create index if not exists product_images_product_idx on public.product_images (product_id);

-- ---------------------------------------------------------------------
-- carts / cart_items  (persistent cart for logged-in users)
-- ---------------------------------------------------------------------
create table if not exists public.carts (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null unique references auth.users (id) on delete cascade,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create table if not exists public.cart_items (
    id              uuid primary key default uuid_generate_v4(),
    cart_id         uuid not null references public.carts (id) on delete cascade,
    product_id      uuid not null references public.products (id) on delete cascade,
    quantity        integer not null default 1 check (quantity > 0),
    customization   text default '',
    created_at      timestamptz not null default now(),
    unique (cart_id, product_id)
);

create index if not exists cart_items_cart_idx on public.cart_items (cart_id);

-- ---------------------------------------------------------------------
-- orders / order_items
-- ---------------------------------------------------------------------
create table if not exists public.orders (
    id              uuid primary key default uuid_generate_v4(),
    user_id         uuid not null references auth.users (id) on delete cascade,
    full_name       text not null,
    contact_number  text not null,
    address         text not null,
    notes           text default '',
    payment_method  text not null check (payment_method in ('cod', 'gcash')),
    subtotal        numeric(10,2) not null default 0,
    shipping_fee    numeric(10,2) not null default 0,
    total           numeric(10,2) not null default 0,
    status          text not null default 'pending'
                      check (status in ('pending', 'preparing', 'shipped', 'delivered', 'cancelled')),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists orders_user_idx on public.orders (user_id);
create index if not exists orders_status_idx on public.orders (status);

drop trigger if exists orders_touch_updated on public.orders;
create trigger orders_touch_updated
    before update on public.orders
    for each row execute procedure public.touch_updated_at();

create table if not exists public.order_items (
    id              uuid primary key default uuid_generate_v4(),
    order_id        uuid not null references public.orders (id) on delete cascade,
    product_id      uuid references public.products (id) on delete set null,
    name            text not null,
    unit_price      numeric(10,2) not null,
    quantity        integer not null check (quantity > 0),
    customization   text default '',
    created_at      timestamptz not null default now()
);

create index if not exists order_items_order_idx on public.order_items (order_id);

-- ---------------------------------------------------------------------
-- chats / messages
-- ---------------------------------------------------------------------
create table if not exists public.chats (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null unique references auth.users (id) on delete cascade,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists chats_user_idx on public.chats (user_id);

create table if not exists public.messages (
    id          uuid primary key default uuid_generate_v4(),
    chat_id     uuid not null references public.chats (id) on delete cascade,
    sender_id   uuid not null references auth.users (id) on delete cascade,
    sender_role text not null check (sender_role in ('customer', 'admin')),
    body        text not null,
    seen        boolean not null default false,
    created_at  timestamptz not null default now()
);

create index if not exists messages_chat_idx on public.messages (chat_id);

-- Make messages broadcast over Supabase Realtime
alter publication supabase_realtime add table public.messages;

-- ---------------------------------------------------------------------
-- wishlist
-- ---------------------------------------------------------------------
create table if not exists public.wishlist (
    user_id     uuid not null references auth.users (id) on delete cascade,
    product_id  uuid not null references public.products (id) on delete cascade,
    created_at  timestamptz not null default now(),
    primary key (user_id, product_id)
);

-- =====================================================================
-- Row Level Security
-- =====================================================================

-- Helper: is current user an admin?
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.profiles
        where id = auth.uid() and role = 'admin'
    );
$$;

alter table public.profiles      enable row level security;
alter table public.products      enable row level security;
alter table public.product_images enable row level security;
alter table public.carts         enable row level security;
alter table public.cart_items    enable row level security;
alter table public.orders        enable row level security;
alter table public.order_items   enable row level security;
alter table public.chats         enable row level security;
alter table public.messages      enable row level security;
alter table public.wishlist      enable row level security;

-- ---------------- profiles ----------------
drop policy if exists "profiles_select_self_or_admin" on public.profiles;
create policy "profiles_select_self_or_admin" on public.profiles
    for select using (auth.uid() = id or public.is_admin());

drop policy if exists "profiles_update_self" on public.profiles;
create policy "profiles_update_self" on public.profiles
    for update using (auth.uid() = id) with check (auth.uid() = id);

-- ---------------- products / product_images (public read, admin write) ----------------
drop policy if exists "products_select_public" on public.products;
create policy "products_select_public" on public.products
    for select using (is_active or public.is_admin());

drop policy if exists "products_admin_write" on public.products;
create policy "products_admin_write" on public.products
    for all using (public.is_admin()) with check (public.is_admin());

drop policy if exists "product_images_select_public" on public.product_images;
create policy "product_images_select_public" on public.product_images
    for select using (true);

drop policy if exists "product_images_admin_write" on public.product_images;
create policy "product_images_admin_write" on public.product_images
    for all using (public.is_admin()) with check (public.is_admin());

-- ---------------- carts ----------------
drop policy if exists "carts_owner_all" on public.carts;
create policy "carts_owner_all" on public.carts
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "cart_items_owner_all" on public.cart_items;
create policy "cart_items_owner_all" on public.cart_items
    for all using (
        exists (select 1 from public.carts c where c.id = cart_items.cart_id and c.user_id = auth.uid())
    ) with check (
        exists (select 1 from public.carts c where c.id = cart_items.cart_id and c.user_id = auth.uid())
    );

-- ---------------- orders ----------------
drop policy if exists "orders_owner_select" on public.orders;
create policy "orders_owner_select" on public.orders
    for select using (auth.uid() = user_id or public.is_admin());

drop policy if exists "orders_owner_insert" on public.orders;
create policy "orders_owner_insert" on public.orders
    for insert with check (auth.uid() = user_id);

drop policy if exists "orders_admin_update" on public.orders;
create policy "orders_admin_update" on public.orders
    for update using (public.is_admin()) with check (public.is_admin());

drop policy if exists "order_items_select" on public.order_items;
create policy "order_items_select" on public.order_items
    for select using (
        public.is_admin() or exists (
            select 1 from public.orders o where o.id = order_items.order_id and o.user_id = auth.uid()
        )
    );

drop policy if exists "order_items_insert_owner" on public.order_items;
create policy "order_items_insert_owner" on public.order_items
    for insert with check (
        exists (select 1 from public.orders o where o.id = order_items.order_id and o.user_id = auth.uid())
    );

-- ---------------- chats / messages ----------------
drop policy if exists "chats_owner_or_admin_select" on public.chats;
create policy "chats_owner_or_admin_select" on public.chats
    for select using (auth.uid() = user_id or public.is_admin());

drop policy if exists "chats_owner_insert" on public.chats;
create policy "chats_owner_insert" on public.chats
    for insert with check (auth.uid() = user_id);

drop policy if exists "messages_chat_participants_select" on public.messages;
create policy "messages_chat_participants_select" on public.messages
    for select using (
        public.is_admin() or exists (
            select 1 from public.chats c where c.id = messages.chat_id and c.user_id = auth.uid()
        )
    );

drop policy if exists "messages_chat_participants_insert" on public.messages;
create policy "messages_chat_participants_insert" on public.messages
    for insert with check (
        sender_id = auth.uid() and (
            public.is_admin() or exists (
                select 1 from public.chats c where c.id = messages.chat_id and c.user_id = auth.uid()
            )
        )
    );

drop policy if exists "messages_seen_update" on public.messages;
create policy "messages_seen_update" on public.messages
    for update using (
        public.is_admin() or exists (
            select 1 from public.chats c where c.id = messages.chat_id and c.user_id = auth.uid()
        )
    );

-- ---------------- wishlist ----------------
drop policy if exists "wishlist_owner_all" on public.wishlist;
create policy "wishlist_owner_all" on public.wishlist
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);


-- =====================================================================
-- Seed sample products (delete these or replace with your own).
-- =====================================================================
insert into public.products (name, slug, description, price, stock, category, cover_image, is_featured)
values
  ('Strawberry Milk Bookmark', 'strawberry-milk-bookmark',
   'A pastel pink bookmark with a hand-drawn strawberry milk carton. Laminated for everyday cuteness.',
   75.00, 30, 'bookmarks',
   'https://images.unsplash.com/photo-1519682337058-a94d519337bc?auto=format&fit=crop&w=900&q=70', true),
  ('Cloud Pearl Keychain', 'cloud-pearl-keychain',
   'Acrylic cloud charm with tiny pearl beads. Comes attached to a soft pink lobster clasp.',
   120.00, 22, 'keychains',
   'https://images.unsplash.com/photo-1611923134239-b9be5816e23d?auto=format&fit=crop&w=900&q=70', true),
  ('Polaroid Memory Set (10)', 'polaroid-memory-set-10',
   'Ten matte polaroid prints with pastel border. Send us your favourite snaps and we''ll print and pack them with love.',
   180.00, 50, 'polaroids',
   'https://images.unsplash.com/photo-1551836022-d5d88e9218df?auto=format&fit=crop&w=900&q=70', true),
  ('Mini Bouquet Card', 'mini-bouquet-card',
   'Handmade paper bouquet card - the perfect surprise tucked inside a gift.',
   95.00, 18, 'crafts',
   'https://images.unsplash.com/photo-1490750967868-88aa4486c946?auto=format&fit=crop&w=900&q=70', true),
  ('Coquette Bow Bookmark', 'coquette-bow-bookmark',
   'Soft pink bookmark with a satin ribbon bow. So cute it almost makes you read more.',
   90.00, 25, 'bookmarks',
   'https://images.unsplash.com/photo-1457369804613-52c61a468e7d?auto=format&fit=crop&w=900&q=70', false),
  ('Sanrio-style Charm Keychain', 'sanrio-style-charm-keychain',
   'Tiny pastel charm keychain, hand-assembled with cute resin pieces.',
   135.00, 15, 'keychains',
   'https://images.unsplash.com/photo-1606760227091-3dd870d97f1d?auto=format&fit=crop&w=900&q=70', false),
  ('Vintage Polaroid Pack (6)', 'vintage-polaroid-pack-6',
   'Six warm-toned polaroid prints with a vintage matte finish.',
   120.00, 40, 'polaroids',
   'https://images.unsplash.com/photo-1542038784456-1ea8e935640e?auto=format&fit=crop&w=900&q=70', false),
  ('Handmade Sticker Pack', 'handmade-sticker-pack',
   'A bundle of 12 hand-drawn pastel stickers. Perfect for journals & laptops.',
   85.00, 60, 'crafts',
   'https://images.unsplash.com/photo-1606293459209-d6c93f53a3a3?auto=format&fit=crop&w=900&q=70', false)
on conflict (slug) do nothing;
