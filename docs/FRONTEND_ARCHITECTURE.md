# Frontend Architecture

**Project**: Starboard AI Agent Web UI  
**Framework**: Next.js 16 + React 19 + TypeScript  
**UI Library**: Material UI v7  
**Status**: Production Ready

---

## Executive Summary

The Starboard frontend is a modern Next.js application that provides a real-time chat interface for interacting with AI agents. It follows best practices for type safety, component composition, and scalable architecture.

### Key Features

✅ **Server-Sent Events (SSE)** - Real-time streaming responses  
✅ **Type-Safe API** - Auto-generated TypeScript types from backend  
✅ **Component-Based UI** - Reusable, testable components  
✅ **Domain-Specific Rendering** - Specialized UIs per agent domain  
✅ **Material UI v7** - Modern, accessible components  
✅ **Dark/Light Mode** - User preference support

---

## Architecture Overview

### Technology Stack

```
┌─────────────────────────────────────────┐
│  Next.js 16 (App Router)               │
│  ├── React 19                          │
│  ├── TypeScript 5.x                    │
│  ├── Material UI v7                    │
│  ├── Tailwind CSS v4                   │
│  └── Zod v4                            │
└────────────┬────────────────────────────┘
             │ HTTP/SSE
┌────────────▼────────────────────────────┐
│  Backend API (FastAPI)                  │
│  ├── REST endpoints                     │
│  ├── SSE streaming                      │
│  └── Type generation                    │
└─────────────────────────────────────────┘
```

### Directory Structure

```
frontend/
├── app/                          # Next.js app directory
│   ├── page.tsx                  # Home page (chat UI)
│   ├── layout.tsx                # Root layout
│   ├── globals.css               # Global styles
│   ├── config/                   # Configuration UI
│   └── demo/                     # Demo pages
│
├── components/                   # React components
│   ├── chat/                     # Chat-related components
│   │   ├── ChatInterface.tsx     # Main chat container
│   │   ├── MessageBubble.tsx     # Individual message display
│   │   ├── ReportBubble.tsx      # Report rendering router
│   │   ├── InputBar.tsx          # Message input
│   │   ├── reports/              # Domain-specific reports
│   │   │   ├── AnalyticsReportBubble.tsx
│   │   │   └── AdvisorReportBubble.tsx
│   │   ├── analytics/            # FinOps components
│   │   │   ├── AnalyticsCostSummary.tsx
│   │   │   └── AnalyticsFindingsCard.tsx
│   │   └── visualization/        # Chart components
│   │       ├── VisualizationPanel.tsx
│   │       ├── ChartView.tsx
│   │       └── DataTableView.tsx
│   │
│   ├── layout/                   # Layout components
│   │   ├── Header.tsx
│   │   ├── Footer.tsx
│   │   └── Sidebar.tsx
│   │
│   └── ui/                       # Reusable UI components
│       ├── Button.tsx
│       ├── Card.tsx
│       └── LoadingSpinner.tsx
│
├── lib/                          # Utilities and hooks
│   ├── api/                      # API client
│   │   ├── client.ts             # HTTP client
│   │   └── streaming.ts          # SSE handling
│   ├── types/                    # TypeScript types
│   │   ├── api.ts                # Type exports
│   │   ├── generated-api.ts      # Auto-generated types
│   │   ├── extended-api.ts       # Frontend extensions
│   │   ├── reports.ts            # Report type guards
│   │   └── chart.ts              # Visualization types
│   ├── hooks/                    # React hooks
│   │   ├── useConversation.ts    # Conversation management
│   │   ├── useStreaming.ts       # SSE streaming
│   │   └── useMessages.ts        # Message state
│   └── utils/                    # Helper functions
│       ├── formatting.ts
│       └── validation.ts
│
├── public/                       # Static assets
│   ├── images/
│   └── icons/
│
└── docs/                         # Frontend documentation
    ├── QUICKSTART.md
    ├── TROUBLESHOOTING.md
    └── DEBUG_LOGGING.md
```

---

## Type System Architecture

### Type Generation

The frontend uses **auto-generated TypeScript types** from the backend OpenAPI schema, ensuring type safety across the stack.

#### Generated Types (Don't Edit!)

```typescript
// lib/types/generated-api.ts (auto-generated)
export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  complete_report?: Record<string, any>;
  metadata?: Record<string, any>;
}

export interface Conversation {
  id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
  config?: ConversationConfig;
}

export interface AgentReport {
  report_type: string;
  title: string;
  summary: string;
  [key: string]: any;
}
```

#### Frontend Extensions (Safe to Edit)

