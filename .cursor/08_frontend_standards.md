# 08 – Frontend Standards

Rules for the Next.js frontend application under `frontend/`.

---

## Stack & Versions

- **Framework**: Next.js 16 with App Router, React 19
- **UI**: Material UI v7 (Emotion) — primary component layer
- **Styling**: Tailwind CSS v4 via PostCSS (`@tailwindcss/postcss`) — global tokens and baseline only
- **State**: Zustand v5 (client), TanStack React Query (server/cache)
- **Validation**: Zod v4 at API boundaries with contract tests
- **Streaming**: `eventsource-parser` + custom `EventSourceClient` in `lib/sse/`
- **Charts**: Recharts
- **TypeScript**: strict mode, `bundler` module resolution, `@/` path alias

---

## Project Structure

```
frontend/
├── app/                    # Next.js App Router (pages, layouts)
├── components/             # Feature-oriented component folders
│   ├── chat/               # Chat experience (messages, tools, reports, thinking)
│   ├── conversations/      # Sidebar, list, search
│   ├── config/             # Domain/model configuration
│   ├── common/             # Cross-cutting UI (errors, loading, dialogs)
│   ├── home/               # Landing page (hero, example queries)
│   └── layout/             # App shell (footer, etc.)
├── lib/
│   ├── api/                # REST client (fetch-based), endpoint modules
│   ├── store/              # Zustand stores
│   ├── hooks/              # Custom React hooks
│   ├── sse/                # SSE client, event handlers, error types
│   ├── types/              # TypeScript types (hand-maintained + generated)
│   ├── validation/         # Zod schemas + contract tests
│   ├── utils/              # Logger, sanitize, file download, etc.
│   └── theme/              # MUI theme, ThemeProvider, EmotionRegistry
└── public/                 # Static assets
```

---

## Conventions

### File Naming & Organization

MUST: PascalCase for component files (`ChatContainer.tsx`, `MessageList.tsx`).
MUST: Use `index.ts` barrel exports for feature folders.
MUST: Co-locate tests as `__tests__/*.test.tsx` next to or under the feature folder.
MUST: Use `@/` import alias for all internal imports (maps to `frontend/`).

### Components

MUST: Use `"use client"` directive only where hooks or browser APIs are needed.
SHOULD: Use React Server Components for static shells; client islands for interactivity.
MUST: Wrap `useSearchParams()` in `<Suspense>` (required for static export).
SHOULD: Use MUI `sx` prop for component-level styling; avoid inline `style` objects.
SHOULD: Use Tailwind only for global/theme tokens in `globals.css`, not as the primary styling layer.

### State Management

MUST: Use Zustand for client-side UI and conversation state.
MUST: Use TanStack React Query for server data fetching and caching.
SHOULD: Only use `persist` middleware on stores that need cross-session durability.
SHOULD: Use selectors in store hooks (`useXStore((s) => s.field)`) to minimize re-renders.
SHOULD: Sync React Query results into Zustand only when cross-component reactivity requires it.

**Query Client defaults:**
- `staleTime`: 5 minutes
- `gcTime`: 30 minutes
- `refetchOnWindowFocus`: false

### API Calls

MUST: Use the shared `lib/api/client.ts` module (fetch-based); do not use Axios or raw fetch in components.
MUST: API base URL comes from `NEXT_PUBLIC_API_URL` environment variable.
MUST: Validate SSE event payloads with Zod schemas from `lib/validation/event-schemas.ts`.
SHOULD: Use typed API response types from `lib/types/api.ts`.

### TypeScript

MUST: `strict: true` in tsconfig — no `any` without explicit justification.
MUST: Keep `generated-api.ts` and `generated-schemas.ts` auto-generated; do not hand-edit.
MUST: Maintain Zod contract tests (`lib/validation/__tests__/`) to guard backend/frontend drift.

### Testing

MUST: Use Jest + Testing Library (`@testing-library/react`, `@testing-library/user-event`).
MUST: Wrap components that use MUI in `ThemeProvider` + `createTheme()` in test renders.
MUST: Mock ESM-only dependencies in Jest (e.g. `react-markdown`, `remark-gfm`).
MUST: Maintain contract tests for API response shapes and SSE event schemas.

SHOULD: Co-locate test files with their components (`__tests__/` subfolder pattern).

**Coverage thresholds (current):** branches 70%, functions/lines/statements 50%.

### Deployment Constraints

MUST: Support `output: 'export'` (static export) for Databricks Apps deployment.
MUST: Use `images.unoptimized: true` (required for static export).
MUST: Use query params for dynamic routes (e.g. `/chat?id=`) — not dynamic segments.
MUST: Handle `trailingSlash` differences between dev (false) and production (true).

---

## Anti-Patterns

NEVER:
- Import from `node_modules` paths directly; use package names.
- Use `any` without a `// eslint-disable` comment explaining why.
- Fetch API endpoints directly from components; use `lib/api/` modules.
- Put business logic in components; extract to `lib/` hooks or utilities.
- Edit `generated-api.ts` or `generated-schemas.ts` by hand.
- Use `localStorage` directly; use Zustand `persist` middleware.
- Skip `Suspense` around `useSearchParams()` — breaks static export.
