# PDF Chat Frontend

Vite + React frontend for PDF Chat. The UI lets users sign up, verify email, log in, upload documents, monitor processing, ask questions, view saved chat history, and manage documents.

## Stack

| Area | Tooling |
| --- | --- |
| App | Vite, React, TypeScript |
| Auth client | Supabase JS |
| Icons | Lucide React |
| Styling | Custom CSS in `src/styles.css` |
| Backend calls | Fetch wrapper in `src/lib/api.ts` |

## Features

- Supabase email/password auth
- Signup form with name, email regex validation, password confirmation, and show/hide password buttons
- Check-email verification screen after signup
- Login form with email validation and friendly unverified-email error
- Modern light/dark theme toggle
- Responsive dashboard layout
- Document upload with progress feedback
- Document list with status dots and skeleton loading
- Latest documents overview
- Chat UI with markdown/table rendering
- Loading answer state
- Clear chat confirmation
- Delete document confirmation
- Toasts for upload/delete success

## Environment

Create `frontend/.env.local`:

```env
VITE_SUPABASE_URL=your_supabase_project_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
VITE_API_URL=http://localhost:8000
```

For deployed frontend, set `VITE_API_URL` to the deployed backend URL.

## Local Development

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## Build

```bash
npm run build
```

Preview production build:

```bash
npm run preview
```

## Supabase Auth Notes

The frontend uses the anon key only:

```ts
createClient(VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY)
```

Do not expose the Supabase service role key in the frontend.

If email confirmation is enabled in Supabase:

1. User signs up.
2. Frontend shows the check-email screen.
3. User verifies email from their inbox.
4. User returns and logs in.

Supabase URL configuration for local development:

```text
Site URL: http://localhost:5173
Redirect URLs: http://localhost:5173/**
```

## Main Files

```text
frontend/src/App.tsx
frontend/src/styles.css
frontend/src/lib/supabase.ts
frontend/src/lib/api.ts
frontend/src/components/auth/
frontend/src/components/dashboard/
frontend/src/components/chat/
frontend/src/components/ui/
```

## Backend API Usage

`src/lib/api.ts` sends the Supabase access token with every protected request:

```http
Authorization: Bearer <supabase_access_token>
```

Important calls:

- `GET /documents`
- `POST /documents/upload`
- `DELETE /documents/{document_id}`
- `POST /chat/query`
- `GET /chat/history/{document_id}`
- `DELETE /chat/history/{document_id}`

## Design Notes

- Brand name: PDF Chat
- Logo and favicon are SVG-based.
- Theme is controlled with `data-theme`.
- Theme choice is saved in local storage.
- User-facing copy avoids technical RAG terms where possible.