```typescript
// lib/types/extended-api.ts
import type { Message as GeneratedMessage } from './generated-api';

export interface Message extends GeneratedMessage {
  // Frontend-only fields
  debug?: boolean;
  retry_count?: number;
  visualization?: {
    data_reference: string;
    chart_config: ChartConfig | null;
    has_visualization: boolean;
  };
}
```

### Type Guards for Reports

Use discriminated unions and type guards for type-safe report handling:

```typescript
// lib/types/reports.ts
import type { AnalyticsReport, AdvisorReport, AgentReport } from './generated-api';

/**
 * Discriminated union of all report types.
 */
export type CompleteReport =
  | AnalyticsReport
  | AdvisorReport
  | AgentReport
  | null;

/**
 * Type guard to check if report is analytics type.
 */
export function isAnalyticsReport(report: unknown): report is AnalyticsReport {
  return (
    typeof report === 'object' &&
    report !== null &&
    'report_type' in report &&
    report.report_type === 'analytics'
  );
}

/**
 * Type guard to check if report is advisor type.
 */
export function isAdvisorReport(report: unknown): report is AdvisorReport {
  return (
    typeof report === 'object' &&
    report !== null &&
    'report_type' in report &&
    report.report_type === 'advisor'
  );
}
```

### Using Type Guards

```typescript
// components/chat/ReportBubble.tsx
import { isAnalyticsReport, isAdvisorReport } from '@/lib/types/reports';

export function ReportBubble({ message }: ReportBubbleProps) {
  const report = message.complete_report;
  
  // TypeScript now knows the exact type! ✅
  if (isAnalyticsReport(report)) {
    return <AnalyticsReportBubble report={report} />;
  }
  
  if (isAdvisorReport(report)) {
    return <AdvisorReportBubble report={report} />;
  }
  
  // Fallback for unknown types
  return <MarkdownReportBubble message={message} />;
}
```

---

## Component Architecture

### Component Patterns

#### 1. Container/Presentational Pattern

**Container** (smart component):
```typescript
// components/chat/ChatInterface.tsx
export function ChatInterface() {
  // State management
  const [messages, setMessages] = useState<Message[]>([]);
  const { sendMessage, isStreaming } = useConversation();
  
  // Business logic
  const handleSend = async (text: string) => {
    await sendMessage(text);
  };
  
  // Render presentational components
  return (
    <Box>
      <MessageList messages={messages} />
      <InputBar onSend={handleSend} disabled={isStreaming} />
    </Box>
  );
}
```

**Presentational** (dumb component):
```typescript
// components/chat/MessageBubble.tsx
interface MessageBubbleProps {
  message: Message;
  onSelectOption?: (option: NextStepOption) => void;
}

export function MessageBubble({ message, onSelectOption }: MessageBubbleProps) {
  // Pure rendering logic, no state
  return (
    <Paper>
      <Typography>{message.content}</Typography>
      {message.next_steps && (
        <NextStepButtons options={message.next_steps} onSelect={onSelectOption} />
      )}
    </Paper>
  );
}
```

#### 2. Component Composition

Build complex UIs from simple, reusable components:

```typescript
// Atomic components
<Button />
<Card />
<Typography />

// Composed components
<MessageBubble>
  <Card>
    <Typography />
    <NextStepButtons />
  </Card>
</MessageBubble>

// Page-level composition
<ChatInterface>
  <MessageList>
    <MessageBubble />
  </MessageList>
  <InputBar />
</ChatInterface>
```

#### 3. Domain-Specific Components

Separate components by agent domain for scalability:

```
components/chat/
├── reports/                    # Report type routers
│   ├── AnalyticsReportBubble.tsx
│   └── AdvisorReportBubble.tsx
│
├── analytics/                  # FinOps domain
│   ├── AnalyticsCostSummary.tsx
│   ├── AnalyticsFindingsCard.tsx
│   └── RecommendationsList.tsx
│
├── diagnostic/                 # Diagnostic domain
│   ├── DiagnosticTimeline.tsx
│   └── ErrorStackTrace.tsx
│
└── query/                      # Query optimization domain
    ├── QueryPlanView.tsx
    └── OptimizationSuggestions.tsx
```

---

## Scaling for Multiple Domains

### Current Pattern: Extension-Based

The current architecture uses **message extension** pattern:

```typescript
// lib/types/extended-api.ts
export interface Message extends GeneratedMessage {
  debug?: boolean;
  retry_count?: number;
  
  // Domain-specific fields (optional)
  visualization?: VisualizationMetadata;
  diagnostic_context?: DiagnosticContext;
  query_plan?: QueryPlanData;
}
```

**Pros**:
- ✅ Simple and flat structure
- ✅ Easy to access: `message.visualization`
- ✅ No nesting complexity
- ✅ Backward compatible

**Cons**:
- ⚠️ Potential naming conflicts
- ⚠️ Harder to see which fields belong to which domain

