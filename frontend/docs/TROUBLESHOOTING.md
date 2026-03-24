# Troubleshooting Guide - Starboard Chat Frontend

Comprehensive solutions for common issues when developing with the Starboard Chat UI.

---

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [IDE Configuration](#ide-configuration)
3. [Runtime Errors](#runtime-errors)
4. [API Connection Issues](#api-connection-issues)
5. [SSE Streaming Issues](#sse-streaming-issues)
6. [State Management Issues](#state-management-issues)
7. [TypeScript Errors](#typescript-errors)
8. [Build Issues](#build-issues)
9. [Performance Issues](#performance-issues)

---

## Installation Issues

### NPM Install Fails

**Error**: `npm ERR! code ERESOLVE`

**Solution**:
```bash
# Option 1: Use legacy peer deps
npm install --legacy-peer-deps

# Option 2: Force install
npm install --force

# Option 3: Clear cache and reinstall
npm cache clean --force
rm -rf node_modules package-lock.json
npm install
```

### Wrong Node Version

**Error**: `error:0308010C:digital envelope routines::unsupported`

**Solution**:
```bash
# Check version
node --version

# Install Node 18+ using nvm
nvm install 18
nvm use 18

# Or upgrade via package manager
brew upgrade node  # macOS
```

### Permission Errors

**Error**: `EACCES: permission denied`

**Solution**:
```bash
# Fix npm permissions (recommended)
mkdir ~/.npm-global
npm config set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.zshrc
source ~/.zshrc

# Or use sudo (not recommended)
sudo npm install
```

---

## IDE Configuration

### Import Aliases Not Resolving

**Issue**: Red squiggly lines on `@/...` imports

**Solution 1** - Restart TS Server:
```
Cmd/Ctrl + Shift + P
→ "TypeScript: Restart TS Server"
```

**Solution 2** - Verify `tsconfig.json`:
```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./*"]
    }
  }
}
```

**Solution 3** - Create `.vscode/settings.json`:
```json
{
  "typescript.tsdk": "frontend/node_modules/typescript/lib",
  "typescript.enablePromptUseWorkspaceTsdk": true
}
```

### ESLint Not Working

**Issue**: No linting errors shown in IDE

**Solution**:
```bash
# Install ESLint extension
# Then create .vscode/settings.json

{
  "eslint.workingDirectories": [
    { "directory": "frontend", "changeProcessCWD": true }
  ],
  "eslint.validate": [
    "javascript",
    "javascriptreact",
    "typescript",
    "typescriptreact"
  ]
}
```

### Prettier Conflicts with ESLint

**Issue**: Formatting keeps changing back

**Solution**:
```bash
# Install both extensions, then:
npm install --save-dev prettier eslint-config-prettier

# Create .prettierrc
{
  "semi": true,
  "trailingComma": "es5",
  "singleQuote": false,
  "printWidth": 80,
  "tabWidth": 2
}

# Update .eslintrc.json
{
  "extends": ["next/core-web-vitals", "prettier"]
}
```

### IntelliSense Slow/Not Working

**Solution**:
```bash
# Exclude node_modules from search
# .vscode/settings.json
{
  "files.exclude": {
    "**/node_modules": true,
    "**/.next": true
  },
  "typescript.tsserver.maxTsServerMemory": 4096
}
```

---

## Runtime Errors

### Hydration Errors

**Error**: `Error: Hydration failed because the initial UI does not match...`

**Cause**: Client/server render mismatch

**Solution 1** - Check for browser-only code in render:
```typescript
// ❌ Bad
function MyComponent() {
  const data = localStorage.getItem('key'); // SSR fails
  return <div>{data}</div>;
}

// ✅ Good
function MyComponent() {
  const [data, setData] = useState<string | null>(null);
  
  useEffect(() => {
    setData(localStorage.getItem('key'));
  }, []);
  
  return <div>{data}</div>;
}
```

**Solution 2** - Use 'use client' directive:
```typescript
'use client';  // Add at top of file

export function BrowserOnlyComponent() {
  // Now runs only on client
}
```

**Solution 3** - Clear Next.js cache:
```bash
rm -rf .next
npm run dev
```

### React Hook Errors

**Error**: `Rendered more hooks than during the previous render`

**Cause**: Conditional hook calls

**Solution**:
```typescript
// ❌ Bad
function MyComponent({ showData }) {
  if (showData) {
    const data = useQuery(...); // Conditional hook!
  }
}

// ✅ Good
function MyComponent({ showData }) {
  const data = useQuery({
    ...queryOptions,
    enabled: showData  // Conditional execution
  });
}
```

### Module Not Found

**Error**: `Module not found: Can't resolve '@/lib/...'`

**Solution**:
```bash
# Verify file exists
ls -la lib/types/api.ts

# Restart dev server
# Ctrl+C then npm run dev

# If still failing, check tsconfig.json paths
cat tsconfig.json | grep -A 5 "paths"
```

---

## API Connection Issues

### Cannot Connect to Backend

**Error**: `Failed to fetch` or `Network request failed`

**Diagnosis**:
```bash
# Check backend is running
curl http://localhost:8000/health/ready

# Check environment variables
echo $NEXT_PUBLIC_API_URL

# Check browser console for actual URL
# Should see: http://localhost:8000/api/chat/...
```

**Solution 1** - Backend not running:
```bash
cd packages/starboard-server
uvicorn starboard_server.main:app --reload --port 8000
```

**Solution 2** - Wrong URL in .env.local:
```bash
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_BASE_PATH=/api
```

**Solution 3** - Restart dev server after changing env:
```bash
# Must restart for env changes
npm run dev
```

### CORS Errors

**Error**: `Access to fetch at '...' from origin '...' has been blocked by CORS policy`

**Solution** - Update backend CORS:

Edit `packages/starboard-server/starboard_server/main.py`:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 404 Not Found

**Error**: API returns 404

**Diagnosis**:
```bash
# Check endpoint exists
curl http://localhost:8000/health/ready

# Check full API path
curl -v http://localhost:8000/api/chat/conversations
```

**Solution**:
- Verify backend routes are registered in `main.py`
- Check API base path matches between frontend/backend
- Ensure backend Phase 1 is complete

### 500 Internal Server Error

**Solution**:
```bash
# Check backend logs
tail -f packages/starboard-server/backend.log

# Run backend in debug mode
DEBUG=true uvicorn starboard_server.main:app --reload

# Check for missing environment variables
# Backend needs: OPENAI_API_KEY, etc.
```

---

## SSE Streaming Issues

### SSE Connection Immediately Closes

**Error**: `EventSource failed to connect`

**Diagnosis**:
```bash
# Test SSE endpoint manually
curl -N http://localhost:8000/api/chat/conversations/test_123/stream

# Check browser Network tab
# EventStream request should be "pending" (long-lived)
```

**Solution 1** - Invalid conversation ID:
```typescript
// Ensure conversation exists before subscribing
const { data: conversation } = useQuery({
  queryKey: ['conversation', conversationId],
  queryFn: () => api.getConversation(conversationId)
});

// Only connect if conversation exists
useSSE({
  conversationId: conversation ? conversationId : null,
  autoConnect: !!conversation
});
```

**Solution 2** - Backend not configured for SSE:
```python
# In streaming.py endpoint
return StreamingResponse(
    event_generator(...),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Important for nginx
    }
)
```

### No Events Received

**Issue**: SSE connected but no events coming through

**Diagnosis**:
```javascript
// Add logging to EventSourceClient
console.log('EventSource readyState:', eventSource.readyState);
// 0 = CONNECTING, 1 = OPEN, 2 = CLOSED
```

**Solution** - Check event handler registration:
```typescript
const client = new EventSourceClient(url);

// Register handlers BEFORE connecting
Object.values(EventType).forEach((type) => {
  client.on(type, (event) => {
    console.log('Received event:', type, event);
    handleStreamingEvent(event);
  });
});

// Then connect
client.connect();
```

### Reconnection Loop

**Issue**: SSE keeps reconnecting rapidly

**Solution** - Check exponential backoff:
```typescript
// In EventSourceClient.ts
private retryConnection(): void {
  if (this.retryCount < MAX_RETRY_ATTEMPTS) {
    const delay = Math.min(
      DEFAULT_RETRY_INTERVAL_MS * Math.pow(2, this.retryCount),
      MAX_RETRY_INTERVAL_MS
    );
    console.log(`Retrying in ${delay}ms...`);
    setTimeout(() => this.connect(), delay);
  } else {
    console.error('Max retries reached');
    // Stop trying
  }
}
```

---

## State Management Issues

### Store Not Persisting

**Issue**: Zustand state resets on refresh

**Diagnosis**:
```javascript
// Check localStorage in browser
localStorage.getItem('conversation-storage')
```

**Solution 1** - Verify persist middleware:
```typescript
export const useConversationStore = create<State>()(
  persist(
    (set) => ({...}),
    {
      name: 'conversation-storage',
      getStorage: () => localStorage,  // Ensure this is set
    }
  )
)
```

**Solution 2** - Check for serialization errors:
```typescript
// Don't store non-serializable data
// ❌ Bad
set({ messages: new Map() });  // Map can't be serialized

// ✅ Good
set({ messages: {} });  // Plain object
```

### Store Updates Not Reflecting

**Issue**: State changes but UI doesn't update

**Solution** - Use correct Zustand selectors:
```typescript
// ❌ Bad - component won't re-render
const store = useConversationStore();
const messages = store.messages[conversationId];

// ✅ Good - component re-renders on change
const messages = useConversationStore(
  (state) => state.messages[conversationId]
);
```

### Multiple Store Instances

**Issue**: Different parts of app see different state

**Solution** - Ensure singleton stores:
```typescript
// ❌ Bad - creates new store each time
export const createStore = () => create(...);

// ✅ Good - single store instance
export const useMyStore = create(...);
```

---

## TypeScript Errors

### Type 'X' is not assignable to type 'Y'

**Solution** - Check API type definitions:
```typescript
// Ensure frontend types match backend
// lib/types/api.ts should mirror backend Pydantic models

// If backend changed, update frontend types
export interface Message {
  message_id: string;
  content: string;
  role: MessageRole;
  // Add any new fields from backend
  metadata?: Record<string, any>;
}
```

### Property 'X' does not exist on type 'Y'

**Solution 1** - Add optional chaining:
```typescript
// ❌ Error if message is undefined
const content = message.content;

// ✅ Safe
const content = message?.content ?? '';
```

**Solution 2** - Update type definitions:
```typescript
// Add missing property to interface
interface Message {
  // ... existing fields
  tool_calls?: ToolCall[];  // Add this if backend returns it
}
```

### 'any' type errors (strict mode)

**Solution**:
```typescript
// ❌ Bad
const data: any = await fetch(...);

// ✅ Good
const data: ConversationResponse = await fetch(...);

// For unknown data
const data: unknown = await fetch(...);
if (isConversation(data)) {
  // Now TypeScript knows the type
}
```

---

## Build Issues

### Build Fails with Memory Error

**Error**: `FATAL ERROR: Ineffective mark-compacts near heap limit`

**Solution**:
```bash
# Increase Node memory
NODE_OPTIONS="--max-old-space-size=4096" npm run build

# Or add to package.json scripts
{
  "scripts": {
    "build": "NODE_OPTIONS='--max-old-space-size=4096' next build"
  }
}
```

### Build Fails on Unused Variables

**Solution**:
```bash
# Temporarily disable during build
# next.config.ts
const config = {
  eslint: {
    ignoreDuringBuilds: true,  // Not recommended for prod
  },
  typescript: {
    ignoreBuildErrors: true,  // Not recommended for prod
  }
}

# Better: Fix the errors
npm run lint -- --fix
```

### Build Size Too Large

**Solution**:
```bash
# Analyze bundle
npm install --save-dev @next/bundle-analyzer

# Run analysis
ANALYZE=true npm run build

# Common optimizations:
# 1. Use dynamic imports
const HeavyComponent = dynamic(() => import('./HeavyComponent'));

# 2. Remove unused dependencies
npm uninstall <unused-package>

# 3. Use tree-shakeable imports
import { Button } from '@mui/material';  // Not: import Button from '@mui/material/Button';
```

---

## Performance Issues

### Slow Initial Load

**Solution**:
```typescript
// 1. Lazy load heavy components
const ChatContainer = dynamic(() => import('./ChatContainer'), {
  loading: () => <LoadingSkeleton variant="chat" />
});

// 2. Optimize images
import Image from 'next/image';
<Image src="/logo.png" alt="Logo" width={100} height={100} />

// 3. Preload critical data
export async function generateMetadata() {
  // This runs at build time
}
```

### Slow Re-renders

**Solution**:
```typescript
// 1. Memoize expensive computations
const sortedMessages = useMemo(
  () => messages.sort(...),
  [messages]
);

// 2. Memoize components
const MessageBubble = memo(({ message }) => {
  // Component code
});

// 3. Use specific Zustand selectors
const activeId = useConversationStore(
  (state) => state.activeConversationId  // Only re-render if this changes
);
```

### Memory Leaks

**Solution**:
```typescript
// 1. Clean up SSE connections
useEffect(() => {
  const client = new EventSourceClient(url);
  client.connect();
  
  return () => {
    client.disconnect();  // Always clean up!
  };
}, [url]);

// 2. Cancel async operations
useEffect(() => {
  let cancelled = false;
  
  fetchData().then(data => {
    if (!cancelled) setData(data);
  });
  
  return () => { cancelled = true; };
}, []);

// 3. Remove event listeners
useEffect(() => {
  const handler = () => {...};
  window.addEventListener('resize', handler);
  
  return () => {
    window.removeEventListener('resize', handler);
  };
}, []);
```

---

## Advanced Debugging

### Enable Verbose Logging

```typescript
// lib/api/client.ts
const apiClient = axios.create({
  baseURL: `${API_URL}${API_BASE_PATH}`,
  headers: { 'Content-Type': 'application/json' }
});

// Add request/response interceptors
apiClient.interceptors.request.use(request => {
  console.log('API Request:', request.method, request.url, request.data);
  return request;
});

apiClient.interceptors.response.use(
  response => {
    console.log('API Response:', response.status, response.data);
    return response;
  },
  error => {
    console.error('API Error:', error.response?.status, error.response?.data);
    return Promise.reject(error);
  }
);
```

### Debug SSE Events

```typescript
// lib/sse/EventSourceClient.ts
this.eventSource.onmessage = (event: MessageEvent) => {
  console.log('SSE Raw Event:', event);
  
  try {
    const parsed = JSON.parse(event.data);
    console.log('SSE Parsed:', parsed.type, parsed);
    
    // Handler logic...
  } catch (error) {
    console.error('SSE Parse Error:', error, event.data);
  }
};
```

### Debug React Query

```typescript
// app/layout.tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      onSuccess: (data) => {
        console.log('Query Success:', data);
      },
      onError: (error) => {
        console.error('Query Error:', error);
      }
    }
  }
});

// Use React Query DevTools (already included)
```

### Profile Performance

```typescript
// Add to component
import { Profiler } from 'react';

<Profiler
  id="MessageList"
  onRender={(id, phase, actualDuration) => {
    console.log(`${id} (${phase}) took ${actualDuration}ms`);
  }}
>
  <MessageList />
</Profiler>
```

---

## Getting More Help

### Useful Commands

```bash
# Check all errors
npm run build 2>&1 | grep -i error

# List all dependencies
npm list --depth=0

# Check for outdated packages
npm outdated

# Verify TypeScript config
npx tsc --showConfig

# Clear all caches
rm -rf .next node_modules package-lock.json
npm install
```

### Logs to Check

1. **Browser Console** (F12)
2. **Network Tab** (F12 → Network)
3. **React Query DevTools** (floating icon)
4. **Backend logs** (`tail -f backend.log`)
5. **Next.js build output** (`npm run build`)

### File Locations

```
frontend/
├── .env.local              # Environment variables
├── .next/                  # Build output (can delete)
├── node_modules/           # Dependencies (can delete)
├── package.json            # Dependency versions
└── tsconfig.json           # TypeScript config
```

---

**If all else fails**:

```bash
# Nuclear option: Fresh start
cd frontend
rm -rf .next node_modules package-lock.json
npm install
npm run dev
```

**Still stuck?** Check:
1. GitHub Issues: [Link to repo]
2. Backend logs for API errors
3. Browser console for client errors
4. This file's appendix below

---

## Appendix: Error Code Reference

| Code | Meaning | Solution |
|------|---------|----------|
| ECONNREFUSED | Backend not running | Start backend server |
| EADDRINUSE | Port already in use | Use different port or kill process |
| MODULE_NOT_FOUND | Missing dependency | Run `npm install` |
| CORS_ERROR | CORS not configured | Update backend CORS settings |
| HYDRATION_ERROR | SSR/CSR mismatch | Use 'use client' or useEffect |
| HOOK_ERROR | Incorrect hook usage | Check hook rules |
| TYPE_ERROR | TypeScript error | Fix type definitions |

---

**Last Updated**: 2025-11-16  
**Version**: 1.0.0

