/**
 * ClarificationDialog Component
 * 
 * Displays clarification requests and collects user responses.
 * Part of Phase 7: Conversation Patterns - Pattern 7 (Clarification Request).
 * 
 * Features:
 * - Displays clarification question and context
 * - Shows predefined options (if provided)
 * - Allows custom text input (if enabled)
 * - Submits response via API
 * - Loading states and error handling
 */

'use client';

import { useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  Stack,
  TextField,
  Alert,
  CircularProgress,
} from '@mui/material';
import {
  HelpOutlineRounded,
  SendRounded,
  CloseRounded,
} from '@mui/icons-material';
import type { ClarificationRequest, ClarificationOption } from '@/lib/types/api';

interface ClarificationDialogProps {
  /** The clarification request data */
  clarification: ClarificationRequest;
  
  /** Callback when user responds with an option */
  onRespondWithOption: (optionId: string) => Promise<void>;
  
  /** Callback when user responds with custom text */
  onRespondWithCustomText: (text: string) => Promise<void>;
  
  /** Callback to dismiss/cancel clarification (if not required) */
  onDismiss?: () => void;
  
  /** Whether the component is in a loading/submitting state */
  isSubmitting?: boolean;
  
  /** Error message to display */
  error?: Error | null;
}

export default function ClarificationDialog({
  clarification,
  onRespondWithOption,
  onRespondWithCustomText,
  onDismiss,
  isSubmitting = false,
  error = null,
}: ClarificationDialogProps) {
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [customText, setCustomText] = useState('');
  const [inputMode, setInputMode] = useState<'options' | 'custom'>('options');

  const handleOptionClick = async (optionId: string) => {
    if (isSubmitting) return;
    
    setSelectedOptionId(optionId);
    try {
      await onRespondWithOption(optionId);
    } catch (err) {
      // Error handled by parent component
      console.error('Failed to submit option:', err);
    }
  };

  const handleCustomSubmit = async () => {
    if (isSubmitting || !customText.trim()) return;
    
    try {
      await onRespondWithCustomText(customText.trim());
    } catch (err) {
      // Error handled by parent component
      console.error('Failed to submit custom text:', err);
    }
  };

  const hasOptions = clarification.options && clarification.options.length > 0;
  const showCustomInput = clarification.allow_custom_response && inputMode === 'custom';

  return (
    <Card 
      elevation={2}
      sx={{ 
        bgcolor: 'warning.50',
        border: '2px solid',
        borderColor: 'warning.main',
        borderRadius: 2,
        mt: 2,
      }}
    >
      <CardContent>
        {/* Header */}
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, mb: 2 }}>
          <HelpOutlineRounded 
            sx={{ 
              color: 'warning.main',
              fontSize: 28,
              mt: 0.25,
            }} 
          />
          <Box sx={{ flex: 1 }}>
            <Typography
              variant="subtitle1"
              sx={{ 
                fontWeight: 600,
                color: 'warning.dark',
                mb: 0.5,
              }}
            >
              Clarification Needed
            </Typography>
            <Typography
              variant="body1"
              sx={{ 
                color: 'text.primary',
                fontWeight: 500,
              }}
            >
              {clarification.question}
            </Typography>
          </Box>
          
          {/* Dismiss button (if not required) */}
          {!clarification.is_required && onDismiss && (
            <Button
              onClick={onDismiss}
              disabled={isSubmitting}
              size="small"
              sx={{ minWidth: 'auto', p: 0.5 }}
            >
              <CloseRounded fontSize="small" />
            </Button>
          )}
        </Box>

        {/* Error Display */}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error.message}
          </Alert>
        )}

        {/* Options Display */}
        {hasOptions && inputMode === 'options' && (
          <Stack spacing={1.5} sx={{ mb: 2 }}>
            {clarification.options!.map((option: ClarificationOption, index: number) => {
              const isSelected = selectedOptionId === option.option_id;
              
              return (
                <Button
                  key={option.option_id}
                  onClick={() => handleOptionClick(option.option_id)}
                  disabled={isSubmitting}
                  variant={isSelected ? 'contained' : 'outlined'}
                  color="warning"
                  fullWidth
                  sx={{
                    justifyContent: 'flex-start',
                    textAlign: 'left',
                    py: 1.5,
                    px: 2,
                    textTransform: 'none',
                    borderRadius: 1.5,
                    transition: 'all 0.2s',
                    '&:hover': {
                      transform: 'translateX(4px)',
                      boxShadow: 1,
                    },
                    '&.Mui-disabled': {
                      opacity: 0.6,
                    },
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, width: '100%' }}>
                    {/* Option Number */}
                    <Box
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: 32,
                        height: 32,
                        borderRadius: '50%',
                        bgcolor: isSelected ? 'background.paper' : 'warning.main',
                        color: isSelected ? 'warning.main' : 'background.paper',
                        fontWeight: 700,
                        fontSize: '0.875rem',
                      }}
                    >
                      {index + 1}
                    </Box>

                    {/* Content */}
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography
                        variant="body1"
                        sx={{
                          fontWeight: 600,
                          color: isSelected ? 'inherit' : 'text.primary',
                        }}
                      >
                        {option.display_text}
                      </Typography>
                      
                      {option.description && (
                        <Typography
                          variant="body2"
                          sx={{
                            color: isSelected ? 'inherit' : 'text.secondary',
                            mt: 0.5,
                            opacity: 0.9,
                          }}
                        >
                          {option.description}
                        </Typography>
                      )}
                    </Box>

                    {/* Loading Indicator */}
                    {isSubmitting && isSelected && (
                      <CircularProgress size={20} color="inherit" />
                    )}
                  </Box>
                </Button>
              );
            })}
          </Stack>
        )}

        {/* Custom Text Input */}
        {showCustomInput && (
          <Box sx={{ mb: 2 }}>
            <TextField
              fullWidth
              multiline
              rows={2}
              value={customText}
              onChange={(e) => setCustomText(e.target.value)}
              disabled={isSubmitting}
              placeholder="Enter your response..."
              variant="outlined"
              sx={{ mb: 1.5 }}
            />
            <Button
              onClick={handleCustomSubmit}
              disabled={isSubmitting || !customText.trim()}
              variant="contained"
              color="warning"
              startIcon={isSubmitting ? <CircularProgress size={20} /> : <SendRounded />}
              sx={{ textTransform: 'none' }}
            >
              {isSubmitting ? 'Submitting...' : 'Submit Response'}
            </Button>
          </Box>
        )}

        {/* Mode Toggle (if custom text allowed and options exist) */}
        {clarification.allow_custom_response && hasOptions && (
          <Box sx={{ mt: 2, pt: 2, borderTop: '1px solid', borderColor: 'divider' }}>
            {inputMode === 'options' ? (
              <Button
                onClick={() => setInputMode('custom')}
                disabled={isSubmitting}
                size="small"
                sx={{ textTransform: 'none' }}
              >
                Or type a custom response
              </Button>
            ) : (
              <Button
                onClick={() => setInputMode('options')}
                disabled={isSubmitting}
                size="small"
                sx={{ textTransform: 'none' }}
              >
                Choose from options instead
              </Button>
            )}
          </Box>
        )}

        {/* Only Custom Text (no options) */}
        {!hasOptions && clarification.allow_custom_response && !showCustomInput && (
          <Box>
            <TextField
              fullWidth
              multiline
              rows={2}
              value={customText}
              onChange={(e) => setCustomText(e.target.value)}
              disabled={isSubmitting}
              placeholder="Enter your response..."
              variant="outlined"
              sx={{ mb: 1.5 }}
            />
            <Button
              onClick={handleCustomSubmit}
              disabled={isSubmitting || !customText.trim()}
              variant="contained"
              color="warning"
              startIcon={isSubmitting ? <CircularProgress size={20} /> : <SendRounded />}
              sx={{ textTransform: 'none' }}
            >
              {isSubmitting ? 'Submitting...' : 'Submit Response'}
            </Button>
          </Box>
        )}

        {/* Helper Text */}
        <Typography
          variant="caption"
          sx={{
            display: 'block',
            mt: 2,
            color: 'text.secondary',
            fontStyle: 'italic',
          }}
        >
          {clarification.is_required
            ? 'A response is required to continue.'
            : 'You can skip this clarification if you prefer.'}
          {clarification.target_tool && ` This will be used for: ${clarification.target_tool}`}
        </Typography>
      </CardContent>
    </Card>
  );
}

