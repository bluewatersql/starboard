# Starboard Chat Frontend - Quickstart Guide

This guide will help you get the Starboard Chat frontend up and running in minutes.

---

## Prerequisites

- **Node.js**: v18.17 or later (recommended: v20+)
- **npm**: v9+ (comes with Node.js)
- **Python**: 3.10+ (for backend)
- **Backend Dependencies**: Installed via `uv` or `pip`

Check your versions:
```bash
node --version   # Should be v18.17+
npm --version    # Should be v9+
python --version # Should be 3.10+
```

---

## Quick Start (6 Steps)

### 1. Start Backend Server

In a **separate terminal** (leave this running):

```bash
cd /<<PATH>>/job-agent/packages/starboard-server
uvicorn starboard_server.main:app --reload --port 8000
```

**Expected output**:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**If you see errors**:
- `ModuleNotFoundError`: Install backend dependencies first
  ```bash
  cd packages/starboard-server
  uv pip install -e .
  # OR
  pip install -e .
  ```
- `Port already in use`: Kill the process or use a different port
  ```bash
  lsof -ti:8000 | xargs kill -9
  ```
- Missing environment variables: Create `.env` file in `packages/starboard-server/`:
  ```bash
  # Required
  LLM_API_KEY=<your-llm-api-key>
  LLM_PROVIDER=openai
  LLM_MODEL=databricks-claude-sonnet-4-5
  ```

**Verify backend is running**:
```bash
curl http://localhost:8000/health/ready
# Should return: {"status":"healthy",...}
```

**Keep this terminal running!** The backend must stay active for the frontend to work.

---

### 2. Navigate to Frontend Directory

In a **new terminal**:

```bash
cd /<<PATH>>/job-agent/frontend
```

### 3. Install Dependencies

```bash
npm install
```

**Expected output**: ~513 packages installed in ~30 seconds

**If you see errors**:
- `ERESOLVE` errors: Run `npm install --legacy-peer-deps`
- Permission errors: Run with `sudo` or fix npm permissions
- Network errors: Check internet connection or try with VPN off

### 4. Configure Environment Variables

Create `.env.local` file in the `frontend` directory:

```bash
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_BASE_PATH=/api
EOF
```

**Important**: The backend must be running at this URL. Adjust if different.

**For Databricks App deployment** (later):
```bash
NEXT_PUBLIC_API_URL=https://your-databricks-workspace.cloud.databricks.com
NEXT_PUBLIC_API_BASE_PATH=/api
```

### 5. Start Frontend Development Server

```bash
npm run dev
```

**Expected output**:
```
▲ Next.js 15.0.3
- Local:        http://localhost:3000
- Ready in 2.1s
```

**If port 3000 is already in use**:
```bash
npm run dev -- -p 3001  # Use port 3001 instead
```

### 6. Open in Browser

Navigate to: **http://localhost:3000**

You should see the Starboard Chat interface with:
- Sidebar on the left (conversation list)
- Chat area in the center
- Theme toggle (sun/moon icon)

---

## Verify Everything is Working

You should now have:
- ✅ **Backend running** in terminal 1 (port 8000)
- ✅ **Frontend running** in terminal 2 (port 3000)
- ✅ **Browser open** to http://localhost:3000

### Quick Health Check

Test backend connectivity:

```bash
# In a third terminal (optional)
curl http://localhost:8000/health/ready
```

**Expected response**:
```json
{
  "status": "healthy",
  "service": "chat_api",
  "version": "2.0"
}
```

**If backend health check fails**:
- Check terminal 1 for backend errors
- Verify backend is running on port 8000
- Ensure environment variables are set (`.env` in `packages/starboard-server/`)

---

## Testing the UI

### Test 1: Create a Conversation

1. Click **"New Conversation"** button in sidebar
2. You should see:
   - Success notification (green toast, bottom-right)
   - New conversation appears in sidebar
   - Chat area becomes active

