# FinOps Visualization Components

Interactive data visualization components for the FinOps Analytics Agent with server-side rendered charts.

## Components

### VisualizationPanel

Container component with interactive chart/table toggle.

```tsx
<VisualizationPanel
  dataReference="data_ref_abc123"
  chartConfig={chartConfig}
/>
```

**Props:**
- `dataReference` (string): Cache key for query results
- `chartConfig` (ChartConfig | null): Chart configuration from LLM, or null for table-only

**Features:**
- Toggle between chart and table views
- Defaults to chart view if available
- Hides toggle buttons if no chart available

### ChartView

Displays server-rendered chart images (PNG).

```tsx
<ChartView
  dataReference="data_ref_abc123"
  chartConfig={chartConfig}
/>
```

**Props:**
- `dataReference` (string): Cache key for query results
- `chartConfig` (ChartConfig): Chart configuration

**Features:**
- Fetches PNG from `/api/chart/render`
- Loading state with spinner
- Error handling with retry
- Download button for PNG export
- Cleans up object URLs on unmount

### DataTableView

Displays raw query results in a table.

```tsx
<DataTableView dataReference="data_ref_abc123" />
```

**Props:**
- `dataReference` (string): Cache key for query results

**Features:**
- Fetches data from `/api/data/{dataReference}`
- Loading state with spinner
- Error handling with retry
- CSV export with proper formatting
- Handles null values (displays "—")
- Responsive with horizontal scroll

## Architecture

### Server-Side Rendering
- All charts rendered on backend using Vega-Lite
- Frontend receives PNG images
- Zero client-side charting libraries
- ~500KB bundle size savings

### Data Flow
```
Backend Query → Cache Results → Generate Chart Config
                                         ↓
Frontend: VisualizationPanel → ChartView (PNG) or DataTableView (Table)
```

### API Endpoints
- `POST /api/chart/render?data_ref={ref}` - Render chart as PNG
- `GET /api/data/{dataReference}` - Fetch cached data

## Testing

### Unit Tests

Run tests:
```bash
npm test -- components/chat/visualization
```

Test coverage:
- ✅ ChartView: Loading, success, error, retry, download
- ✅ DataTableView: Loading, success, error, empty, CSV export
- ✅ VisualizationPanel: Toggle, defaults, button states

### Demo Mode

Test without backend at: **http://localhost:3000/demo/visualization**

```bash
npm run dev
# Navigate to http://localhost:3000/demo/visualization
```

**Features:**
- Mock data generator
- Mock API implementation
- Interactive chart type selector
- All components fully functional

**Try:**
- Toggle between chart and table views
- Download mock charts (SVG)
- Export CSV with mock data
- Switch chart types (bar, line, scatter, table-only)

## Usage Example

### In AnalyticsReportBubble

```tsx
import { VisualizationPanel } from '@/components/chat/visualization';

// Inside component:
{message.visualization?.has_visualization && (
  <VisualizationPanel
    dataReference={message.visualization.data_reference}
    chartConfig={message.visualization.chart_config}
  />
)}
```

### Message Structure

```typescript
const message: Message = {
  // ... standard fields ...
  visualization: {
    data_reference: "data_ref_abc123",
    chart_config: {
      chart_type: "bar",
      title: "Top 10 Most Expensive Jobs",
      data: { data_ref: "data_ref_abc123" },
      encodings: {
        x: { field: "job_name", type: "nominal" },
        y: { field: "total_cost", type: "quantitative" }
      },
      options: { width: 800, height: 400 }
    },
    has_visualization: true
  }
};
```

## Types

See `/lib/types/chart.ts` for complete type definitions:
- `ChartType`: "bar" | "line" | "area" | "scatter" | "histogram" | "table"
- `ChartConfig`: Complete chart configuration
- `VisualizationMetadata`: Message extension for visualization

## Error Handling

### Network Errors
- Shows error message with retry button
- Clears error on successful retry

### Data Expiration
- 10-minute cache TTL (configurable)
- Clear error message: "Data not found. Please re-run your query."

### Invalid Config
- Validates chart config structure
- Fallback to error state with details

## Accessibility

### Keyboard Navigation
- ✅ Tab through toggle buttons
- ✅ Enter/Space to activate
- ✅ Focus indicators visible

### Screen Readers
- ✅ Chart images have descriptive alt text
- ✅ Toggle buttons have aria-labels
- ✅ Loading states announced
- ✅ View changes announced

### Visual
- ✅ Color contrast meets WCAG 2.1 AA
- ✅ No information by color alone
- ✅ Text summaries always provided

## Performance

### Targets
- Chart render: <2s (p95: <5s)
- Table render: <500ms
- Toggle transition: <200ms

### Optimizations
- Object URL cleanup prevents memory leaks
- Lazy loading of table data (only when switched to table view)
- Backend caching (5-minute HTTP cache)

## Development

### Adding New Chart Types

1. Update `ChartType` in `/lib/types/chart.ts`
2. Backend handles rendering
3. Frontend automatically supports it
4. Add demo case in `/app/demo/visualization/page.tsx`
5. Add test case in `__tests__/`

### Debugging

Enable debug mode:
```tsx
// In browser console
localStorage.setItem('debug_visualization', 'true');
```

This will log:
- API calls and responses
- Chart config validations
- Data transformations

## Troubleshooting

### Chart not displaying
1. Check `message.visualization?.has_visualization` is true
2. Verify `data_reference` is valid and not expired
3. Check browser console for errors
4. Test with demo mode

### Table not loading
1. Verify API endpoint `/api/data/{ref}` is accessible
2. Check data hasn't expired (10-min TTL)
3. Inspect network tab for 404/500 errors

### Toggle buttons hidden
- Expected if `chartConfig` is null or `chart_type === "table"`
- Means only table view is available

## Browser Support

- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Edge 90+

## License

See project LICENSE file.

