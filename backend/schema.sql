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
