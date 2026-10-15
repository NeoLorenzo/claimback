-- ClaimBack hosted app: the worker (service role) writes, signed-in users read
-- only their own rows. Users never write these tables directly; they ask the
-- worker API, which checks ownership and quotas, then records a job.

create table public.runs (
  id          text primary key,
  owner       uuid not null references auth.users (id) on delete cascade,
  case_name   text not null,
  mode        text not null check (mode in ('mock', 'live')),
  status      text not null,
  verdict     text,
  stages      jsonb not null default '{}',
  packet_path text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table public.events (
  id         bigint generated always as identity primary key,
  owner      uuid not null references auth.users (id) on delete cascade,
  run_id     text,
  case_id    text,
  ts         timestamptz not null,
  agent      text not null,
  kind       text not null,
  message    text not null,
  data       jsonb not null default '{}',
  check (run_id is not null or case_id is not null)
);
create index events_run_idx on public.events (run_id, id);
create index events_case_idx on public.events (case_id, id);
create index events_owner_idx on public.events (owner);

create table public.cases (
  id         text primary key,
  owner      uuid not null references auth.users (id) on delete cascade,
  run_id     text not null,
  status     text not null,
  stage      text not null,
  data       jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index cases_owner_idx on public.cases (owner);

create table public.jobs (
  id         bigint generated always as identity primary key,
  owner      uuid not null references auth.users (id) on delete cascade,
  kind       text not null,
  payload    jsonb not null default '{}',
  status     text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
  error      text,
  result     jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index jobs_owner_created_idx on public.jobs (owner, created_at);
create index jobs_kind_created_idx on public.jobs (kind, created_at);

create table public.worker_heartbeat (
  id text primary key,
  at timestamptz not null
);

create index runs_owner_idx on public.runs (owner);

create function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;
create trigger runs_touch before update on public.runs for each row execute function public.touch_updated_at();
create trigger cases_touch before update on public.cases for each row execute function public.touch_updated_at();

-- Row-level security: read your own rows; no client writes at all.
alter table public.runs enable row level security;
alter table public.events enable row level security;
alter table public.cases enable row level security;
alter table public.jobs enable row level security;
alter table public.worker_heartbeat enable row level security;

create policy "own runs" on public.runs for select to authenticated using (owner = (select auth.uid()));
create policy "own events" on public.events for select to authenticated using (owner = (select auth.uid()));
create policy "own cases" on public.cases for select to authenticated using (owner = (select auth.uid()));
create policy "own jobs" on public.jobs for select to authenticated using (owner = (select auth.uid()));
create policy "worker status" on public.worker_heartbeat for select to authenticated using (true);

revoke insert, update, delete, truncate on public.runs, public.events, public.cases, public.jobs,
  public.worker_heartbeat from anon, authenticated;
revoke all on public.runs, public.events, public.cases, public.jobs, public.worker_heartbeat from anon;
grant select on public.runs, public.events, public.cases, public.jobs, public.worker_heartbeat to authenticated;
grant all on public.runs, public.events, public.cases, public.jobs, public.worker_heartbeat to service_role;

-- Live timeline: the browser subscribes to new rows (RLS still applies).
alter publication supabase_realtime add table public.events, public.runs, public.cases, public.jobs;

-- Storage: private buckets, one folder per user (<user id>/...).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('uploads', 'uploads', false, 10485760, array['text/plain', 'text/markdown', 'application/pdf']),
  ('packets', 'packets', false, 10485760, array['text/html', 'text/markdown']);

create policy "upload own documents" on storage.objects for insert to authenticated
  with check (bucket_id = 'uploads' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "read own documents" on storage.objects for select to authenticated
  using (bucket_id in ('uploads', 'packets') and (storage.foldername(name))[1] = (select auth.uid())::text);
