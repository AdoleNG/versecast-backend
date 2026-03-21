create extension if not exists pgcrypto;

create table churches (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  country text,
  timezone text not null default 'UTC',
  contact_email text,
  subscription_status text not null default 'trial',
  plan_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table users (
  id uuid primary key,
  church_id uuid not null references churches(id) on delete cascade,
  full_name text,
  email text not null unique,
  role text not null check (role in ('owner', 'operator')),
  status text not null default 'active' check (status in ('active', 'invited', 'suspended')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index one_owner_per_church
on users (church_id)
where role = 'owner';

create table church_settings (
  id uuid primary key default gen_random_uuid(),
  church_id uuid not null unique references churches(id) on delete cascade,
  display_mode text not null default 'assist' check (display_mode in ('assist', 'auto')),
  approval_required boolean not null default true,
  hold_seconds integer not null default 10,
  default_translation text not null default 'KJV',
  max_range_verses integer not null default 15,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table service_sessions (
  id uuid primary key default gen_random_uuid(),
  church_id uuid not null references churches(id) on delete cascade,
  title text,
  session_type text not null default 'live' check (session_type in ('live', 'rehearsal', 'test')),
  status text not null default 'scheduled' check (status in ('scheduled', 'live', 'ended', 'cancelled')),
  started_at timestamptz,
  ended_at timestamptz,
  created_by uuid references users(id),
  ended_by uuid references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_users_church_id on users(church_id);
create index idx_service_sessions_church_id on service_sessions(church_id);
create index idx_service_sessions_status on service_sessions(status);
create index idx_service_sessions_started_at on service_sessions(started_at);