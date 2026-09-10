import { createTheme, type ThemeOptions } from "@mui/material/styles";

/**
 * Color tokens — docs/04-frontend-ui.md §2.
 * Primary: #1474d4 (blue), #06b6ed (cyan). Soft semantic colors for status, not
 * saturated alarm colors — urgency should come from icon/label/position too.
 */
const semanticLight = {
  success: "#78b75e",
  warning: "#e8b04b",
  error: "#e07a6b",
  info: "#06b6ed",
};

const semanticDark = {
  success: "#8fcf77",
  warning: "#f0c268",
  error: "#eb9385",
  info: "#06b6ed",
};

function buildTheme(mode: "light" | "dark"): ThemeOptions {
  const isDark = mode === "dark";
  return {
    palette: {
      mode,
      primary: { main: isDark ? "#4a9ce8" : "#1474d4" },
      secondary: { main: "#06b6ed" },
      background: {
        // Dark mode already gives the page (#0f1720) and cards (#182430) distinct
        // shades so surfaces have depth against the page. Light mode used to be pure
        // #ffffff for both, so cards had zero visual separation from the page except
        // their border. #f7f9fc mirrors the same relationship: a barely-there cool-gray
        // page background, with cards staying pure white to stand out against it.
        default: isDark ? "#0f1720" : "#f7f9fc",
        paper: isDark ? "#182430" : "#ffffff",
      },
      success: { main: isDark ? semanticDark.success : semanticLight.success },
      warning: { main: isDark ? semanticDark.warning : semanticLight.warning },
      error: { main: isDark ? semanticDark.error : semanticLight.error },
      info: { main: isDark ? semanticDark.info : semanticLight.info },
    },
    // Kept small deliberately — MUI's sx `borderRadius` shorthand multiplies numeric
    // values by this base (e.g. `borderRadius: 3` => 3 * shape.borderRadius), so a large
    // base here silently produces very round corners everywhere. Component sx overrides
    // in this codebase use explicit "8px"/"10px" strings instead of numeric multiples for
    // exactly this reason — this value only governs components with no explicit override.
    shape: { borderRadius: 8 },
    typography: {
      fontFamily: [
        "Inter",
        "-apple-system",
        "BlinkMacSystemFont",
        "Segoe UI",
        "Roboto",
        "Helvetica Neue",
        "Arial",
        "sans-serif",
      ].join(","),
    },
    components: {
      MuiAppBar: {
        styleOverrides: {
          root: { boxShadow: "none", borderBottom: "1px solid rgba(128,128,128,0.15)" },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: "none" },
        },
      },
    },
  };
}

export const lightTheme = createTheme(buildTheme("light"));
export const darkTheme = createTheme(buildTheme("dark"));