**If this fails**:
- Check browser console (F12) for errors
- Verify backend `/api/chat/conversations` endpoint is working:
  ```bash
  curl -X POST http://localhost:8000/api/chat/conversations \
    -H "Content-Type: application/json" \
    -d '{"user_id": "test_user"}'
  ```

### Test 2: Send a Message

1. Type a message in the input field at the bottom
2. Press **Enter** or click the **Send** button
3. You should see:
   - Your message appears immediately (optimistic update)
   - Connection indicator (green dot in header)
   - Assistant response starts streaming

**If messages don't send**:
- Check browser Network tab (F12 → Network)
- Look for POST to `/api/chat/conversations/{id}/messages`
- Check for 202 Accepted response

### Test 3: Real-Time Streaming

1. After sending a message, watch for:
   - Typing indicator (three animated dots)
   - Assistant response appearing word-by-word
   - Tool calls shown as colored chips
   - Final message marked complete

**If streaming doesn't work**:
- Check EventSource connection in Network tab
- Look for `/api/chat/conversations/{id}/stream`
- Status should be "pending" (long-lived connection)
- Check browser console for SSE errors

### Test 4: Theme Toggle

1. Click the **sun/moon icon** in sidebar header
2. Theme should switch between light and dark
3. Preference saved to localStorage
4. Persists across page refreshes

### Test 5: Search Conversations

1. Create multiple conversations
2. Type in the search box at top of sidebar
3. Conversations filter in real-time

---

## IDE Setup (VS Code / Cursor)

### Install Recommended Extensions

1. **ESLint** - `dbaeumer.vscode-eslint`
2. **Prettier** - `esbenp.prettier-vscode`
3. **TypeScript** - Built-in (ensure enabled)

### Configure VS Code Settings

Create `.vscode/settings.json` in workspace root:

```json
{
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "typescript.tsdk": "frontend/node_modules/typescript/lib",
  "typescript.enablePromptUseWorkspaceTsdk": true,
  "[typescript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "[typescriptreact]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  }
}
```

### Enable TypeScript Checking

In VS Code:
1. Open any `.tsx` file
2. Click TypeScript version in bottom-right
3. Select "Use Workspace Version"

### Resolve Import Errors

If you see "Cannot find module '@/...'" errors:

1. Restart TypeScript server:
   - `Cmd/Ctrl + Shift + P`
   - Type "TypeScript: Restart TS Server"
   - Select and execute

2. Verify `tsconfig.json` has correct paths:
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

### Fix ESLint Errors

If you see linting errors:

```bash
cd frontend
npm run lint
```

Auto-fix many issues:
```bash
npm run lint -- --fix
```

---

## Common Issues & Solutions

### Issue: "Module not found" errors

**Solution**:
```bash
rm -rf node_modules package-lock.json
npm install
```

### Issue: TypeScript errors about missing types

**Solution**:
```bash
npm install --save-dev @types/node @types/react @types/react-dom
```

### Issue: Hot reload not working

**Solution**:
1. Stop dev server (Ctrl+C)
2. Clear Next.js cache:
   ```bash
   rm -rf .next
   ```
3. Restart: `npm run dev`

### Issue: "EADDRINUSE" - Port already in use

**Solution**:
```bash
# Find and kill process on port 3000
lsof -ti:3000 | xargs kill -9

# Or use different port
npm run dev -- -p 3001
```

### Issue: API requests fail with CORS errors

