import type { SxProps } from "@mui/material";
import type { AgentCategory, NoiseVerdict, SeverityLevel } from "../types/api";

const SOURCE_COLORS: Record<AgentCategory, { bg: string; color: string }> = {
  Grafana: { bg: "#fde8d7", color: "#9a4a12" },
  Synthetics: { bg: "#dcf5e6", color: "#166a3f" },
  Prometheus: { bg: "#fdf0d5", color: "#8a5a06" },
  Kubernetes: { bg: "#dcecfd", color: "#0d5aa8" },
  CloudWatch: { bg: "#dcecfd", color: "#0d5aa8" },
  Custom: { bg: "#eee", color: "#444" },
};

export function sourceColor(source: AgentCategory): SxProps {
  const c = SOURCE_COLORS[source] ?? SOURCE_COLORS.Custom;
  return { bgcolor: c.bg, color: c.color, fontWeight: 700 };
}

export function severityColor(severity: SeverityLevel): SxProps {
  if (severity === "Critical") return { bgcolor: "#fbdfdb", color: "#9a2f22", fontWeight: 700 };
  if (severity === "Warning") return { bgcolor: "#fdf0d5", color: "#8a5a06", fontWeight: 700 };
  return { bgcolor: "action.hover", color: "text.secondary", fontWeight: 700 };
}

export function verdictColor(verdict: NoiseVerdict): SxProps {
  if (verdict === "Real Incident") return { bgcolor: "#fbdfdb", color: "#9a2f22", fontWeight: 700 };
  if (verdict === "Filtered Noise") return { bgcolor: "#dcf5e6", color: "#166a3f", fontWeight: 700 };
  return { bgcolor: "action.hover", color: "text.secondary", fontWeight: 700 };
}
