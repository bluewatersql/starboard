/**
 * Unit tests for SSE event validation schemas.
 *
 * These tests ensure that:
 * 1. Valid events pass validation
 * 2. Invalid events are rejected with clear errors
 * 3. All event types are covered
 * 4. Edge cases are handled properly
 */

import {
  validateStreamingEvent,
  validateStreamingEventWithHandler,
  isEventType,
  formatValidationError,
  getValidationErrorPath,
  MessageStartEventSchema,
  MessageDeltaEventSchema,
  MessageCompleteEventSchema,
  ToolCallStartEventSchema,
  ToolProgressEventSchema,
  ToolCallResultEventSchema,
  FinalOutputEventSchema,
  ErrorEventSchema,
  HeartbeatEventSchema,
  NextStepsEventSchema,
} from "../event-schemas";
import { z } from "zod";

describe("Event Validation Schemas", () => {
  // ============================================================================
  // Base Event Structure
  // ============================================================================

  describe("Base Event Structure", () => {
    it("requires event_id, type, timestamp, and data", () => {
      const invalidEvent = {
        // Missing required fields
        type: "message.start",
      };

      const result = validateStreamingEvent(invalidEvent);

      expect(result.success).toBe(false);
      if (!result.success) {
        const paths = result.error.issues.map((i) => i.path.join("."));
        expect(paths).toContain("event_id");
        expect(paths).toContain("timestamp");
        expect(paths).toContain("data");
      }
    });

    it("validates timestamp format", () => {
      const invalidEvent = {
        event_id: "evt_123",
        type: "message.start",
        timestamp: "not-a-valid-datetime",
        data: { message_id: "msg_123" },
      };

      const result = validateStreamingEvent(invalidEvent);

      expect(result.success).toBe(false);
      if (!result.success) {
        expect(result.error.issues[0].path).toContain("timestamp");
      }
    });

    it("validates event_id is a string", () => {
      const invalidEvent = {
        event_id: 123, // Should be string
        type: "message.start",
        timestamp: new Date().toISOString(),
        data: { message_id: "msg_123" },
      };

      const result = validateStreamingEvent(invalidEvent);

      expect(result.success).toBe(false);
    });
  });

  // ============================================================================
  // MESSAGE_START Event
  // ============================================================================

  describe("MESSAGE_START Event", () => {
    it("validates correct message.start event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          conversation_id: "conv_xyz789",
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe("message.start");
        expect((result.data.data as { message_id: string }).message_id).toBe("msg_abc123");
      }
    });

    it("validates message_id format", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "invalid-format", // Should be msg_xxx
        },
      };

      const result = MessageStartEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("requires message_id in data", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.start",
        timestamp: new Date().toISOString(),
        data: {},  // Missing message_id
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(false);
      if (!result.success) {
        const paths = result.error.issues.map((i) => i.path.join("."));
        expect(paths.some((p) => p.includes("message_id"))).toBe(true);
      }
    });
  });

  // ============================================================================
  // MESSAGE_DELTA Event
  // ============================================================================

  describe("MESSAGE_DELTA Event", () => {
    it("validates correct message.delta event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.delta",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          delta: {
            content: "Let me analyze that...",
          },
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe("message.delta");
        expect((result.data.data as { delta: { content: string } }).delta.content).toBe("Let me analyze that...");
      }
    });

    it("requires delta object with content", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.delta",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          // Missing delta
        },
      };

      const result = MessageDeltaEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("validates delta.content is a string", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.delta",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          delta: {
            content: 123,  // Should be string
          },
        },
      };

      const result = MessageDeltaEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });
  });

  // ============================================================================
  // MESSAGE_COMPLETE Event
  // ============================================================================

  describe("MESSAGE_COMPLETE Event", () => {
    it("validates correct message.complete event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.complete",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          status: "completed",
          final_content: "Analysis complete.",
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("allows optional status and final_content", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.complete",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
        },
      };

      const result = MessageCompleteEventSchema.safeParse(event);

      expect(result.success).toBe(true);
    });
  });

  // ============================================================================
  // TOOL_CALL_START Event
  // ============================================================================

  describe("TOOL_CALL_START Event", () => {
    it("validates correct tool.call.start event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call: {
            tool_call_id: "call_xyz789",
            tool_name: "fetch_table_metadata",
            friendly_name: "Fetching Table Metadata",
            arguments: { table_name: "main.users" },
            status: "running",
          },
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.type).toBe("tool.call.start");
        const toolCallData = result.data.data as { tool_call: { tool_name: string; status: string } };
        expect(toolCallData.tool_call.tool_name).toBe("fetch_table_metadata");
        expect(toolCallData.tool_call.status).toBe("running");
      }
    });

    it("requires tool_call object in data", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          // Missing tool_call
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(false);
    });

    it("requires tool_name in tool_call", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call: {
            // Missing tool_name
            arguments: {},
            status: "running",
          },
        },
      };

      const result = ToolCallStartEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("validates status is 'running' for tool.call.start", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call: {
            tool_name: "fetch_data",
            arguments: {},
            status: "completed",  // Should be "running" for start event
          },
        },
      };

      const result = ToolCallStartEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("allows optional tool_call_id and friendly_name", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call: {
            tool_name: "fetch_data",
            arguments: {},
            status: "running",
          },
        },
      };

      const result = ToolCallStartEventSchema.safeParse(event);

      expect(result.success).toBe(true);
    });
  });

  // ============================================================================
  // TOOL_PROGRESS Event
  // ============================================================================

  describe("TOOL_PROGRESS Event", () => {
    it("validates correct tool.progress event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.progress",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call_id: "call_xyz789",
          progress_message: "Fetching schema information...",
          progress_percentage: 45,
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("requires tool_call_id and progress_message", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.progress",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          // Missing tool_call_id and progress_message
        },
      };

      const result = ToolProgressEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("validates progress_percentage is between 0-100", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.progress",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call_id: "call_xyz",
          progress_message: "Processing...",
          progress_percentage: 150,  // Invalid: > 100
        },
      };

      const result = ToolProgressEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });
  });

  // ============================================================================
  // TOOL_CALL_RESULT Event
  // ============================================================================

  describe("TOOL_CALL_RESULT Event", () => {
    it("validates correct tool.call.result event (completed)", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.result",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call: {
            tool_call_id: "call_xyz789",
            tool_name: "fetch_table_metadata",
            friendly_name: "Fetching Table Metadata",
            arguments: { table_name: "main.users" },
            status: "completed",
            result: { columns: 5, rows: 1000 },
            duration_ms: 234,
          },
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("validates correct tool.call.result event (failed)", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.result",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call: {
            tool_name: "fetch_data",
            arguments: {},
            status: "failed",
            error: "Table not found",
          },
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("validates status is 'completed' or 'failed'", () => {
      const event = {
        event_id: "evt_abc123",
        type: "tool.call.result",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          tool_call: {
            tool_name: "fetch_data",
            arguments: {},
            status: "running",  // Invalid for result event
          },
        },
      };

      const result = ToolCallResultEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });
  });

  // ============================================================================
  // FINAL_OUTPUT Event
  // ============================================================================

  describe("FINAL_OUTPUT Event", () => {
    it("validates correct final_output event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "final_output",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          output: {
            status: "success",
            formatted_report: "# Analysis Complete\n\nResults...",
            complete_report: { findings: [] },
            tokens_used: 1500,
            cost_usd: 0.05,
            duration_seconds: 12.5,
            steps_taken: 3,
          },
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("requires output object with status", () => {
      const event = {
        event_id: "evt_abc123",
        type: "final_output",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          // Missing output
        },
      };

      const result = FinalOutputEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("validates status is one of: success, error, partial", () => {
      const event = {
        event_id: "evt_abc123",
        type: "final_output",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          output: {
            status: "invalid",  // Invalid status
          },
        },
      };

      const result = FinalOutputEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("validates non-negative numbers for metrics", () => {
      const event = {
        event_id: "evt_abc123",
        type: "final_output",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          output: {
            status: "success",
            tokens_used: -100,  // Invalid: negative
          },
        },
      };

      const result = FinalOutputEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });
  });

  // ============================================================================
  // ERROR Event
  // ============================================================================

  describe("ERROR Event", () => {
    it("validates correct error event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "error",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          error: {
            message: "Failed to connect to database",
            code: "DB_CONNECTION_ERROR",
            details: { host: "localhost", port: 5432 },
          },
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("requires error object with message", () => {
      const event = {
        event_id: "evt_abc123",
        type: "error",
        timestamp: new Date().toISOString(),
        data: {
          error: {},  // Missing message
        },
      };

      const result = ErrorEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });

    it("allows optional message_id", () => {
      const event = {
        event_id: "evt_abc123",
        type: "error",
        timestamp: new Date().toISOString(),
        data: {
          // No message_id (global error)
          error: {
            message: "System error",
          },
        },
      };

      const result = ErrorEventSchema.safeParse(event);

      expect(result.success).toBe(true);
    });
  });

  // ============================================================================
  // HEARTBEAT Event
  // ============================================================================

  describe("HEARTBEAT Event", () => {
    it("validates correct heartbeat event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "heartbeat",
        timestamp: new Date().toISOString(),
        data: {
          timestamp: new Date().toISOString(),
          message: "Keep-alive",
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("requires timestamp in data", () => {
      const event = {
        event_id: "evt_abc123",
        type: "heartbeat",
        timestamp: new Date().toISOString(),
        data: {},  // Missing timestamp
      };

      const result = HeartbeatEventSchema.safeParse(event);

      expect(result.success).toBe(false);
    });
  });

  // ============================================================================
  // NEXT_STEPS Event
  // ============================================================================

  describe("NEXT_STEPS Event", () => {
    it("validates correct next_steps event", () => {
      const event = {
        event_id: "evt_abc123",
        type: "next_steps",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          next_steps: [
            {
              id: "step_1",
              number: 1,
              title: "Optimize query",
              description: "Improve performance",
              action_type: "tool_call",
              target_agent: null,
              tool_name: "optimize_query",
              parameters: { query_id: "123" },
            },
            {
              id: "step_2",
              number: 2,
              title: "Analyze results",
              description: null,
              action_type: "continue",
              target_agent: null,
              tool_name: null,
              parameters: null,
            },
          ],
        },
      };

      const result = validateStreamingEvent(event);

      expect(result.success).toBe(true);
    });

    it("requires at least 1 and at most 9 next_steps", () => {
      const emptySteps = {
        event_id: "evt_abc123",
        type: "next_steps",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          next_steps: [],  // Empty array
        },
      };

      const result1 = NextStepsEventSchema.safeParse(emptySteps);
      expect(result1.success).toBe(false);

      const tooManySteps = {
        event_id: "evt_abc123",
        type: "next_steps",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          next_steps: Array.from({ length: 10 }, (_, i) => ({
            id: `step_${i}`,
            number: i + 1,
            title: `Step ${i}`,
            description: null,
            action_type: "continue",
            target_agent: null,
            tool_name: null,
            parameters: null,
          })),
        },
      };

      const result2 = NextStepsEventSchema.safeParse(tooManySteps);
      expect(result2.success).toBe(false);
    });

    it("validates step number is between 1-9", () => {
      const event = {
        event_id: "evt_abc123",
        type: "next_steps",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
          next_steps: [
            {
              id: "step_10",
              number: 10,  // Invalid: > 9
              title: "Step 10",
              description: null,
              action_type: "continue",
              target_agent: null,
              tool_name: null,
              parameters: null,
            },
          ],
        },
      };

      const result = NextStepsEventSchema.safeParse(event);
      expect(result.success).toBe(false);
    });
  });

  // ============================================================================
  // Validation Utility Functions
  // ============================================================================

  describe("validateStreamingEventWithHandler", () => {
    it("calls error handler on validation failure", () => {
      const mockErrorHandler = jest.fn();
      const invalidEvent = {
        event_id: "evt_123",
        type: "message.start",
        timestamp: new Date().toISOString(),
        data: {},  // Missing message_id
      };

      const result = validateStreamingEventWithHandler(
        invalidEvent,
        mockErrorHandler
      );

      expect(result).toBeNull();
      expect(mockErrorHandler).toHaveBeenCalledTimes(1);
      expect(mockErrorHandler).toHaveBeenCalledWith(
        expect.any(Object),
        invalidEvent
      );
    });

    it("returns validated data on success", () => {
      const mockErrorHandler = jest.fn();
      const validEvent = {
        event_id: "evt_abc123",
        type: "message.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
        },
      };

      const result = validateStreamingEventWithHandler(
        validEvent,
        mockErrorHandler
      );

      expect(result).not.toBeNull();
      expect(result?.type).toBe("message.start");
      expect(mockErrorHandler).not.toHaveBeenCalled();
    });
  });

  describe("isEventType", () => {
    it("correctly narrows event type", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.start" as const,
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
        },
      };

      const result = validateStreamingEvent(event);
      if (result.success) {
        if (isEventType(result.data, "message.start")) {
          // Type should be narrowed to MessageStartEvent
          expect(result.data.data.message_id).toBe("msg_abc123");
        }
      }
    });

    it("returns false for different event type", () => {
      const event = {
        event_id: "evt_abc123",
        type: "message.start" as const,
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_abc123",
        },
      };

      const result = validateStreamingEvent(event);
      if (result.success) {
        expect(isEventType(result.data, "message.complete")).toBe(false);
      }
    });
  });

  describe("formatValidationError", () => {
    it("formats validation error as JSON string", () => {
      const invalidEvent = {
        event_id: "evt_123",
        type: "message.start",
        timestamp: new Date().toISOString(),
        data: {},
      };

      const result = validateStreamingEvent(invalidEvent);

      if (!result.success) {
        const formatted = formatValidationError(result.error);
        expect(formatted).toContain("message_id");
        expect(() => JSON.parse(formatted)).not.toThrow();
      }
    });
  });

  describe("getValidationErrorPath", () => {
    it("extracts error path from validation error", () => {
      const invalidEvent = {
        event_id: "evt_123",
        type: "tool.call.start",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          tool_call: {
            // Missing tool_name
            arguments: {},
            status: "running",
          },
        },
      };

      const result = ToolCallStartEventSchema.safeParse(invalidEvent);

      if (!result.success) {
        const path = getValidationErrorPath(result.error);
        expect(path.length).toBeGreaterThan(0);
        expect(path.join(".")).toContain("tool_call");
      }
    });

    it("returns empty array for no errors", () => {
      const error = {
        issues: [],
      } as unknown as z.ZodError;

      const path = getValidationErrorPath(error);
      expect(path).toEqual([]);
    });
  });
});

