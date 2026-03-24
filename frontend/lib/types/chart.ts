/**
 * Chart configuration types for FinOps Analytics Agent.
 * 
 * Based on backend ChartConfig schema from:
 * packages/starboard-server/starboard_server/tools/schemas/visualization_schemas.py
 * 
 * These types define the structure for LLM-driven chart generation,
 * where charts are rendered server-side using Vega-Lite and returned as PNG images.
 * 
 * @module chart
 */

/**
 * Allowed chart types (constrained set to prevent LLM hallucinations).
 * 
 * Each type has a specific use case:
 * - bar: Categorical comparisons, rankings, top N
 * - line: Time series trends, temporal patterns
 * - area: Time series with magnitude emphasis
 * - scatter: Correlations, relationships between 2 numeric variables
 * - histogram: Distribution of single numeric variable
 * - table: Fallback when visualization adds no value
 */
export type ChartType = "bar" | "line" | "area" | "scatter" | "histogram" | "table";

/**
 * Data type for encoding channels (Vega-Lite standard types).
 * 
 * - quantitative: Numeric continuous data
 * - nominal: Categorical data without order
 * - ordinal: Categorical data with order
 * - temporal: Date/time data
 */
export type EncodingType = "quantitative" | "nominal" | "ordinal" | "temporal";

/**
 * Encoding channel configuration (x, y, color, size, etc.).
 * 
 * Defines how a data field is mapped to a visual property.
 * Based on Vega-Lite encoding specification.
 * 
 * **IMPORTANT**: Must match backend Encoding model in visualization_models.py
 * 
 * @example
 * ```typescript
 * const xEncoding: Encoding = {
 *   field: "job_name",
 *   type: "nominal",
 *   title: "Job Name"
 * };
 * 
 * const yEncoding: Encoding = {
 *   field: "total_cost",
 *   type: "quantitative",
 *   title: "Total Cost",
 *   aggregate: "sum"
 * };
 * ```
 */
export interface Encoding {
  /** 
   * Column name from dataset.
   * Must match a column in the cached data.
   */
  field: string;
  
  /** 
   * Data type for encoding.
   * Determines how Vega-Lite interprets and renders the field.
   */
  type: EncodingType;
  
  /** 
   * Human-readable label for axis/legend (optional).
   */
  title?: string | null;
  
  /** 
   * Sort order (optional).
   * Common values: "ascending", "descending", or field name to sort by
   */
  sort?: string | null;
  
  /**
   * Aggregation function (optional).
   * When specified, Vega-Lite will aggregate data by the grouping dimension.
   * Common values: "sum", "mean", "count", "min", "max", "median"
   */
  aggregate?: string | null;
}

/**
 * Chart rendering options.
 * 
 * Generic options dictionary for chart-specific configuration.
 * Backend accepts dict[str, Any] for flexibility.
 * 
 * **IMPORTANT**: Must match backend ChartConfig.options type (dict[str, Any])
 * 
 * @example
 * ```typescript
 * const options: ChartOptions = {
 *   interpolate: "monotone",
 *   point: true
 * };
 * ```
 */
export type ChartOptions = Record<string, unknown>;

/**
 * Complete chart configuration (subset of Vega-Lite).
 * 
 * This is the primary interface sent from backend to frontend,
 * containing all information needed to render a chart.
 * 
 * **IMPORTANT**: Must EXACTLY match backend ChartConfig model in visualization_models.py
 * The backend uses Pydantic with extra="forbid", so any extra fields will cause errors!
 * 
 * The backend LLM generates this configuration based on data analysis,
 * and the backend ChartRenderer converts it to Vega-Lite spec and renders to PNG.
 * 
 * @example
 * ```typescript
 * const chartConfig: ChartConfig = {
 *   chart_type: "bar",
 *   title: "Top 10 Most Expensive Jobs",
 *   description: "DBU cost breakdown by job",
 *   encodings: {
 *     x: { field: "job_name", type: "nominal", title: "Job Name" },
 *     y: { field: "total_cost", type: "quantitative", title: "Total Cost" }
 *   },
 *   options: { interpolate: "monotone" }
 * };
 * ```
 */
export interface ChartConfig {
  /** 
   * Chart type.
   * Determines the visual representation (bar, line, etc.)
   */
  chart_type: ChartType;
  
  /** 
   * Chart title.
   * Displayed at the top of the chart and used for alt text.
   */
  title: string;
  
  /** 
   * Chart description (optional).
   * Provides context about what the chart shows.
   */
  description?: string | null;
  
  /** 
   * Encoding channels (x, y, color, size, etc.).
   * Maps data fields to visual properties.
   * Common channels: x, y, color, size, opacity, shape
   */
  encodings: Record<string, Encoding>;
  
