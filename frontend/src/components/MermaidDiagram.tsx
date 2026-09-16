import {
  useEffect,
  useId,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { Box, Dialog, IconButton, Stack, Tooltip, Typography, useTheme } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import OpenInFullIcon from "@mui/icons-material/OpenInFull";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ZoomInIcon from "@mui/icons-material/ZoomIn";
import ZoomOutIcon from "@mui/icons-material/ZoomOut";

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

const MIN_SCALE = 0.25;
const MAX_SCALE = 4;
const ZOOM_STEP = 0.25;

function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

const FIT_PADDING = 0.92; // small margin so the diagram's edges aren't flush against the viewport

/** Pannable/zoomable stage for the enlarged modal view — a real topology diagram can be
 * far too big to read at chat-bubble width, and the fullscreen dialog alone doesn't help
 * once a diagram is *also* too big for a single screen. Opens fit-to-viewport (not 1:1 —
 * found live that a small diagram in a big fullscreen dialog just renders tiny in the
 * middle, which defeats the point), then scroll to zoom, drag to pan. No pan-zoom library
 * pulled in for this — the interaction is simple enough (two numbers: scale and a
 * translate offset) that a dependency would cost more than it saves. */
function PanZoomStage({ svg }: { svg: string | null }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [fitScale, setFitScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragOrigin = useRef<{ startX: number; startY: number; base: { x: number; y: number } } | null>(null);
  const svgSize = useRef<{ width: number; height: number } | null>(null);
  // Mirrors `fitScale` state for the resize observer below, which is intentionally set
  // up once (empty deps) rather than re-subscribed on every fit change — a ref avoids
  // reading a stale `fitScale` from that effect's original closure.
  const fitScaleRef = useRef(1);

  const computeFit = (): number => {
    const viewport = viewportRef.current;
    if (!viewport || !svgSize.current || svgSize.current.width <= 0 || svgSize.current.height <= 0) return 1;
    const viewportRect = viewport.getBoundingClientRect();
    return clampScale(
      Math.min(
        (viewportRect.width * FIT_PADDING) / svgSize.current.width,
        (viewportRect.height * FIT_PADDING) / svgSize.current.height,
      ),
    );
  };

  useEffect(() => {
    if (!stageRef.current || !svg) return;
    stageRef.current.innerHTML = svg;
    // Mermaid always sets a viewBox — read the diagram's true content size from it
    // rather than getBoundingClientRect(), which would reflect the *current* CSS
    // transform scale, not the diagram's natural size, once a transform is applied.
    const svgEl = stageRef.current.querySelector("svg");
    const viewBox = svgEl?.viewBox.baseVal;
    if (svgEl && viewBox && viewBox.width > 0 && viewBox.height > 0) {
      svgSize.current = { width: viewBox.width, height: viewBox.height };
      // Mermaid's own markup sets width="100%" + a max-width style, meant for it to
      // shrink-to-fit an ordinary block container. Inside this flex-centered viewport
      // that combination resolves to an unpredictable (and, found live, much too
      // small) size — pin it to its true natural pixel size instead, so our own
      // `transform: scale(...)` below is the only thing controlling its displayed size.
      svgEl.setAttribute("width", String(viewBox.width));
      svgEl.setAttribute("height", String(viewBox.height));
      svgEl.style.maxWidth = "none";
    } else {
      svgSize.current = null;
    }

    const fit = computeFit();
    fitScaleRef.current = fit;
    setFitScale(fit);
    setScale(fit);
    setTranslate({ x: 0, y: 0 });
  }, [svg]);

  // Re-fit if the dialog/viewport is resized while a diagram the user hasn't manually
  // zoomed is showing — a manual zoom is left alone rather than being overridden.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const observer = new ResizeObserver(() => {
      const newFit = computeFit();
      setScale((current) => (Math.abs(current - fitScaleRef.current) < 0.001 ? newFit : current));
      fitScaleRef.current = newFit;
      setFitScale(newFit);
    });
    observer.observe(viewport);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onWheel = (e: ReactWheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    setScale((s) => clampScale(s - e.deltaY * 0.0015 * s));
  };

  const onMouseDown = (e: ReactMouseEvent<HTMLDivElement>) => {
    dragOrigin.current = { startX: e.clientX, startY: e.clientY, base: translate };
    setIsDragging(true);
  };
  const onMouseMove = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (!dragOrigin.current) return;
    const { startX, startY, base } = dragOrigin.current;
    setTranslate({ x: base.x + (e.clientX - startX), y: base.y + (e.clientY - startY) });
  };
  const endDrag = () => {
    dragOrigin.current = null;
    setIsDragging(false);
  };

  const zoomBy = (delta: number) => setScale((s) => clampScale(s + delta));
  const reset = () => {
    setScale(fitScale);
    setTranslate({ x: 0, y: 0 });
  };

  return (
    <Box sx={{ position: "relative", width: "100%", height: "100%", overflow: "hidden", bgcolor: "background.default" }}>
      {svg ? (
        <Box
          ref={viewportRef}
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={endDrag}
          onMouseLeave={endDrag}
          sx={{
            width: "100%",
            height: "100%",
            cursor: isDragging ? "grabbing" : "grab",
            touchAction: "none",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Box
            ref={stageRef}
            sx={{
              transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
              transition: isDragging ? "none" : "transform 0.05s linear",
              "& svg": { display: "block" },
            }}
          />
        </Box>
      ) : (
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
          <Typography variant="body2" color="text.secondary">
            Rendering diagram…
          </Typography>
        </Box>
      )}

      <Stack
        direction="row"
        spacing={0.5}
        sx={{ position: "absolute", bottom: 16, right: 16, bgcolor: "background.paper", borderRadius: "10px", p: 0.5, boxShadow: 3 }}
      >
        <Tooltip title="Zoom out">
          <IconButton size="small" onClick={() => zoomBy(-ZOOM_STEP)}>
            <ZoomOutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Fit to screen">
          <IconButton size="small" onClick={reset}>
            <RestartAltIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Zoom in">
          <IconButton size="small" onClick={() => zoomBy(ZOOM_STEP)}>
            <ZoomInIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
    </Box>
  );
}

/** Renders a Mermaid diagram from raw diagram source (the ` ```mermaid ` fence's body,
 * fence markers already stripped by MarkdownContent's code renderer). Falls back to the
 * raw source in a plain code block on a render error — found worth doing explicitly
 * rather than a blank space, since a subtle diagram-generation bug should be visible and
 * debuggable, not silently swallowed (same "never hide a failure" principle the backend
 * tools use for a degraded/failed AWS call).
 *
 * A real VPC topology can be far too big to read at chat-bubble width (found testing
 * against a real account — docs/11-network-topology-visualization.md §9): the inline
 * preview is capped and scrollable, with a hover overlay / corner button to open a
 * fullscreen, pannable/zoomable modal for actually reading a large diagram. */
export default function MermaidDiagram({ code }: Props) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const previewRef = useRef<HTMLDivElement>(null);
  const [previewSvg, setPreviewSvg] = useState<string | null>(null);
  const [modalSvg, setModalSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
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
        if (cancelled) return;
        setPreviewSvg(result.svg);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not render diagram.");
      });

    return () => {
      cancelled = true;
    };
  }, [code, isDark, diagramId]);

  useEffect(() => {
    if (previewRef.current && previewSvg) previewRef.current.innerHTML = previewSvg;
  }, [previewSvg]);

  // Rendered separately from the preview (own mermaid id) rather than reusing the same
  // SVG string in two places at once — both would be mounted simultaneously while the
  // modal is open (the Dialog portals over the page, it doesn't unmount what's behind
  // it), and mermaid's internal ids (arrowhead markers, etc.) would collide if the exact
  // same markup existed twice in the document at once.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    loadMermaid()
      .then(({ default: mermaid }) => {
        mermaid.initialize({ startOnLoad: false, theme: isDark ? "dark" : "default", securityLevel: "strict" });
        return mermaid.render(`${diagramId}-modal`, code);
      })
      .then((result) => {
        if (!cancelled) setModalSvg(result.svg);
      })
      .catch(() => {
        // The preview's own effect already surfaced a render error, if there is one —
        // nothing additional to show here.
      });
    return () => {
      cancelled = true;
    };
  }, [open, code, isDark, diagramId]);

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

  return (
    <>
      <Box
        onClick={() => setOpen(true)}
        role="button"
        aria-label="Enlarge diagram"
        sx={{
          position: "relative",
          my: 1,
          maxHeight: 420,
          overflow: "auto",
          borderRadius: "8px",
          border: 1,
          borderColor: "divider",
          cursor: "zoom-in",
          "&:hover .diagram-hover-overlay": { opacity: 1 },
          "& svg": { maxWidth: "100%", display: "block" },
        }}
      >
        <Box ref={previewRef} sx={{ p: 1 }} />

        <Box
          className="diagram-hover-overlay"
          sx={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            bgcolor: "rgba(0, 0, 0, 0.45)",
            color: "#fff",
            opacity: 0,
            transition: "opacity 0.15s ease",
            pointerEvents: "none",
          }}
        >
          <Stack direction="row" spacing={1} alignItems="center">
            <OpenInFullIcon fontSize="small" />
            <Typography variant="body2">Click to enlarge</Typography>
          </Stack>
        </Box>

        <Tooltip title="Enlarge diagram">
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(true);
            }}
            sx={{
              position: "absolute",
              top: 6,
              right: 6,
              bgcolor: "background.paper",
              boxShadow: 1,
              "&:hover": { bgcolor: "background.paper" },
            }}
          >
            <OpenInFullIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      <Dialog
        fullScreen
        open={open}
        onClose={() => setOpen(false)}
        slotProps={{ paper: { sx: { display: "flex", flexDirection: "column" } } }}
      >
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          sx={{ px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}
        >
          <Typography variant="subtitle1" fontWeight={600}>
            Network diagram
          </Typography>
          <Tooltip title="Close">
            <IconButton onClick={() => setOpen(false)}>
              <CloseIcon />
            </IconButton>
          </Tooltip>
        </Stack>
        <Box sx={{ flex: 1, minHeight: 0 }}>
          <PanZoomStage svg={modalSvg} />
        </Box>
      </Dialog>
    </>
  );
}
