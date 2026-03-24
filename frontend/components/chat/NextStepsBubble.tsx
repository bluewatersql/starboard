/**
 * NextStepsBubble component.
 *
 * Renders next steps/suggested actions as a prominent, separate UI element
 * below the report to make them more obvious and actionable.
 * 
 * Enhanced in Phase 2 with:
 * - Fade-in animation on appear
 * - First option emphasized as primary action
 * - Action type badges (Continue, Expert, Action)
 * - Better visual hierarchy and call-to-action styling
 */

"use client";

import React, { useState } from "react";
import { Box, Paper, Typography, Button, Chip } from "@mui/material";
import { useTheme, alpha } from "@mui/material/styles";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import LightbulbIcon from "@mui/icons-material/Lightbulb";
import RouteIcon from "@mui/icons-material/Route";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import LoopIcon from "@mui/icons-material/Loop";
import type { NextStepOption } from "@/lib/types/api";

interface NextStepsBubbleProps {
  options: NextStepOption[];
  onSelectOption: (option: NextStepOption) => void;
  disabled?: boolean;
}

/**
 * Get icon and color config for action type.
 */
function getActionTypeConfig(actionType?: string) {
  switch (actionType) {
    case "route":
      return { 
        icon: <RouteIcon sx={{ fontSize: "0.875rem" }} />, 
        label: "Expert", 
        color: "secondary" as const,  // Changed from "info" (blue) to "secondary" (purple) for better contrast
        tooltip: "Hand off to specialist agent"
      };
    case "tool_call":
      return { 
        icon: <PlayArrowIcon sx={{ fontSize: "0.875rem" }} />, 
        label: "Action", 
        color: "warning" as const,
        tooltip: "Execute specific action"
      };
    case "continue":
    default:
      return { 
        icon: <LoopIcon sx={{ fontSize: "0.875rem" }} />, 
        label: "Continue", 
        color: "success" as const,
        tooltip: "Continue conversation"
      };
  }
}

/**
 * Action type chip component.
 */
function ActionTypeChip({ actionType }: { actionType?: string }) {
  const config = getActionTypeConfig(actionType);
  
  return (
    <Chip
      icon={config.icon}
      label={config.label}
      size="small"
      color={config.color}
      variant="filled"  // Changed from "outlined" to "filled" for better contrast and visibility
      sx={{ 
        height: 24,
        fontWeight: 600,  // Increased from default for better readability
        "& .MuiChip-icon": { 
          fontSize: "0.875rem",
          marginLeft: "4px"
        },
        "& .MuiChip-label": {
          px: 1,
          fontSize: "0.75rem",
        }
      }}
    />
  );
}

/**
 * Next steps bubble component.
 *
 * Displays suggested next actions in a prominent card format,
 * separate from the main report for better visibility.
 *
 * @param props - Component props
 * @returns Next steps bubble component
 *
 * @example
 * ```tsx
 * <NextStepsBubble
 *   options={nextSteps}
 *   onSelectOption={handleSelect}
 * />
 * ```
 */
