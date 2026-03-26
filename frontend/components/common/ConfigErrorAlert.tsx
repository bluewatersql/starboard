/**
 * ConfigErrorAlert component.
 *
 * Displays prominent configuration error alerts with fix instructions.
 * Styled to stand out from regular errors and guide users to resolution.
 */

"use client";

import React from "react";
import { Alert, AlertTitle, Box, Typography, List, ListItem, ListItemText, Collapse, IconButton } from "@mui/material";
import SettingsIcon from "@mui/icons-material/Settings";
import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";

interface ConfigErrorAlertProps {
  errorMessage: string;
  onDismiss?: () => void;
}

/**
 * Parse error message to extract structured information.
 * Expected format from backend:
 * - First line: Error description
 * - "How to fix:" section with numbered steps
 * - "Valid model names:" section with bullet points
 */
function parseErrorMessage(message: string): {
  description: string;
  howToFix: string[];
  validModels: string[];
} {
  const lines = message.split('\n').map(l => l.trim()).filter(l => l);
  
  let description = '';
  const howToFix: string[] = [];
  const validModels: string[] = [];
  
  let currentSection: 'description' | 'howToFix' | 'validModels' = 'description';
  
  for (const line of lines) {
    if (line.startsWith('⚙️') || line.startsWith('**Configuration Error**')) {
      continue; // Skip header
    } else if (line === '**How to fix:**') {
      currentSection = 'howToFix';
    } else if (line === '**Valid model names:**') {
      currentSection = 'validModels';
    } else if (currentSection === 'description') {
      description += line + ' ';
    } else if (currentSection === 'howToFix') {
      // Remove numbered prefix (e.g., "1. ", "2. ")
      const cleanLine = line.replace(/^\d+\.\s*/, '');
      if (cleanLine) {
        howToFix.push(cleanLine);
      }
    } else if (currentSection === 'validModels') {
      // Remove bullet prefix (e.g., "- ")
      const cleanLine = line.replace(/^-\s*/, '');
      if (cleanLine) {
        validModels.push(cleanLine);
      }
    }
  }
  
  return {
    description: description.trim(),
    howToFix,
    validModels,
  };
}

/**
 * ConfigErrorAlert component.
 *
 * Displays a prominent, dismissible alert for configuration errors.
 * Includes structured fix instructions and valid model names.
 *
 * @param props - Component props
 * @returns ConfigErrorAlert component
 *
 * @example
 * ```tsx
 * <ConfigErrorAlert
 *   errorMessage={error.message}
 *   onDismiss={() => setShowError(false)}
 * />
 * ```
 */
export function ConfigErrorAlert({ errorMessage, onDismiss }: ConfigErrorAlertProps) {
  const [expanded, setExpanded] = React.useState(true);
  const { description, howToFix, validModels } = parseErrorMessage(errorMessage);

  return (
    <Box sx={{ mb: 2 }}>
      <Alert
        severity="error"
        icon={<SettingsIcon />}
        sx={{
          borderLeft: 4,
          borderColor: 'error.main',
          '& .MuiAlert-message': {
            width: '100%',
          },
        }}
        action={
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <IconButton
              size="small"
              aria-label="toggle details"
              onClick={() => setExpanded(!expanded)}
              sx={{ color: 'inherit' }}
            >
              {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
            {onDismiss && (
              <IconButton
                size="small"
                aria-label="dismiss"
                onClick={onDismiss}
                sx={{ color: 'inherit' }}
              >
                <CloseIcon fontSize="small" />
              </IconButton>
            )}
          </Box>
        }
      >
        <AlertTitle sx={{ fontWeight: 600 }}>Configuration Error</AlertTitle>
        <Typography variant="body2" sx={{ mb: 1 }}>
          {description}
        </Typography>

        <Collapse in={expanded}>
          {howToFix.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                How to fix:
              </Typography>
              <List dense sx={{ pl: 0 }}>
                {howToFix.map((step, index) => (
                  <ListItem key={index} sx={{ py: 0.25, pl: 0 }}>
                    <ListItemText
                      primary={`${index + 1}. ${step}`}
                      primaryTypographyProps={{
                        variant: 'body2',
                        sx: { fontFamily: 'monospace', fontSize: '0.85rem' },
                      }}
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {validModels.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                Valid model names:
              </Typography>
              <Box
                sx={{
                  bgcolor: 'action.hover',
                  borderRadius: 1,
                  p: 1,
                  fontFamily: 'monospace',
                  fontSize: '0.8rem',
                }}
              >
                {validModels.map((model, index) => (
                  <Box key={index} sx={{ py: 0.25 }}>
                    • {model}
                  </Box>
                ))}
              </Box>
            </Box>
          )}
        </Collapse>
      </Alert>
    </Box>
  );
}

