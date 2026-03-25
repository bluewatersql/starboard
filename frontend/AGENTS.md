# frontend/ — Next.js Web UI

This directory contains the Starboard web frontend.

## Stack

- **Framework:** Next.js 16 with App Router
- **UI:** Material UI v7 + Tailwind CSS v4
- **State:** Zustand (client state) + TanStack Query (server state)
- **Streaming:** EventSource (SSE) with `eventsource-parser`
- **Type Safety:** Zod v4 schemas with API contract tests
- **Charts:** Recharts
- **Testing:** Jest + React Testing Library

## Directory Structure

```
frontend/
├── app/              # Next.js App Router pages and layouts
├── components/       # Reusable React components
├── lib/              # Client utilities, API clients, hooks
├── public/           # Static assets
├── docs/             # Frontend-specific documentation
├── __mocks__/        # Jest module mocks
└── jest.config.ts    # Jest configuration
```

## Key Architecture Patterns

- **SSE streaming**: The chat UI consumes Server-Sent Events from the backend `/stream` endpoint
- **Zustand stores**: UI state (conversation, settings) lives in Zustand stores under `lib/store/`
- **Zod contracts**: API response shapes are validated at runtime with Zod schemas; `tests/contract/` enforces alignment with backend
- **Material UI theming**: Theme configuration in `lib/theme/`

## Development

```bash
make dev-frontend       # Start dev server at http://localhost:3000
make test-frontend      # Run Jest tests
make lint-frontend      # ESLint + TypeScript type-check
```
