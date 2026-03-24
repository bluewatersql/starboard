/**
 * NextStepsCard Component
 * 
 * Displays structured next step options for user selection.
 * Part of Phase 1: Conversation Patterns - Pattern 1 (Option Selection).
 * 
 * Features:
 * - Displays 1-9 numbered options
 * - Color-coded by action type (Continue, Route, Tool Call)
 * - Click handling for option selection
 * - Keyboard navigation support
 * - Responsive design
 */

'use client';

import { useState } from 'react';
import { Box, Card, CardContent, Typography, Button, Stack, Chip } from '@mui/material';
import {
  PlayArrowRounded,
  CallSplitRounded,
  BuildRounded,
} from '@mui/icons-material';
import { NextStepOption, ActionType } from '@/lib/types/api';

interface NextStepsCardProps {
  options: NextStepOption[];
  onSelectOption: (option: NextStepOption) => void;
  disabled?: boolean;
}

/**
 * Get icon for action type
 */
function getActionIcon(actionType: ActionType) {
  switch (actionType) {
    case ActionType.CONTINUE:
      return <PlayArrowRounded />;
    case ActionType.ROUTE:
      return <CallSplitRounded />;
    case ActionType.TOOL_CALL:
      return <BuildRounded />;
    default:
      return <PlayArrowRounded />;
  }
}

/**
 * Get color for action type
 */
function getActionColor(actionType: ActionType): 'primary' | 'secondary' | 'success' {
  switch (actionType) {
    case ActionType.CONTINUE:
      return 'primary';
    case ActionType.ROUTE:
      return 'secondary';
    case ActionType.TOOL_CALL:
      return 'success';
    default:
      return 'primary';
  }
}

/**
 * Get label for action type
 */
function getActionLabel(actionType: ActionType): string {
  switch (actionType) {
    case ActionType.CONTINUE:
      return 'Continue';
    case ActionType.ROUTE:
      return 'Route';
    case ActionType.TOOL_CALL:
      return 'Execute';
    default:
      return 'Action';
  }
}

export default function NextStepsCard({ options, onSelectOption, disabled = false }: NextStepsCardProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const handleOptionClick = (option: NextStepOption) => {
    if (disabled) return;
    
    setSelectedId(option.id);
    onSelectOption(option);
  };

  const handleKeyPress = (event: React.KeyboardEvent, option: NextStepOption) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleOptionClick(option);
    }
  };

  return (
    <Card 
      elevation={0}
      sx={{ 
        bgcolor: 'background.paper',
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 2,
        mt: 2,
      }}
    >
      <CardContent>
        <Typography
          variant="subtitle2"
          sx={{ 
            fontWeight: 600,
            mb: 2,
            color: 'text.secondary',
          }}
        >
          What would you like to do next?
        </Typography>
        
        <Stack spacing={1.5}>
          {options.map((option) => {
            const isSelected = selectedId === option.id;
            const color = getActionColor(option.action_type);
            
            return (
              <Button
                key={option.id}
                onClick={() => handleOptionClick(option)}
                onKeyPress={(e) => handleKeyPress(e, option)}
                disabled={disabled}
                variant={isSelected ? 'contained' : 'outlined'}
                color={color}
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
                      bgcolor: isSelected ? 'background.paper' : `${color}.main`,
                      color: isSelected ? `${color}.main` : 'background.paper',
                      fontWeight: 700,
                      fontSize: '0.875rem',
                    }}
                  >
                    {option.number}
                  </Box>

                  {/* Content */}
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography
                      variant="body1"
                      sx={{
                        fontWeight: 600,
                        color: isSelected ? 'inherit' : 'text.primary',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1,
                      }}
                    >
                      {option.title}
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

                  {/* Action Type Badge */}
                  <Chip
                    icon={getActionIcon(option.action_type)}
                    label={getActionLabel(option.action_type)}
                    size="small"
                    color={color}
                    variant={isSelected ? 'filled' : 'outlined'}
                    sx={{
                      fontWeight: 500,
                      fontSize: '0.75rem',
                    }}
                  />
                </Box>
              </Button>
            );
          })}
        </Stack>

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
          You can also type a number (1-{options.length}) or continue with a new question.
        </Typography>
      </CardContent>
    </Card>
  );
}

