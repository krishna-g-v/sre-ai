import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Drawer,
  IconButton,
  InputAdornment,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CloseIcon from "@mui/icons-material/Close";
import RefreshIcon from "@mui/icons-material/Refresh";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import BoltIcon from "@mui/icons-material/Bolt";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import type { Alert } from "../types/api";
import { severityColor, sourceColor, verdictColor } from "../components/alertColors";

const SOURCES = ["All", "Grafana", "Synthetics", "Prometheus", "Kubernetes", "CloudWatch", "Custom"];
const VERDICTS = ["All", "Real Incident", "Filtered Noise", "Investigating"];

export default function AlertsPage() {
  const location = useLocation();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("All");
  const [verdict, setVerdict] = useState("All");
  const [selected, setSelected] = useState<Alert | null>(null);
  const [retriaging, setRetriaging] = useState(false);

  const load = async () => {
    const data = await api.get<Alert[]>("/alerts");
    setAlerts(data);
    return data;
  };

  useEffect(() => {
    load().then((data) => {
      const wantedId = (location.state as { alertId?: string } | null)?.alertId;
      if (wantedId) {
        const match = data.find((a) => a.id === wantedId);
        if (match) setSelected(match);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    return alerts.filter((a) => {
      const matchesSearch =
        a.title.toLowerCase().includes(search.toLowerCase()) ||
        a.source.toLowerCase().includes(search.toLowerCase()) ||
        (a.triage_report?.summary ?? "").toLowerCase().includes(search.toLowerCase());
      const matchesSource = source === "All" || a.source === source;
      const matchesVerdict = verdict === "All" || a.verdict === verdict;
      return matchesSearch && matchesSource && matchesVerdict;
    });
  }, [alerts, search, source, verdict]);

  const handleReTriage = async () => {
    if (!selected) return;
    setRetriaging(true);
    try {
      const updated = await api.post<Alert>(`/alerts/${selected.id}/re-triage`);
      setSelected(updated);
      setAlerts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
    } finally {
      setRetriaging(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 2, sm: 3, lg: 4 } }}>
      <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px", mb: 3 }}>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ md: "center" }} gap={2}>
          <Box>
            <Typography variant="h6" fontWeight={700} display="flex" alignItems="center" gap={1}>
              <WarningAmberIcon color="warning" /> Live Alert Triage Feed
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Real-time alerts triaged and enriched by SRE Agents
            </Typography>
          </Box>
          <TextField
            size="small"
            placeholder="Search by title, source, or triage keyword..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            sx={{ minWidth: 320 }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
          />
        </Stack>

        <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={2} sx={{ mt: 2, pt: 2, borderTop: 1, borderColor: "divider" }}>
          <ToggleButtonGroup size="small" value={source} exclusive onChange={(_, v) => v && setSource(v)}>
            {SOURCES.map((s) => (
              <ToggleButton key={s} value={s} sx={{ textTransform: "none", fontSize: 12, px: 1.5 }}>
                {s}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <ToggleButtonGroup size="small" value={verdict} exclusive onChange={(_, v) => v && setVerdict(v)}>
            {VERDICTS.map((v) => (
              <ToggleButton key={v} value={v} sx={{ textTransform: "none", fontSize: 12, px: 1.5 }}>
                {v}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Stack>
      </Paper>

      <Stack spacing={2}>
        {filtered.map((alert) => (
          <Paper
            key={alert.id}
            variant="outlined"
            sx={{ p: 2.5, borderRadius: "10px", cursor: "pointer", "&:hover": { borderColor: "primary.main" } }}
            onClick={() => setSelected(alert)}
          >
            <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={1}>
              <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
                <Chip label={alert.source} size="small" sx={sourceColor(alert.source)} />
                <Typography variant="caption" color="text.secondary" fontFamily="monospace">
                  {new Date(alert.occurred_at).toLocaleString()}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  • Agent: {alert.agent_name}
                </Typography>
              </Stack>
              <Stack direction="row" gap={0.5}>
                <Chip label={alert.severity} size="small" sx={severityColor(alert.severity)} />
                <Chip label={alert.verdict} size="small" sx={verdictColor(alert.verdict)} />
              </Stack>
            </Stack>

            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 1 }}>
              <Typography variant="subtitle2" fontWeight={700}>
                {alert.title}
              </Typography>
              <ChevronRightIcon fontSize="small" color="disabled" />
            </Stack>

            {alert.triage_report && (
              <Paper variant="outlined" sx={{ mt: 1.5, p: 1.5, bgcolor: "action.hover" }}>
                <Typography variant="caption" fontWeight={700} display="flex" alignItems="center" gap={0.5} color="primary.main">
                  <BoltIcon sx={{ fontSize: 14 }} /> AI Agent Triage Analysis
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {alert.triage_report.summary}
                </Typography>
              </Paper>
            )}
          </Paper>
        ))}

        {filtered.length === 0 && (
          <Paper variant="outlined" sx={{ p: 6, textAlign: "center", borderRadius: "10px" }}>
            <CheckCircleIcon sx={{ fontSize: 44, color: "success.main", mb: 1 }} />
            <Typography variant="subtitle2" fontWeight={700}>
              No alerts found
            </Typography>
            <Typography variant="caption" color="text.secondary">
              No matching alerts for the selected filters. Use the Dashboard's quick-trigger simulator to test one.
            </Typography>
          </Paper>
        )}
      </Stack>

      <Drawer anchor="right" open={!!selected} onClose={() => setSelected(null)}>
        {selected && (
          <Box sx={{ width: { xs: "100vw", sm: 480 }, height: "100%", display: "flex", flexDirection: "column" }}>
            <Box sx={{ p: 3, bgcolor: "action.hover", borderBottom: 1, borderColor: "divider" }}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                <Box>
                  <Stack direction="row" gap={1} alignItems="center" sx={{ mb: 0.5 }}>
                    <Chip label={selected.source} size="small" color="primary" />
                    <Typography variant="caption" color="text.secondary" fontFamily="monospace">
                      {selected.agent_name}
                    </Typography>
                  </Stack>
                  <Typography variant="subtitle1" fontWeight={700}>
                    {selected.title}
                  </Typography>
                </Box>
                <IconButton size="small" onClick={() => setSelected(null)}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Stack>
            </Box>

            <Box sx={{ flex: 1, overflowY: "auto", p: 3 }}>
              <Stack direction="row" spacing={1.5} sx={{ mb: 3 }}>
                <Paper variant="outlined" sx={{ p: 1.5, flex: 1, borderRadius: "8px" }}>
                  <Typography variant="caption" color="text.secondary">
                    Verdict
                  </Typography>
                  <Typography variant="body2" fontWeight={700}>
                    {selected.verdict}
                  </Typography>
                </Paper>
                <Paper variant="outlined" sx={{ p: 1.5, flex: 1, borderRadius: "8px" }}>
                  <Typography variant="caption" color="text.secondary">
                    Severity
                  </Typography>
                  <Typography variant="body2" fontWeight={700}>
                    {selected.severity}
                  </Typography>
                </Paper>
                <Paper variant="outlined" sx={{ p: 1.5, flex: 1, borderRadius: "8px" }}>
                  <Typography variant="caption" color="text.secondary">
                    Est. Resolution
                  </Typography>
                  <Typography variant="body2" fontWeight={700} fontFamily="monospace">
                    {selected.triage_report?.estimated_resolution_minutes ?? 15}m
                  </Typography>
                </Paper>
              </Stack>

              {selected.canary_steps && (
                <Paper variant="outlined" sx={{ p: 2, mb: 3, borderRadius: "8px" }}>
                  <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 1 }}>
                    Canary Execution Steps
                  </Typography>
                  <Stack spacing={1}>
                    {selected.canary_steps.map((step, idx) => (
                      <Stack
                        key={idx}
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        sx={{
                          p: 1,
                          borderRadius: "8px",
                          bgcolor: step.status === "success" ? "action.hover" : "#fbdfdb",
                        }}
                      >
                        <Typography variant="caption" fontWeight={600}>
                          {idx + 1}. {step.name}
                        </Typography>
                        <Typography variant="caption" fontFamily="monospace">
                          {step.durationMs}ms · {step.status}
                        </Typography>
                      </Stack>
                    ))}
                  </Stack>
                  {selected.canary_error_msg && (
                    <Typography variant="caption" color="error.main" sx={{ display: "block", mt: 1 }}>
                      {selected.canary_error_msg}
                    </Typography>
                  )}
                </Paper>
              )}

              {selected.triage_report && (
                <Stack spacing={2} sx={{ mb: 3 }}>
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: "8px", bgcolor: "action.hover" }}>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                      Executive Triage Analysis
                    </Typography>
                    <Typography variant="body2">{selected.triage_report.summary}</Typography>
                  </Paper>

                  <Paper variant="outlined" sx={{ p: 2, borderRadius: "8px" }}>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                      Root Cause Hypothesis
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selected.triage_report.root_cause_hypothesis}
                    </Typography>
                  </Paper>

                  <Paper variant="outlined" sx={{ p: 2, borderRadius: "8px" }}>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                      Step-by-Step Remediation (advisory — nothing here is executed automatically)
                    </Typography>
                    <Stack spacing={1}>
                      {selected.triage_report.step_by_step_remediation.map((step, idx) => (
                        <Typography key={idx} variant="body2" sx={{ display: "flex", gap: 1 }}>
                          <Box component="span" sx={{ fontWeight: 700, color: "primary.main" }}>
                            {idx + 1}.
                          </Box>
                          {step}
                        </Typography>
                      ))}
                    </Stack>
                  </Paper>
                </Stack>
              )}

              <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 1 }}>
                Raw Alert Payload
              </Typography>
              <Box
                component="pre"
                sx={{
                  bgcolor: "#0f1720",
                  color: "#8fcf77",
                  p: 2,
                  borderRadius: "8px",
                  fontSize: 11,
                  overflowX: "auto",
                  maxHeight: 200,
                }}
              >
                {JSON.stringify(selected.raw_payload, null, 2)}
              </Box>
            </Box>

            <Stack direction="row" justifyContent="space-between" sx={{ p: 2, borderTop: 1, borderColor: "divider" }}>
              <Button startIcon={<RefreshIcon />} size="small" disabled={retriaging} onClick={handleReTriage}>
                {retriaging ? "Re-triaging…" : "Re-Triage"}
              </Button>
              <Button variant="contained" size="small" onClick={() => setSelected(null)}>
                Close
              </Button>
            </Stack>
          </Box>
        )}
      </Drawer>
    </Box>
  );
}
