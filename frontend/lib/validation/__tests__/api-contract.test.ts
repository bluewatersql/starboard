/**
 * Frontend API Contract Tests
 * 
 * Validates that frontend types match backend API schemas.
 * Ensures type-safety and backward compatibility.
 * 
 * Part of Option 1: Enhanced API Contract Testing.
 */

import { describe, expect, test } from '@jest/globals';
import { z } from 'zod';
import type { 
  MessageResponse, 
  ConversationResponse, 
  SendMessageRequest,
  CreateConversationRequest,
  SubmitFeedbackRequest 
} from '@/lib/types/api';
import { FeedbackRatingEnum } from '@/lib/types/api';

// ============================================================================
// Schema Definitions (matching backend Pydantic models)
// ============================================================================

const ConversationCreateRequestSchema = z.object({
  context: z.record(z.string(), z.any()).nullable().optional(),
  config: z.any().nullable().optional(),
  initial_message: z.string().nullable().optional(),
  metadata: z.record(z.string(), z.any()).nullable().optional(),
});

const ConversationResponseSchema = z.object({
  conversation_id: z.string(),
  user_id: z.string().nullable().optional(),
  friendly_name: z.string(),
  created_at: z.string(),
  config: z.any(),
});

const MessageRequestSchema = z.object({
  content: z.string().min(1),
  attachments: z.array(z.record(z.string(), z.unknown())).nullable().optional(),
  metadata: z.record(z.string(), z.unknown()).nullable().optional(),
});

const MessageResponseSchema = z.object({
  message_id: z.string(),
  conversation_id: z.string(),
  status: z.enum(['pending', 'processing', 'completed', 'failed']),
  trace_id: z.string().nullable().optional(),
});

const FeedbackRequestSchema = z.object({
  message_id: z.string(),
  rating: z.enum(['positive', 'negative']),
  comment: z.string().optional(),
});

// ============================================================================
// Contract Tests: Request Schemas
// ============================================================================

describe('API Request Contracts', () => {
  describe('ConversationCreateRequest', () => {
    test('should validate correct request', () => {
      // Note: user_id is now extracted from auth middleware, not from request body
      const data: CreateConversationRequest = {
        initial_message: 'Analyze my query',
      };

      const result = ConversationCreateRequestSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should allow empty request (all fields optional)', () => {
      const data: CreateConversationRequest = {};

      const result = ConversationCreateRequestSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should match TypeScript type', () => {
      const data: CreateConversationRequest = {
        initial_message: 'Test message',
        context: { job_id: '12345' },
      };

      // If this compiles, type matches schema
      const validated = ConversationCreateRequestSchema.parse(data);
      expect(validated.initial_message).toBe('Test message');
    });
  });

  describe('MessageRequest', () => {
    test('should validate correct request', () => {
      const data: SendMessageRequest = {
        content: 'Show me cost trends',
      };

      const result = MessageRequestSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should allow optional fields', () => {
      const data: SendMessageRequest = {
        content: 'Test message',
        attachments: [{ type: 'file', name: 'data.csv' }],
        metadata: { source: 'ui' },
      };

      const result = MessageRequestSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should reject missing required content', () => {
      const data = {
        // Missing content
        metadata: { test: true },
      };

      const result = MessageRequestSchema.safeParse(data);
      expect(result.success).toBe(false);
    });

    test('should reject empty content', () => {
      const data = {
        content: '', // Empty string not allowed (min 1)
      };

      const result = MessageRequestSchema.safeParse(data);
      expect(result.success).toBe(false);
    });
  });

  describe('FeedbackRequest', () => {
    test('should validate positive feedback', () => {
      const data: SubmitFeedbackRequest = {
        message_id: 'msg_123',
        rating: FeedbackRatingEnum.POSITIVE,
      };

      const result = FeedbackRequestSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should validate negative feedback with comment', () => {
      const data: SubmitFeedbackRequest = {
        message_id: 'msg_123',
        rating: FeedbackRatingEnum.NEGATIVE,
        comment: 'Response was not helpful',
      };

      const result = FeedbackRequestSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should reject invalid rating', () => {
      const data = {
        message_id: 'msg_123',
        rating: 'neutral', // Not in enum
      };

      const result = FeedbackRequestSchema.safeParse(data);
      expect(result.success).toBe(false);
    });
  });
});

// ============================================================================
// Contract Tests: Response Schemas
// ============================================================================

