/**
 * ErrorBoundary component.
 *
 * Catches and displays errors in child components.
 * Supports both static fallback and render prop pattern.
 */

"use client";

import React, { Component, ReactNode } from "react";
import { Box, Typography, Button, Paper } from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";

/** Props for fallback render function */
export interface FallbackProps {
  error: Error;
  resetError: () => void;
}

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Static fallback element */
  fallback?: ReactNode;
  /** Render prop for fallback with error access */
  fallbackRender?: (props: FallbackProps) => ReactNode;
  /** Called when error is caught */
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
  /** Called when error is reset */
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error boundary component.
 *
 * Catches errors in child components and displays a fallback UI.
 * Supports both static fallback and render prop for dynamic fallback with error access.
 *
 * @example
 * // Static fallback
 * <ErrorBoundary fallback={<div>Something went wrong</div>}>
 *   <MyComponent />
 * </ErrorBoundary>
 *
 * @example
 * // Render prop with error access
 * <ErrorBoundary
 *   fallbackRender={({ error, resetError }) => (
 *     <div>
 *       <p>Error: {error.message}</p>
 *       <button onClick={resetError}>Retry</button>
 *     </div>
 *   )}
 * >
 *   <MyComponent />
 * </ErrorBoundary>
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleReset = (): void => {
    this.props.onReset?.();
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      // Render prop takes priority
      if (this.props.fallbackRender) {
        return this.props.fallbackRender({
          error: this.state.error,
          resetError: this.handleReset,
        });
      }

      // Static fallback
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Default fallback UI
      return (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            p: 3,
          }}
        >
          <Paper
            elevation={3}
            sx={{
              p: 4,
              maxWidth: 500,
              textAlign: "center",
            }}
          >
            <ErrorOutlineIcon
              sx={{ fontSize: 64, color: "error.main", mb: 2 }}
            />
            <Typography variant="h5" gutterBottom>
              Something went wrong
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {this.state.error?.message || "An unexpected error occurred"}
            </Typography>
            <Button variant="contained" onClick={this.handleReset}>
              Try Again
            </Button>
          </Paper>
        </Box>
      );
    }

    return this.props.children;
  }
}