**Solution**:
1. Verify backend CORS is configured for `http://localhost:3000`
2. Check `packages/starboard-server/starboard_server/main.py`:
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["http://localhost:3000", ...],
       ...
   )
   ```

### Issue: SSE connection fails immediately

**Solution**:
1. Check browser console for error messages
2. Verify conversation ID is valid
3. Test SSE endpoint manually:
   ```bash
   curl -N http://localhost:8000/api/chat/conversations/{id}/stream
   ```

### Issue: Environment variables not loading

**Solution**:
1. Ensure `.env.local` exists in `frontend/` directory
2. Variables must start with `NEXT_PUBLIC_` to be available in browser
3. Restart dev server after changing env vars
4. Check loaded env vars:
   ```javascript
   console.log(process.env.NEXT_PUBLIC_API_URL);
   ```

---

## Development Workflow

### File Structure

```
frontend/
├── app/
│   ├── layout.tsx          # Root layout (providers)
│   ├── page.tsx            # Home page
│   └── globals.css         # Global styles
├── components/
│   ├── chat/               # Chat components
│   ├── conversations/      # Sidebar components
│   └── common/             # Shared components
├── lib/
│   ├── api/                # API client
│   ├── hooks/              # React hooks
│   ├── sse/                # SSE client
│   ├── store/              # Zustand stores
│   ├── theme/              # MUI theme
│   └── types/              # TypeScript types
└── public/                 # Static assets
```

### Making Changes

1. **Edit component**: Changes hot-reload automatically
2. **Add dependency**: Run `npm install <package>`
3. **New component**: Follow existing patterns in `components/`
4. **Update types**: Edit `lib/types/api.ts`
5. **State management**: Use Zustand stores in `lib/store/`

### Debugging

**Browser DevTools** (F12):
- **Console**: Error messages, logs
- **Network**: API calls, SSE connections
- **Application → Local Storage**: Zustand persistence
- **React DevTools**: Component tree (install extension)

**React Query DevTools**:
- Automatically available in dev mode
- Click floating icon (bottom-left)
- Shows query status, cache, mutations

**Next.js DevTools**:
- Install: `npm install @next/devtools`
- Shows route info, performance metrics

---

## Building for Production

### Create Production Build

```bash
npm run build
```

**Expected output**:
```
Route (app)                Size     First Load JS
┌ ○ /                     X kB          XX kB
└ ○ /api/...              ...          ...
```

### Test Production Build Locally

```bash
npm start
```

Access at: `http://localhost:3000`

### Optimize Build

If build is slow or large:

1. **Analyze bundle**:
   ```bash
   npm install --save-dev @next/bundle-analyzer
   ```
   
   Add to `next.config.ts`:
   ```typescript
   const withBundleAnalyzer = require('@next/bundle-analyzer')({
     enabled: process.env.ANALYZE === 'true',
   })
   
   module.exports = withBundleAnalyzer(config)
   ```
   
   Run: `ANALYZE=true npm run build`

2. **Check build output**: Look for large chunks (>500KB)

3. **Optimize imports**: Use specific imports instead of barrel imports

---

## Integration Testing

### Test with Real Backend

1. Ensure backend is running with real LLM API keys
2. Create conversation
3. Send: "What is job 12345 status?"
4. Verify:
   - Agent thinks (shows thinking indicator)
   - Tool calls appear (e.g., "get_job_status")
   - Response streams in real-time
   - Markdown renders correctly
   - Code blocks have syntax highlighting

### Test Error Scenarios

1. **Stop backend**: Verify error notifications appear
2. **Invalid conversation ID**: Should show 404 error
3. **Network offline**: Should show reconnection attempts
4. **Long message**: Should scroll properly

### Test Persistence

1. Create conversation and send messages
2. Refresh page (F5)
3. Verify:
   - Active conversation remembered
   - Sidebar state persists
   - Theme preference persists
   - Must refetch messages (expected)

---

## Next Steps

### Customize the UI

1. **Change theme colors**: Edit `lib/theme/theme.ts`
2. **Modify layout**: Edit `components/chat/ChatContainer.tsx`
3. **Add features**: Follow existing component patterns

### Deploy to Databricks App

See **Task 2.10** documentation (coming soon) for:
- `app.yaml` configuration
- Environment setup
- Authentication passthrough
- Deployment steps

### Add Features

Ideas for enhancement:
- **Message regeneration**: Add retry button
- **Copy message**: Add copy button to messages
- **Export conversation**: Download as JSON/Markdown
- **Voice input**: Add speech-to-text
- **File upload**: Support attachments
- **User profiles**: Avatar customization

