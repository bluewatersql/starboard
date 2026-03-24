# Frontend Debug Logging

## Overview

The frontend now uses a centralized debug utility (`lib/utils/debug.ts`) that controls console logging based on environment configuration.

## Configuration

Set the `NEXT_PUBLIC_DEBUG` environment variable to enable debug logging:

```bash
# In .env.local
NEXT_PUBLIC_DEBUG=true
```

Or start the dev server with:
```bash
NEXT_PUBLIC_DEBUG=true npm run dev
```

## Behavior

- **Development mode** (`NODE_ENV=development`): Debug logs enabled by default
- **Production mode**: Debug logs disabled unless explicitly enabled
- **Error logs**: Always displayed (even in production)

## Usage

```typescript
import { debug } from '@/lib/utils/debug';

// Only logs in debug mode
debug.log('Processing message:', message);
debug.warn('Rate limit approaching:', usage);
debug.info('Connection established');

// Always logs (even in production)
debug.error('Failed to send message:', error);

// Check if debug is enabled
if (debug.isEnabled()) {
  // Expensive debug operation
}
```

## Files Updated

The following files now use the debug utility:

- ✅ `lib/sse/event-handlers.ts` - Event handling debug logs
- ✅ `lib/sse/EventSourceClient.ts` - SSE connection logs
- ✅ `lib/hooks/useSSE.ts` - Hook lifecycle logs
- ✅ `lib/store/messageStore.ts` - Store operations logs
- ✅ `lib/hooks/useClarification.ts` - Clarification handling logs
- ✅ `lib/hooks/useSlashCommands.ts` - Command execution logs

## Error Handling

All `console.error()` calls remain unchanged - errors should always be visible to help with debugging production issues.

Test files (`*.test.ts`, `*.test.tsx`) still use direct `console.*` calls as they're not part of the production bundle.

