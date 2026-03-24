/**
 * Material UI theme configuration.
 *
 * Defines light and dark mode themes with custom colors, typography,
 * and component overrides for the chat UI.
 */

import { createTheme, ThemeOptions } from "@mui/material/styles";

// Color palette for light and dark modes
const lightPalette = {
  primary: {
    main: "#1976d2",
    light: "#42a5f5",
    dark: "#1565c0",
    contrastText: "#fff",
  },
  secondary: {
    main: "#9c27b0",
    light: "#ba68c8",
    dark: "#7b1fa2",
    contrastText: "#fff",
  },
  background: {
    default: "#f5f5f5",
    paper: "#ffffff",
  },
  text: {
    primary: "#212121",
    secondary: "#757575",
  },
};

const darkPalette = {
  primary: {
    main: "#90caf9",
    light: "#e3f2fd",
    dark: "#42a5f5",
    contrastText: "#000",
  },
  secondary: {
    main: "#ce93d8",
    light: "#f3e5f5",
    dark: "#ab47bc",
    contrastText: "#000",
  },
  background: {
    default: "#121212",
    paper: "#1e1e1e",
  },
  text: {
    primary: "#ffffff",
    secondary: "#b0b0b0",
  },
};

// Common theme options
const commonOptions: ThemeOptions = {
  typography: {
    fontFamily: [
      "-apple-system",
      "BlinkMacSystemFont",
      '"Segoe UI"',
      "Roboto",
      '"Helvetica Neue"',
      "Arial",
      "sans-serif",
    ].join(","),
    h1: {
      fontSize: "2.5rem",
      fontWeight: 600,
    },
    h2: {
      fontSize: "2rem",
      fontWeight: 600,
    },
    h3: {
      fontSize: "1.75rem",
      fontWeight: 600,
    },
    h4: {
      fontSize: "1.5rem",
      fontWeight: 600,
    },
    h5: {
      fontSize: "1.25rem",
      fontWeight: 600,
    },
    h6: {
      fontSize: "1rem",
      fontWeight: 600,
    },
    body1: {
      fontSize: "1rem",
      lineHeight: 1.5,
    },
    body2: {
      fontSize: "0.875rem",
      lineHeight: 1.43,
    },
  },
  shape: {
    borderRadius: 8,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: "none",
          fontWeight: 500,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
        },
      },
    },
  },
};

/**
 * Create light theme.
 */
export const lightTheme = createTheme({
  ...commonOptions,
  palette: {
    mode: "light",
    ...lightPalette,
  },
});

/**
 * Create dark theme.
 */
export const darkTheme = createTheme({
  ...commonOptions,
  palette: {
    mode: "dark",
    ...darkPalette,
  },
});

/**
 * Get theme based on mode.
 */
export const getTheme = (mode: "light" | "dark") => {
  return mode === "light" ? lightTheme : darkTheme;
};