**Recommendation**: Continue with this pattern until you have 5+ domains with many fields each.

### Report Routing Pattern

Use polymorphic rendering based on `report_type`:

```typescript
// components/chat/ReportBubble.tsx
export function ReportBubble({ message }: ReportBubbleProps) {
  const report = message.complete_report;
  
  if (!report || !report.report_type) {
    return null;
  }
  
  // Route to domain-specific component
  switch (report.report_type) {
    case "analytics":
      return <AnalyticsReportBubble report={report} />;
    case "advisor":
      return <AdvisorReportBubble report={report} />;
    case "diagnostic":
      return <DiagnosticReportBubble report={report} />;
    default:
      return <MarkdownReportBubble message={message} />;
  }
}
```

### Future Enhancement: Component Registry

For 3+ report types, consider a registry pattern:

```typescript
// lib/components/report-registry.ts
type ReportComponent = React.ComponentType<ReportProps>;

export const REPORT_COMPONENTS: Record<string, ReportComponent> = {
  analytics: AnalyticsReportBubble,
  advisor: AdvisorReportBubble,
  diagnostic: DiagnosticReportBubble,
  // Add new domains here
};

export function getReportComponent(reportType: string): ReportComponent {
  return REPORT_COMPONENTS[reportType] || MarkdownReportBubble;
}

// Usage in ReportBubble
const ReportComponent = getReportComponent(report.report_type);
return <ReportComponent report={report} />;
```

**Benefits**:
- ✅ No switch statements
- ✅ Easy to add new domains
- ✅ Plugin-like architecture
- ✅ Single responsibility

---

## State Management

### Conversation State

```typescript
// lib/hooks/useConversation.ts
export function useConversation(conversationId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [config, setConfig] = useState<ConversationConfig>();
  
  const sendMessage = async (content: string) => {
    setIsStreaming(true);
    try {
      const response = await api.sendMessage(conversationId, content);
      setMessages(prev => [...prev, response]);
    } finally {
      setIsStreaming(false);
    }
  };
  
  return { messages, isStreaming, config, sendMessage };
}
```

### SSE Streaming State

```typescript
// lib/hooks/useStreaming.ts
export function useStreaming(conversationId: string) {
  const [events, setEvents] = useState<StreamingEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  
  useEffect(() => {
    const eventSource = new EventSource(`/api/chat/stream/${conversationId}`);
    
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setEvents(prev => [...prev, data]);
    };
    
    eventSource.onopen = () => setIsConnected(true);
    eventSource.onerror = () => setIsConnected(false);
    
    return () => eventSource.close();
  }, [conversationId]);
  
  return { events, isConnected };
}
```

---

## API Integration

### HTTP Client

