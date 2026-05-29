-- ============================================================
-- Chat with PDF — Supabase Schema
-- Run this in the Supabase SQL Editor to set up your project
-- ============================================================

-- Documents table
create table if not exists public.documents (
  document_id   uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  filename      text not null,
  storage_path  text not null,
  language      text,
  total_pages   integer,
  status        text not null default 'processing'
                  check (status in ('processing', 'ready', 'failed')),
  error_message text,
  uploaded_at   timestamptz not null default now()
);

-- Index for fast per-user document lookups
create index if not exists documents_user_id_idx
  on public.documents(user_id);

-- Index for status polling
create index if not exists documents_status_idx
  on public.documents(user_id, status);

-- ============================================================
-- Row Level Security
-- Users can only see and modify their own documents
-- The backend uses the service role key which bypasses RLS
-- ============================================================

alter table public.documents enable row level security;

-- Allow users to read their own documents
create policy "Users can view own documents"
  on public.documents for select
  using (auth.uid() = user_id);

-- Allow users to delete their own documents
create policy "Users can delete own documents"
  on public.documents for delete
  using (auth.uid() = user_id);

-- Service role handles insert/update (no user-facing policy needed)

-- ============================================================
-- Chat sessions, messages, and API logs
-- ============================================================

create table if not exists public.chat_sessions (
  session_id  uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  document_id uuid not null references public.documents(document_id) on delete cascade,
  title       text,
  summary     text,
  is_default  boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create unique index if not exists one_default_chat_session_per_document
  on public.chat_sessions(user_id, document_id)
  where is_default = true;

create index if not exists chat_sessions_user_document_idx
  on public.chat_sessions(user_id, document_id);

create table if not exists public.chat_messages (
  message_id  uuid primary key default gen_random_uuid(),
  session_id  uuid not null references public.chat_sessions(session_id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  document_id uuid not null references public.documents(document_id) on delete cascade,
  role        text not null check (role in ('user', 'assistant', 'system')),
  content     text not null,
  citations   jsonb not null default '[]',
  metadata    jsonb not null default '{}',
  created_at  timestamptz not null default now()
);

create index if not exists chat_messages_session_created_idx
  on public.chat_messages(session_id, created_at);

create table if not exists public.api_logs (
  log_id              uuid primary key default gen_random_uuid(),
  user_id             uuid references auth.users(id) on delete set null,
  document_id          uuid references public.documents(document_id) on delete set null,
  session_id           uuid references public.chat_sessions(session_id) on delete set null,
  purpose              text not null check (
                         purpose in (
                           'chat_answer',
                           'memory_summary',
                           'comparison_extraction',
                           'comparison_answer',
                           'document_summary'
                         )
                       ),
  provider             text not null default 'opencode',
  model                text not null,
  status               text not null check (status in ('success', 'error')),
  user_prompt          text,
  latency_ms           integer,
  prompt_tokens        integer,
  completion_tokens    integer,
  total_tokens         integer,
  request_metadata     jsonb not null default '{}',
  response_metadata    jsonb not null default '{}',
  response_content     text,
  raw_response         jsonb,
  error_message        text,
  created_at           timestamptz not null default now()
);

alter table public.api_logs
  add column if not exists response_content text;

alter table public.api_logs
  add column if not exists raw_response jsonb;

alter table public.api_logs
  drop constraint if exists api_logs_purpose_check;

alter table public.api_logs
  add constraint api_logs_purpose_check
  check (
    purpose in (
      'chat_answer',
      'memory_summary',
      'comparison_extraction',
      'comparison_answer',
      'document_summary'
    )
  );

create index if not exists api_logs_user_created_idx
  on public.api_logs(user_id, created_at desc);

create index if not exists api_logs_purpose_created_idx
  on public.api_logs(purpose, created_at desc);

alter table public.chat_sessions enable row level security;
alter table public.chat_messages enable row level security;
alter table public.api_logs enable row level security;

create policy "Users can view own chat sessions"
  on public.chat_sessions for select
  using (auth.uid() = user_id);

create policy "Users can view own chat messages"
  on public.chat_messages for select
  using (auth.uid() = user_id);

create policy "Users can delete own chat sessions"
  on public.chat_sessions for delete
  using (auth.uid() = user_id);

-- API logs are backend-only by default. Add a select policy later if you build an admin/user analytics UI.

-- ============================================================
-- Storage bucket
-- Create manually in Supabase dashboard > Storage,
-- or run via Supabase CLI
-- ============================================================

-- Bucket: chat-with-pdf (private)
-- Path structure: {user_id}/{document_id}/{filename}
-- RLS: users can only access their own folder

-- Storage RLS policies (set in dashboard under Storage > Policies):
--
-- SELECT: (auth.uid())::text = (storage.foldername(name))[1]
-- INSERT: (auth.uid())::text = (storage.foldername(name))[1]
-- DELETE: (auth.uid())::text = (storage.foldername(name))[1]