describe('API Response Contracts', () => {
  describe('ConversationResponse', () => {
    test('should validate correct response', () => {
      const data: ConversationResponse = {
        conversation_id: 'conv_abc',
        user_id: 'user_123',
        friendly_name: 'My Conversation',
        created_at: '2025-11-28T10:00:00Z',
        config: {},
      };

      const result = ConversationResponseSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should reject missing required fields', () => {
      const data = {
        conversation_id: 'conv_abc',
        // Missing user_id and created_at
      };

      const result = ConversationResponseSchema.safeParse(data);
      expect(result.success).toBe(false);
    });
  });

  describe('MessageResponse', () => {
    test('should validate correct response', () => {
      const data: MessageResponse = {
        message_id: 'msg_123',
        conversation_id: 'conv_456',
        status: 'completed',
        trace_id: 'trace_789',
      };

      const result = MessageResponseSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should handle missing optional trace_id', () => {
      const data: MessageResponse = {
        message_id: 'msg_123',
        conversation_id: 'conv_456',
        status: 'completed',
      };

      const result = MessageResponseSchema.safeParse(data);
      expect(result.success).toBe(true);
    });

    test('should accept valid status values', () => {
      const statuses: Array<"pending" | "processing" | "completed" | "failed"> = [
        'pending', 'processing', 'completed', 'failed'
      ];

      statuses.forEach(status => {
        const data: MessageResponse = {
          message_id: 'msg_123',
          conversation_id: 'conv_456',
          status: status,
        };

        const result = MessageResponseSchema.safeParse(data);
        expect(result.success).toBe(true);
      });
    });

    test('should reject invalid status values', () => {
      const invalidData = {
        message_id: 'msg_123',
        conversation_id: 'conv_456',
        status: 'invalid_status',
      };

      const result = MessageResponseSchema.safeParse(invalidData);
      expect(result.success).toBe(false);
    });
  });
});

// ============================================================================
// Backward Compatibility Tests
// ============================================================================

describe('Backward Compatibility', () => {
  test('MessageResponse maintains required fields', () => {
    // Ensure existing frontend code continues to work
    // Required fields: message_id, conversation_id, status
    const incompleteData = {
      message_id: 'msg_123',
      // Missing: conversation_id, status
    };

    const result = MessageResponseSchema.safeParse(incompleteData);
    expect(result.success).toBe(false);
  });

  test('adding optional fields does not break existing code', () => {
    // New optional fields should not break existing valid requests
    const minimalData: SendMessageRequest = {
      content: 'Test',
    };

    const result = MessageRequestSchema.safeParse(minimalData);
    expect(result.success).toBe(true);
  });

  test('trace_id field remains optional', () => {
    // Frontend should handle responses with or without trace_id
    const withoutTraceId: MessageResponse = {
      message_id: 'msg_123',
      conversation_id: 'conv_456',
      status: 'completed',
    };

    const result = MessageResponseSchema.safeParse(withoutTraceId);
    expect(result.success).toBe(true);
  });
});

// ============================================================================
// Serialization Tests
// ============================================================================

describe('JSON Serialization', () => {
  test('should serialize and deserialize MessageResponse', () => {
    const original: MessageResponse = {
      message_id: 'msg_123',
      conversation_id: 'conv_456',
      status: 'completed',
      trace_id: 'trace_789',
    };

    // Serialize to JSON
    const json = JSON.stringify(original);

    // Deserialize back
    const restored = JSON.parse(json);

    // Validate schema
    const result = MessageResponseSchema.safeParse(restored);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).toEqual(original);
    }
  });

  test('should handle null trace_id', () => {
    const data: MessageResponse = {
      message_id: 'msg_123',
      conversation_id: 'conv_456',
      status: 'processing',
      trace_id: null,
    };

    const json = JSON.stringify(data);
    const restored = JSON.parse(json);

    const result = MessageResponseSchema.safeParse(restored);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.trace_id).toBeNull();
    }
  });
});

// ============================================================================
// Integration Test: Full Request/Response Cycle
// ============================================================================

describe('Request/Response Cycle', () => {
  test('conversation creation cycle', () => {
    // Request (user_id now from auth, not request body)
    const request: CreateConversationRequest = {
      initial_message: 'Analyze my job performance',
    };

    const requestResult = ConversationCreateRequestSchema.safeParse(request);
    expect(requestResult.success).toBe(true);

    // Response (simulated - user_id added by server from auth)
    const response: ConversationResponse = {
      conversation_id: 'conv_abc',
      user_id: 'user_123', // Added by server
      friendly_name: 'New Conversation',
      created_at: '2025-11-28T10:00:00Z',
      config: {},
    };

    const responseResult = ConversationResponseSchema.safeParse(response);
    expect(responseResult.success).toBe(true);
    
    if (requestResult.success && responseResult.success) {
      expect(responseResult.data.conversation_id).toBe('conv_abc');
    }
  });

  test('message send cycle', () => {
    // Request
    const request: SendMessageRequest = {
      content: 'Show me cost trends',
    };

    const requestResult = MessageRequestSchema.safeParse(request);
    expect(requestResult.success).toBe(true);

    // Response (simulated)
    const response: MessageResponse = {
      message_id: 'msg_456',
      conversation_id: 'conv_789',
      status: 'processing',
      trace_id: 'trace_abc',
    };

    const responseResult = MessageResponseSchema.safeParse(response);
    expect(responseResult.success).toBe(true);
  });
});

// ============================================================================
// Schema Evolution Tests
// ============================================================================

describe('Schema Evolution', () => {
  test('should handle unknown fields gracefully', () => {
    // Backend might add new fields in future
    // Frontend should not break if it receives extra fields
    const responseWithExtraFields = {
      message_id: 'msg_123',
      conversation_id: 'conv_456',
      status: 'completed',
      trace_id: 'trace_abc',
      // Future fields that might be added:
      created_at: '2025-11-28T10:00:00Z',
      updated_at: '2025-11-28T10:01:00Z',
    };

    // Schema should still validate core fields
    const result = MessageResponseSchema.safeParse(responseWithExtraFields);
    expect(result.success).toBe(true);
  });
});

