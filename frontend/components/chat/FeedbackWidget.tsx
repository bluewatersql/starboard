/**
 * FeedbackWidget Component
 * 
 * Displays thumbs up/down feedback buttons for agent messages.
 * Part of Phase 1: Conversation Patterns - Pattern 4 (Feedback Collection).
 * 
 * Features:
 * - Thumbs up/down buttons
 * - Visual feedback on selection
 * - Persists feedback state
 * - Optional comment collection (future enhancement)
 */

'use client';

import { useState } from 'react';
import { Box, IconButton, Tooltip, Fade, Typography } from '@mui/material';
import { ThumbUpRounded, ThumbDownRounded } from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import { FeedbackRating } from '@/lib/types/api';

interface FeedbackWidgetProps {
  messageId: string;
  conversationId: string;
  onSubmitFeedback: (messageId: string, rating: FeedbackRating) => Promise<void>;
  disabled?: boolean;
}

/**
 * Feedback widget component.
 * 
 * Displays thumbs up/down buttons for collecting user feedback on messages.
 * 
 * @param props - Component props
 * @returns Feedback widget component
 * 
 * @example
 * ```tsx
 * <FeedbackWidget
 *   messageId="msg_123"
 *   conversationId="conv_456"
 *   onSubmitFeedback={handleFeedback}
 * />
 * ```
 */
export function FeedbackWidget({
  messageId,
  conversationId: _conversationId, // eslint-disable-line @typescript-eslint/no-unused-vars
  onSubmitFeedback,
  disabled = false,
}: FeedbackWidgetProps) {
  const theme = useTheme();
  const [selectedRating, setSelectedRating] = useState<FeedbackRating | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showThankYou, setShowThankYou] = useState(false);

  const handleFeedbackClick = async (rating: FeedbackRating) => {
    if (disabled || isSubmitting || selectedRating) {
      return;
    }

    setIsSubmitting(true);
    try {
      await onSubmitFeedback(messageId, rating);
      setSelectedRating(rating);
      setShowThankYou(true);
      
      // Hide thank you message after 2 seconds
      setTimeout(() => {
        setShowThankYou(false);
      }, 2000);
    } catch (error) {
      console.error('Failed to submit feedback:', error);
      // Reset on error so user can try again
      setIsSubmitting(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.5,
        mt: 0.5,
      }}
    >
      {/* Thumbs Up Button */}
      <Tooltip
        title={selectedRating === FeedbackRating.POSITIVE ? "Thanks for your feedback!" : "This was helpful"}
        arrow
        placement="top"
      >
        <span>
          <IconButton
            size="small"
            onClick={() => handleFeedbackClick(FeedbackRating.POSITIVE)}
            disabled={disabled || isSubmitting || selectedRating !== null}
            sx={{
              color: selectedRating === FeedbackRating.POSITIVE
                ? 'success.main'
                : 'text.secondary',
              opacity: selectedRating === null || selectedRating === FeedbackRating.POSITIVE
                ? 1
                : 0.3,
              transition: 'all 0.2s',
              '&:hover': {
                color: 'success.main',
                bgcolor: theme.palette.mode === 'dark'
                  ? 'rgba(76, 175, 80, 0.1)'
                  : 'rgba(76, 175, 80, 0.08)',
                transform: selectedRating === null ? 'scale(1.1)' : 'none',
              },
              '&.Mui-disabled': {
                color: selectedRating === FeedbackRating.POSITIVE
                  ? 'success.main'
                  : 'text.disabled',
              },
            }}
          >
            <ThumbUpRounded sx={{ fontSize: 18 }} />
          </IconButton>
        </span>
      </Tooltip>

      {/* Thumbs Down Button */}
      <Tooltip
        title={selectedRating === FeedbackRating.NEGATIVE ? "Thanks for your feedback!" : "This needs improvement"}
        arrow
        placement="top"
      >
        <span>
          <IconButton
            size="small"
            onClick={() => handleFeedbackClick(FeedbackRating.NEGATIVE)}
            disabled={disabled || isSubmitting || selectedRating !== null}
            sx={{
              color: selectedRating === FeedbackRating.NEGATIVE
                ? 'error.main'
                : 'text.secondary',
              opacity: selectedRating === null || selectedRating === FeedbackRating.NEGATIVE
                ? 1
                : 0.3,
              transition: 'all 0.2s',
              '&:hover': {
                color: 'error.main',
                bgcolor: theme.palette.mode === 'dark'
                  ? 'rgba(244, 67, 54, 0.1)'
                  : 'rgba(244, 67, 54, 0.08)',
                transform: selectedRating === null ? 'scale(1.1)' : 'none',
              },
              '&.Mui-disabled': {
                color: selectedRating === FeedbackRating.NEGATIVE
                  ? 'error.main'
                  : 'text.disabled',
              },
            }}
          >
            <ThumbDownRounded sx={{ fontSize: 18 }} />
          </IconButton>
        </span>
      </Tooltip>

      {/* Thank You Message */}
      <Fade in={showThankYou} timeout={300}>
        <Typography
          variant="caption"
          sx={{
            ml: 1,
            color: 'text.secondary',
            fontStyle: 'italic',
          }}
        >
          Thanks!
        </Typography>
      </Fade>
    </Box>
  );
}