  /** 
   * Chart-specific options (optional).
   * Flexible options dict for rendering customization.
   */
  options?: ChartOptions | null;
}

/**
 * Chart recommendation from LLM.
 * 
 * The LLM analyzes the data profile and recommends an appropriate chart type
 * with reasoning for the choice.
 * 
 * @example
 * ```typescript
 * const recommendation: ChartRecommendation = {
 *   chart_type: "bar",
 *   reasoning: "Bar chart is ideal for comparing costs across jobs (categorical comparison)"
 * };
 * ```
 */
export interface ChartRecommendation {
  /** 
   * Recommended chart type.
   */
  chart_type: ChartType;
  
  /** 
   * 1-2 sentence explanation for chart choice.
   * Helps users understand why this visualization was selected.
   */
  reasoning: string;
}

/**
 * Complete visualization output from backend.
 * 
 * This is the full response from the backend VisualizationService,
 * including the natural language summary, chart recommendation, and chart config.
 * 
 * @example
 * ```typescript
 * const vizOutput: VisualizationOutput = {
 *   summary: "The top 10 most expensive jobs consumed $1,234.56 in DBUs this month.",
 *   chart_recommendation: {
 *     chart_type: "bar",
 *     reasoning: "Bar chart is ideal for comparing categorical data"
 *   },
 *   chart_config: {
 *     chart_type: "bar",
 *     title: "Top 10 Most Expensive Jobs",
 *     data: { data_ref: "data_ref_abc123" },
 *     encodings: { ... }
 *   }
 * };
 * ```
 */
export interface VisualizationOutput {
  /** 
   * Natural language summary of insights (2-3 sentences).
   * Always provided, even if chart generation fails.
   * This ensures progressive enhancement - text summaries are always available.
   */
  summary: string;
  
  /** 
   * Chart type recommendation.
   * Includes reasoning for the LLM's choice.
   */
  chart_recommendation: ChartRecommendation;
  
  /** 
   * Chart configuration (null if chart_type is 'table').
   * If the LLM determines a chart adds no value, this will be null.
   */
  chart_config: ChartConfig | null;
}

/**
 * Cached data response from backend.
 * 
 * Response from GET /api/data/{data_reference} endpoint.
 * Contains the raw query results for display in table view.
 * 
 * Format matches polars_df_to_dict output from backend utils.
 * 
 * @example
 * ```typescript
 * const data: CachedDataResponse = {
 *   version: 1,
 *   orientation: "records",
 *   schema: {
 *     job_id: { dtype: "Utf8", encoding: "native" },
 *     total_cost: { dtype: "Float64", encoding: "float_finite_only" }
 *   },
 *   data: [
 *     { job_id: "123", job_name: "ETL Pipeline", total_cost: 456.78 },
 *     { job_id: "456", job_name: "Data Warehouse", total_cost: 234.56 }
 *   ],
 *   row_count: 2
 * };
 * ```
 */
export interface CachedDataResponse {
  /** 
   * Schema version for compatibility.
   * @default 1
   */
  version: number;
  
  /** 
   * Data orientation format.
   * - "records": Array of row objects (list of dicts)
   * - "columns": Object with column arrays (dict of lists)
   */
  orientation: "records" | "columns";
  
  /** 
   * Schema metadata for each column.
   * Maps column name to metadata including dtype, encoding, format info.
   */
  schema: Record<string, unknown>;
  
  /** 
   * Raw data in the specified orientation.
   * For "records": Array<Record<string, unknown>>
   * For "columns": Record<string, Array<unknown>>
   */
  data: Array<Record<string, unknown>> | Record<string, Array<unknown>>;
  
  /** 
   * Total row count.
   * May differ from data.length if pagination is applied (future enhancement).
   */
  row_count: number;
}

/**
 * Visualization metadata for Message extension.
 * 
 * This field is added to the Message type to support FinOps visualization.
 * It contains all information needed to render charts and tables in the UI.
 * 
 * @example
 * ```typescript
 * const message: Message = {
 *   // ... standard message fields ...
 *   visualization: {
 *     data_reference: "data_ref_abc123",
 *     chart_config: { ... },
 *     has_visualization: true
 *   }
 * };
 * ```
 */
export interface VisualizationMetadata {
  /** 
   * Cache key for query results.
   * Used to fetch data for both chart rendering and table display.
   */
  data_reference: string;
  
  /** 
   * Chart configuration from LLM.
   * Null if no chart should be displayed (chart_type === "table").
   */
  chart_config: ChartConfig | null;
  
  /** 
   * Whether visualization is available.
   * If false, VisualizationPanel should not be rendered.
   */
  has_visualization: boolean;
}