---

## Getting Help

### Check Logs

**Browser Console** (F12):
```javascript
// View SSE connection state
// Look for "sse_stream_started", "sse_event_sent", etc.
```

**Backend Logs**:
```bash
# Backend should log all API calls
tail -f backend.log
```

### Common Error Messages

| Error | Meaning | Solution |
|-------|---------|----------|
| `Failed to fetch` | Can't reach backend | Check backend is running |
| `404 Not Found` | Invalid conversation ID | Create new conversation |
| `CORS policy` | CORS not configured | Update backend CORS settings |
| `EventSource failed` | SSE connection issue | Check conversation exists |
| `Hydration error` | SSR mismatch | Clear `.next/` and rebuild |

### Debug Checklist

- [ ] Backend running on correct port?
- [ ] `.env.local` file exists with correct URL?
- [ ] Browser console shows no errors?
- [ ] Network tab shows successful API calls?
- [ ] SSE connection established (check Network → EventStream)?
- [ ] React Query DevTools shows data loading?

---

## Success Criteria

You've successfully set up the UI when you can:

✅ Open the app in browser  
✅ See the sidebar with theme toggle  
✅ Create a new conversation  
✅ Send a message  
✅ See assistant response stream in real-time  
✅ See markdown rendering (try: "Show me a code example")  
✅ Toggle light/dark theme  
✅ Search conversations  
✅ Delete a conversation  

**Congratulations!** Your Starboard Chat frontend is running. 🎉

---

## Appendix: Complete Setup Script

Save as `setup.sh` in the **project root** and run with `bash setup.sh`:

```bash
#!/bin/bash
set -e

echo "🚀 Setting up Starboard Chat (Backend + Frontend)..."
echo ""

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Check Node.js version
echo "📋 Checking prerequisites..."
NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js 18+ required. Current: $(node -v)"
    exit 1
fi
echo "✅ Node.js version OK: $(node -v)"

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "✅ Python version: $PYTHON_VERSION"

echo ""
echo "🔧 Setting up Backend..."
cd "$PROJECT_ROOT/packages/starboard-server"

# Check if backend dependencies are installed
if ! python3 -c "import starboard_server" 2>/dev/null; then
    echo "📦 Installing backend dependencies..."
    uv pip install -e . || pip install -e .
else
    echo "✅ Backend dependencies already installed"
fi

# Check for backend .env
if [ ! -f .env ]; then
    echo "⚠️  Backend .env not found"
    echo "   Create packages/starboard-server/.env with:"
    echo "   LLM_API_KEY=<your-llm-api-key>"
    echo "   LLM_PROVIDER=openai"
    echo "   LLM_MODEL=databricks-claude-sonnet-4-5"
fi

echo ""
echo "🎨 Setting up Frontend..."
cd "$PROJECT_ROOT/frontend"

# Install frontend dependencies
echo "📦 Installing frontend dependencies..."
npm install

# Create .env.local if it doesn't exist
if [ ! -f .env.local ]; then
    echo "⚙️  Creating .env.local..."
    cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_BASE_PATH=/api
EOF
    echo "✅ Created .env.local"
else
    echo "✅ .env.local already exists"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "To start the application:"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Terminal 1 (Backend):"
echo "  cd $PROJECT_ROOT/packages/starboard-server"
echo "  uvicorn starboard_server.main:app --reload --port 8000"
echo ""
echo "Terminal 2 (Frontend):"
echo "  cd $PROJECT_ROOT/frontend"
echo "  npm run dev"
echo ""
echo "Then open: http://localhost:3000"
echo ""
```

Make executable and run:
```bash
chmod +x setup.sh
./setup.sh
```

---

**Last Updated**: 2025-11-16  
**Frontend Version**: 1.0.0  
**Backend Required**: Phase 1 complete (v2 API)