export function NextStepsBubble({ options, onSelectOption, disabled = false }: NextStepsBubbleProps) {
  const theme = useTheme();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (!options || options.length === 0) {
    return null;
  }

  const handleOptionClick = async (option: NextStepOption) => {
    // Don't allow clicks if disabled or already selected an option
    if (disabled || selectedId) return;
    
    setSelectedId(option.id);
    
    try {
      await onSelectOption(option);
      // Successfully sent - selectedId remains set, showing checkmark
    } catch (error) {
      console.error("[NextStepsBubble] Option selection failed:", error);
      // Reset selection on error so user can retry
      setSelectedId(null);
    }
  };

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "flex-start",
        mb: 3,
        px: 2,
        // Fade-in animation
        animation: "fadeSlideIn 0.4s ease-out",
        "@keyframes fadeSlideIn": {
          from: { 
            opacity: 0, 
            transform: "translateY(12px)" 
          },
          to: { 
            opacity: 1, 
            transform: "translateY(0)" 
          },
        },
      }}
    >
      <Box
        sx={{
          maxWidth: "90%",
          width: "100%",
        }}
      >
        <Paper
          elevation={4}
          sx={{
            p: 3,
            bgcolor: theme.palette.mode === "dark"
              ? alpha(theme.palette.success.main, 0.08)
              : alpha(theme.palette.success.main, 0.04),
            borderRadius: 3,
            borderLeft: `5px solid ${theme.palette.success.main}`,
            transition: "all 0.2s ease",
            "&:hover": {
              boxShadow: theme.shadows[6],
            },
          }}
        >
          {/* Header */}
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1.5,
              mb: 2.5,
            }}
          >
            <Box
              sx={{
                width: 40,
                height: 40,
                borderRadius: "50%",
                bgcolor: alpha(theme.palette.success.main, 0.15),
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <LightbulbIcon 
                sx={{ 
                  color: "success.main",
                  fontSize: "1.5rem",
                }} 
              />
            </Box>
            <Box sx={{ flex: 1 }}>
              <Typography
                variant="h6"
                sx={{
                  fontWeight: 700,
                  color: "success.main",
                  fontSize: "1.15rem",
                  lineHeight: 1.2,
                }}
              >
                What would you like to do next?
              </Typography>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                  display: "block",
                }}
              >
                Select an option to continue
              </Typography>
            </Box>
            <Chip
              label={`${options.length} option${options.length > 1 ? 's' : ''}`}
              size="small"
              sx={{
                bgcolor: alpha(theme.palette.success.main, 0.15),
                color: "success.main",
                fontWeight: 600,
                fontSize: "0.75rem",
              }}
            />
          </Box>

          {/* Options */}
          <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
            {options.map((option, index) => {
              const isFirst = index === 0;
              const isSelected = selectedId === option.id;
              const isDisabled = disabled || selectedId !== null;
              
              return (
                <Button
                  key={option.id || option.number}
                  variant={isFirst ? "contained" : "outlined"}
                  color="success"
                  onClick={() => handleOptionClick(option)}
                  disabled={isDisabled}
                  sx={{
                    justifyContent: "flex-start",
                    textAlign: "left",
                    py: 1.5,
                    px: 2,
                    borderRadius: 2,
                    transition: "all 0.2s ease",
                    // Selected state styling
                    ...(isSelected && {
                      bgcolor: alpha(theme.palette.success.main, 0.3),
                      borderColor: "success.dark",
                      opacity: 0.9,
                    }),
                    // First option is emphasized
                    ...(isFirst ? {
                      boxShadow: 2,
                      "&:hover": {
                        boxShadow: 4,
                      },
                      // Override disabled styling for first option - keep the look but no hover
                      "&.Mui-disabled": {
                        bgcolor: !isSelected ? "success.main" : undefined,
                        color: !isSelected ? "white" : undefined,
                        opacity: 0.7,
                      },
                    } : {
                      borderColor: alpha(theme.palette.success.main, 0.4),
                      bgcolor: theme.palette.mode === "dark"
                        ? alpha(theme.palette.common.white, 0.02)
                        : alpha(theme.palette.common.white, 0.7),
                      "&:hover": {
                        borderColor: "success.main",
                        bgcolor: alpha(theme.palette.success.main, 0.08),
                      },
                      // Override disabled styling for other options - keep outlined look
                      "&.Mui-disabled": {
                        borderColor: !isSelected ? alpha(theme.palette.success.main, 0.3) : undefined,
                        opacity: 0.6,
                      },
                    }),
                    "& .MuiButton-startIcon": {
                      marginRight: 1.5,
                    },
                  }}
                >
                  {/* Option number badge */}
                  <Box
                    sx={{
                      width: 28,
                      height: 28,
                      borderRadius: "50%",
                      bgcolor: isFirst ? "white" : "success.main",
                      color: isFirst ? "success.main" : "white",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "0.875rem",
                      fontWeight: 700,
                      mr: 1.5,
                      flexShrink: 0,
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
                        lineHeight: 1.3,
                        color: isFirst ? "inherit" : "text.primary",
                      }}
                    >
                      {option.title || option.description}
                    </Typography>
                    {option.title && option.description && option.title !== option.description && (
                      <Typography
                        variant="body2"
                        sx={{
                          opacity: 0.85,
                          lineHeight: 1.3,
                          mt: 0.25,
                          color: isFirst ? "inherit" : "text.secondary",
                        }}
                      >
                        {option.description}
                      </Typography>
                    )}
                  </Box>

                  {/* Action type chip */}
                  <Box sx={{ ml: 1.5, flexShrink: 0 }}>
                    <ActionTypeChip actionType={option.action_type} />
                  </Box>

                  {/* Arrow or Checkmark (selected) */}
                  {isSelected ? (
                    <CheckCircleIcon 
                      sx={{ 
                        ml: 1,
                        fontSize: 20,
                        color: "success.main",
                        animation: "fadeIn 200ms ease-in",
                        "@keyframes fadeIn": {
                          from: { opacity: 0 },
                          to: { opacity: 1 },
                        },
                      }} 
                    />
                  ) : (
                    <ArrowForwardIcon 
                      sx={{ 
                        ml: 1, 
                        opacity: 0.6,
                        flexShrink: 0,
                        color: isFirst ? "inherit" : "text.secondary",
                      }} 
                    />
                  )}
                </Button>
              );
            })}
          </Box>

          {/* Helper text */}
          <Typography
            variant="caption"
            sx={{
              display: "block",
              mt: 2.5,
              color: "text.secondary",
              textAlign: "center",
              opacity: 0.7,
            }}
          >
            Click an option or type your own question below
          </Typography>
        </Paper>
      </Box>
    </Box>
  );
}