```typescript
// lib/api/client.ts
export class ApiClient {
  private baseUrl: string;
  
  constructor(baseUrl: string = process.env.NEXT_PUBLIC_API_URL!) {
    this.baseUrl = baseUrl;
  }
  
  async createConversation(
    userId: string,
    config?: ConversationConfig
  ): Promise<Conversation> {
    const response = await fetch(`${this.baseUrl}/api/chat/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, config }),
    });
    
    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }
    
    return response.json();
  }
  
  async sendMessage(
    conversationId: string,
    content: string
  ): Promise<Message> {
    const response = await fetch(
      `${this.baseUrl}/api/chat/conversations/${conversationId}/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      }
    );
    
    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }
    
    return response.json();
  }
}

export const api = new ApiClient();
```

### SSE Streaming

```typescript
// lib/api/streaming.ts
export class StreamingClient {
  private baseUrl: string;
  
  constructor(baseUrl: string = process.env.NEXT_PUBLIC_API_URL!) {
    this.baseUrl = baseUrl;
  }
  
  connect(
    conversationId: string,
    onEvent: (event: StreamingEvent) => void,
    onError?: (error: Error) => void
  ): () => void {
    const eventSource = new EventSource(
      `${this.baseUrl}/api/chat/stream/${conversationId}`
    );
    
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onEvent(data);
      } catch (error) {
        onError?.(error as Error);
      }
    };
    
    eventSource.onerror = (error) => {
      onError?.(new Error('SSE connection error'));
    };
    
    // Return cleanup function
    return () => eventSource.close();
  }
}

export const streaming = new StreamingClient();
```

---

## Best Practices

### Type Safety

✅ **DO**: Use type guards for runtime type checking
```typescript
if (isAnalyticsReport(report)) {
  // TypeScript knows report is AnalyticsReport
  return <AnalyticsReportBubble report={report} />;
}
```

❌ **DON'T**: Use `as any` or type assertions
```typescript
// BAD
const report = message.complete_report as any;
```

### Component Design

✅ **DO**: Keep components small and focused
```typescript
// Good: Single responsibility
function MessageContent({ content }: { content: string }) {
  return <Typography>{content}</Typography>;
}
```

❌ **DON'T**: Create monolithic components
```typescript
// Bad: Too many responsibilities
function MessageBubbleWithEverything() {
  // 500 lines of code...
}
```

### State Management

✅ **DO**: Use custom hooks for complex state
```typescript
function useConversation() {
  // Encapsulate conversation logic
  return { messages, sendMessage, isStreaming };
}
```

❌ **DON'T**: Put all state in page components
```typescript
// Bad: Page component with 50 useState calls
```

### Error Handling

✅ **DO**: Handle errors gracefully
```typescript
try {
  await api.sendMessage(conversationId, content);
} catch (error) {
  showErrorToast(error.message);
}
```

❌ **DON'T**: Ignore errors
```typescript
// Bad: Silent failure
await api.sendMessage(conversationId, content);
```

---

## Testing Strategy

### Component Tests

```typescript
// components/chat/__tests__/MessageBubble.test.tsx
import { render, screen } from '@testing-library/react';
import { MessageBubble } from '../MessageBubble';

describe('MessageBubble', () => {
  it('renders message content', () => {
    const message = {
      id: '1',
      content: 'Hello, world!',
      role: 'user',
    };
    
    render(<MessageBubble message={message} />);
    
    expect(screen.getByText('Hello, world!')).toBeInTheDocument();
  });
  
  it('calls onSelectOption when option clicked', () => {
    const onSelectOption = jest.fn();
    const message = {
      id: '1',
      content: 'Choose:',
      next_steps: [{ label: 'Option 1', value: '1' }],
    };
    
    render(<MessageBubble message={message} onSelectOption={onSelectOption} />);
    
    fireEvent.click(screen.getByText('Option 1'));
    
    expect(onSelectOption).toHaveBeenCalledWith({ label: 'Option 1', value: '1' });
  });
});
```

### Hook Tests

```typescript
// lib/hooks/__tests__/useConversation.test.ts
import { renderHook, act } from '@testing-library/react';
import { useConversation } from '../useConversation';

describe('useConversation', () => {
  it('sends message and updates state', async () => {
    const { result } = renderHook(() => useConversation('conv_123'));
    
    await act(async () => {
      await result.current.sendMessage('Hello');
    });
    
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.isStreaming).toBe(false);
  });
});
```

---

## Performance Optimization

### Code Splitting

```typescript
// Lazy load heavy components
const ChartView = lazy(() => import('./visualization/ChartView'));

function VisualizationPanel({ data }: Props) {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <ChartView data={data} />
    </Suspense>
  );
}
```

### Memoization

```typescript
// Memoize expensive computations
const processedData = useMemo(() => {
  return expensiveTransform(rawData);
}, [rawData]);

// Memoize callbacks
const handleClick = useCallback(() => {
  doSomething(value);
}, [value]);
```

### Virtual Scrolling

For long message lists:
```typescript
import { FixedSizeList } from 'react-window';

function MessageList({ messages }: Props) {
  return (
    <FixedSizeList
      height={600}
      itemCount={messages.length}
      itemSize={100}
      width="100%"
    >
      {({ index, style }) => (
        <div style={style}>
          <MessageBubble message={messages[index]} />
        </div>
      )}
    </FixedSizeList>
  );
}
```

---

## Accessibility

### Semantic HTML

```typescript
// Use semantic elements
<header>
  <nav>
    <h1>Starboard AI Agent</h1>
  </nav>
</header>

<main>
  <article>
    <MessageBubble />
  </article>
</main>
```

### ARIA Labels

```typescript
<button
  aria-label="Send message"
  aria-disabled={isStreaming}
  onClick={handleSend}
>
  <SendIcon />
</button>
```

### Keyboard Navigation

```typescript
function InputBar({ onSend }: Props) {
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend(inputValue);
    }
  };
  
  return <input onKeyDown={handleKeyDown} />;
}
```

---

## Conclusion

The Starboard frontend follows modern React best practices with a focus on:

✅ **Type Safety** - Auto-generated types from backend  
✅ **Component Composition** - Small, reusable components  
✅ **Scalability** - Easy to add new domains and features  
✅ **Performance** - Code splitting, memoization, virtual scrolling  
✅ **Accessibility** - Semantic HTML, ARIA labels, keyboard navigation

### Key Takeaways

1. **Extend generated types, don't modify them**
2. **Use type guards for polymorphic components**
3. **Keep components small and focused**
4. **Use custom hooks for complex state**
5. **Handle errors gracefully**
6. **Test components and hooks**
7. **Optimize performance where needed**
8. **Ensure accessibility**

---

**Document Created**: November 27, 2025  
**Last Updated**: December 9, 2025  
**Maintained By**: Engineering Team

