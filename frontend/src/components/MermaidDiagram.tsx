import { useEffect, useId, useRef, useState } from "react";
import { Box, Typography, useTheme } from "@mui/material";

interface Props {
  code: string;
}

// docs/11-network-topology-visualization.md §7 — mermaid is only ever needed once a chat
// answer actually contains a ```mermaid block (currently: VPC topology answers), so it's
// dynamically imported rather than added to the main bundle every user pays for.
let mermaidModulePromise: Promise<typeof import("mermaid")> | null = null;

function loadMermaid() {
  mermaidModulePromise ??= import("mermaid");
  return mermaidModulePromise;
}

/** Renders a Mermaid diagram from raw diagram source (the ` ```mermaid ` fence's body,
 * fence markers already stripped by MarkdownContent's code renderer). Falls back to the
 * raw source in a plain code block on a render error — found worth doing explicitly
 * rather than a blank space, since a subtle diagram-generation bug should be visible and
 * debuggable, not silently swallowed (same "never hide a failure" principle the backend
 * tools use for a degraded/failed AWS call). */
export default function MermaidDiagram({ code }: Props) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  // useId() includes colons, which mermaid's id-based DOM/CSS selectors don't accept.
  const diagramId = `mermaid-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;

  useEffect(() => {
    let cancelled = false;
    setError(null);

    loadMermaid()
      .then(({ default: mermaid }) => {
        mermaid.initialize({
          startOnLoad: false,
          theme: isDark ? "dark" : "default",
          securityLevel: "strict", // sanitizes SVG output — diagram text ultimately traces back to AWS resource tags
        });
        return mermaid.render(diagramId, code);
      })
      .then((result) => {
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = result.svg;
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not render diagram.");
      });

    return () => {
      cancelled = true;
    };
  }, [code, isDark, diagramId]);

  if (error) {
    return (
      <Box sx={{ my: 1 }}>
        <Typography variant="body2" color="error" sx={{ mb: 0.5 }}>
          Could not render diagram: {error}
        </Typography>
        <Box
          component="pre"
          sx={{
            bgcolor: "action.hover",
            p: 1.5,
            borderRadius: "8px",
            overflowX: "auto",
            fontSize: 12.5,
            fontFamily: "monospace",
          }}
        >
          <code>{code}</code>
        </Box>
      </Box>
    );
  }

  return <Box ref={containerRef} sx={{ my: 1, overflowX: "auto", "& svg": { maxWidth: "100%" } }} />;
}
