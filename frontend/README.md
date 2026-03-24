# Starboard Chat - Frontend

Modern Next.js web interface for the Starboard AI Agent platform with real-time streaming and interactive chat.

## Overview

The Starboard Chat frontend provides:
- **Real-time Streaming**: Live agent reasoning and tool execution via Server-Sent Events (SSE)
- **Interactive Chat**: Full-featured chat interface with conversation management
- **Domain Configuration**: Query, Job, and Pipeline optimization modes
- **Dark/Light Themes**: Material-UI theming with persistent preferences
- **State Management**: Zustand stores with localStorage persistence
- **Type-Safe API**: Full TypeScript integration with backend API

## Tech Stack

- **Framework**: [Next.js 16.0.7](https://nextjs.org/) (App Router, React 19.2.0)
- **UI Library**: [Material-UI (MUI) v7.3.5](https://mui.com/) + Tailwind CSS v4
- **State Management**: [Zustand v5.0.9](https://github.com/pmndrs/zustand)
- **Server Queries**: [TanStack Query v5.90.9 (React Query)](https://tanstack.com/query)
- **Markdown**: [react-markdown v10.1.0](https://github.com/remarkjs/react-markdown)
- **Code Highlighting**: [shiki v3.18.0](https://shiki.style/) with rehype-highlight v7.0.2
- **Charts**: [Recharts v3.5.0](https://recharts.org/)
- **Type Safety**: TypeScript 5.x strict mode + [Zod v4.1.13](https://zod.dev/) schemas
- **Streaming**: EventSource (SSE) with eventsource-parser v3.0.6

## Quick Start

**Prerequisites**: Node.js 18.17+ and backend server running on port 8000

```bash
# Install dependencies
npm install

# Configure environment
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_BASE_PATH=/api
EOF

# Start development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

**📚 Detailed Setup**: See [QUICKSTART.md](./docs/QUICKSTART.md) for comprehensive installation and configuration guide.

## Features

### Real-Time Streaming
- Server-Sent Events (SSE) connection for live updates
- Automatic reconnection with exponential backoff
- Visual indicators for connection status
- Message streaming with typing indicators

### Chat Interface
- Create and manage multiple conversations
- Send messages with markdown support
- View agent reasoning and tool calls in real-time
- Search conversations by name
- Delete conversations with confirmation

### Agent Capabilities
- **Query Optimization**: Analyze and optimize SQL queries
- **Job Optimization**: Databricks job performance analysis
- **Pipeline Optimization**: Data pipeline lineage and recommendations
- Real-time tool execution visualization
- Interruptible reasoning with user-in-the-loop support

### UI/UX
- Responsive design (desktop and mobile)
- Dark and light theme toggle
- Persistent theme preferences
- Smooth animations and transitions
- Accessible components (ARIA labels)

## Project Structure

```
frontend/
├── app/                      # Next.js App Router
│   ├── layout.tsx            # Root layout with providers
│   ├── page.tsx              # Home page (chat interface)
│   ├── config/               # Configuration page
│   └── globals.css           # Global styles
├── components/
│   ├── chat/                 # Chat UI components
│   │   ├── ChatContainer.tsx
│   │   ├── MessageList.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── MessageInput.tsx
│   │   ├── ToolCallCard.tsx
│   │   └── ReportBubble.tsx
│   ├── conversations/        # Sidebar components
│   │   ├── ConversationSidebar.tsx
│   │   ├── ConversationList.tsx
│   │   └── ConversationItem.tsx
│   ├── config/               # Configuration components
│   │   └── DomainModelSelector.tsx
│   └── common/               # Shared components
│       ├── ErrorBoundary.tsx
│       ├── LoadingSkeleton.tsx
│       └── NotificationSnackbar.tsx
├── lib/
│   ├── api/                  # API client and React Query setup
│   │   ├── client.ts         # Axios API client
│   │   └── QueryProvider.tsx
│   ├── hooks/                # Custom React hooks
│   │   ├── useSSE.ts         # SSE connection management
│   │   └── useSlashCommands.ts
│   ├── sse/                  # SSE client implementation
│   │   └── EventSourceClient.ts
│   ├── store/                # Zustand stores
│   │   ├── conversationStore.ts
│   │   ├── messageStore.ts
│   │   ├── configStore.ts
│   │   └── uiStore.ts
│   ├── theme/                # MUI theme configuration
│   │   ├── theme.ts
│   │   └── ThemeProvider.tsx
│   └── types/                # TypeScript definitions
│       └── api.ts            # API types matching backend
├── public/                   # Static assets (images, icons)
├── docs/
│   ├── DEBUG_LOGGING.md      # Debug logging configuration
│   ├── ENV_SETUP.md          # Environment configuration guide
│   ├── QUICKSTART.md         # Detailed setup guide
│   └── TROUBLESHOOTING.md    # Common issues and solutions
```

## Development

### Running the Development Server

```bash
npm run dev
```

Server runs at http://localhost:3000 with hot module replacement.

### Building for Production

```bash
# Create optimized production build
npm run build

# Test production build locally
npm start
```

### Code Quality

```bash
# Lint code
npm run lint

# Auto-fix linting issues
npm run lint -- --fix

# Type checking is automatic with TypeScript
```

## Configuration

### Environment Variables

Create `.env.local` in the frontend directory:

```bash
# Backend API URL (required)
NEXT_PUBLIC_API_URL=http://localhost:8000

# API base path (required)
NEXT_PUBLIC_API_BASE_PATH=/api
```

**Note**: Variables must be prefixed with `NEXT_PUBLIC_` to be available in the browser.

### API Integration

The frontend connects to the Starboard backend API:
- **REST API**: CRUD operations for conversations and messages
- **SSE Streaming**: Real-time agent events and updates
- **Authentication**: API key passthrough (for Databricks deployment)

See [API_REFERENCE.md](../docs/API_REFERENCE.md) for backend API documentation.

## Testing

```bash
# Run tests (when available)
npm test

# Run tests in watch mode
npm test -- --watch
```

## Deployment

### Databricks Apps

Deploy alongside the backend as a Databricks App. See [DEPLOYMENT.md](../docs/DEPLOYMENT.md) for instructions.

### Docker

```bash
# Build Docker image
docker build -t starboard-frontend .

# Run container
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_URL=http://backend:8000 \
  -e NEXT_PUBLIC_API_BASE_PATH=/api \
  starboard-frontend
```

### Static Export

For static hosting (limited SSE support):

```bash
npm run build
# Output in .next/ directory
```

## Documentation

- **[Quickstart Guide](./docs/QUICKSTART.md)** - Complete setup instructions
- **[Troubleshooting](./docs/TROUBLESHOOTING.md)** - Common issues and solutions
- **[Environment Setup](./docs/ENV_SETUP.md)** - Configuration details
- **[Debug Logging](./docs/DEBUG_LOGGING.md)** - Console logging configuration
- **[Backend API Reference](../docs/API_REFERENCE.md)** - API documentation
- **[Main Project README](../README.md)** - Overall project information

## Architecture

### State Management

The app uses Zustand for state management with these stores:

- **conversationStore**: Conversation list and active conversation
- **messageStore**: Messages grouped by conversation
- **configStore**: Domain model and optimization settings
- **uiStore**: UI state (theme, sidebar, notifications)

All stores persist to `localStorage` for state restoration.

### Real-Time Communication

SSE (Server-Sent Events) implementation:
1. Client establishes connection to `/api/chat/conversations/{id}/stream`
2. Backend streams events as they occur
3. Frontend updates UI optimistically and confirms with events
4. Automatic reconnection on connection loss

Event types:
- `agent_start`: Agent begins processing
- `agent_thinking`: Agent reasoning step
- `tool_call_start`: Tool execution begins
- `tool_call_result`: Tool execution result
- `agent_response`: Final agent message
- `agent_error`: Error occurred

### API Client

Axios-based client with:
- Base URL from environment variables
- Automatic JSON serialization
- Error handling and retry logic
- TypeScript types for all endpoints

## Contributing

When contributing to the frontend:

1. Follow TypeScript best practices
2. Use Material-UI components consistently
3. Maintain responsive design
4. Add proper error handling
5. Update types in `lib/types/api.ts` when backend changes
6. Test SSE connections thoroughly
7. Ensure accessibility (ARIA labels)

## Troubleshooting

Common issues:

**Can't connect to backend**:
- Verify backend is running: `curl http://localhost:8000/health/ready`
- Check `.env.local` file exists and has correct URL
- Restart dev server after changing environment variables

**SSE not working**:
- Check browser Network tab for EventSource connection
- Verify conversation ID is valid
- Check backend CORS settings allow `http://localhost:3000`

**Module not found errors**:
```bash
rm -rf node_modules package-lock.json .next
npm install
```

See [TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) for comprehensive debugging guide.

## Learn More

This project uses Next.js. To learn more:

- [Next.js Documentation](https://nextjs.org/docs) - Next.js features and API
- [Material-UI Documentation](https://mui.com/material-ui/) - Component library
- [Zustand Documentation](https://github.com/pmndrs/zustand) - State management
- [TanStack Query Documentation](https://tanstack.com/query) - Server state

## License

MIT
