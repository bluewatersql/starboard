/**
 * Theme provider component with dark mode support.
 *
 * Wraps the app with Material UI theme provider and provides
 * a context for toggling between light and dark modes.
 */

"use client";

import React, { createContext, useContext, useMemo, useState } from "react";
import { ThemeProvider as MuiThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import { getTheme } from "./theme";

type ThemeMode = "light" | "dark";

interface ThemeContextType {
  mode: ThemeMode;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

/**
 * Hook to access theme context.
 */
export const useThemeMode = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useThemeMode must be used within ThemeProvider");
  }
  return context;
};

interface ThemeProviderProps {
  children: React.ReactNode;
}

/**
 * Theme provider component.
 *
 * Provides Material UI theme and dark mode toggle functionality.
 *
 * @param props - Component props
 * @returns Theme provider component
 *
 * @example
 * ```tsx
 * <ThemeProvider>
 *   <App />
 * </ThemeProvider>
 * ```
 */
export function ThemeProvider({ children }: ThemeProviderProps) {
  // Always start with light mode to ensure server/client match
  // Will be updated on client after hydration
  const [mode, setMode] = useState<ThemeMode>("light");
  const [mounted, setMounted] = useState(false);

  // Update theme from localStorage/system preference after mount (client-side only)
  React.useEffect(() => {
    setMounted(true);
    
    const stored = localStorage.getItem("theme-mode");
    if (stored === "light" || stored === "dark") {
      setMode(stored);
    } else {
      // Check system preference
      if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
        setMode("dark");
      }
    }
  }, []);

  // Sync theme mode with document root for CSS variables
  React.useEffect(() => {
    if (!mounted) return;
    
    const root = document.documentElement;
    
    if (mode === "dark") {
      root.classList.add("dark");
      root.setAttribute("data-theme", "dark");
    } else {
      root.classList.remove("dark");
      root.setAttribute("data-theme", "light");
    }
  }, [mode, mounted]);

  const toggleTheme = () => {
    setMode((prevMode) => {
      const newMode = prevMode === "light" ? "dark" : "light";
      localStorage.setItem("theme-mode", newMode);
      return newMode;
    });
  };

  const theme = useMemo(() => getTheme(mode), [mode]);

  const contextValue = useMemo(
    () => ({
      mode,
      toggleTheme,
    }),
    [mode]
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      <MuiThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MuiThemeProvider>
    </ThemeContext.Provider>
  );
}

