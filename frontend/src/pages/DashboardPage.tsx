import { useEffect, useState, useCallback } from "react";
import {
  Box,
  Button,
  Card,
  CardActionArea,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import BoltIcon from "@mui/icons-material/Bolt";
import TerminalIcon from "@mui/icons-material/Terminal";
import ArrowOutwardIcon from "@mui/icons-material/ArrowOutward";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import LocalFireDepartmentIcon from "@mui/icons-material/LocalFireDepartment";
import FilterAltIcon from "@mui/icons-material/FilterAlt";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Agent, Alert, DashboardStats } from "../types/api";
import { severityColor, sourceColor, verdictColor } from "../components/alertColors";

const QUICK_TRIGGERS: { type: string; label: string; sub: string }[] = [
  { type: "grafana_cpu", label: "Grafana CPU Alert", sub: "14MqUgb4k Cores" },
  { type: "grafana_memory", label: "Grafana Memory", sub: "8qW3UgxVz Allocatable" },
  { type: "synthetics_login", label: "Synthetics Canary", sub: "analytics_login_prod" },
  { type: "prometheus_slow", label: "Prometheus Slow", sub: "Target Scraping 60s" },
];

function StatCard({ label, value, sub, icon, color }: { label: string; value: string | number; sub: string; icon: React.ReactNode; color?: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: "10px", height: "100%" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
        <Typography variant="caption" color="text.secondary" fontWeight={600}>
          {label}
        </Typography>
        <Box sx={{ color: color ?? "primary.main", display: "flex" }}>{icon}</Box>
      </Stack>
      <Typography variant="h5" fontWeight={700} fontFamily="monospace" color={color}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {sub}
      </Typography>
    </Paper>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [triggering, setTriggering] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [statsData, alertsData, agentsData] = await Promise.all([
      api.get<DashboardStats>("/stats"),
      api.get<Alert[]>("/alerts"),
      api.get<Agent[]>("/agents"),
    ]);
    setStats(statsData);
    setAlerts(alertsData);
    setAgents(agentsData);
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [load]);

  const handleTrigger = async (sampleType: string) => {
    setTriggering(sampleType);
    try {
      await api.post("/alerts/sample-trigger", { sample_type: sampleType });
      await load();
    } finally {
      setTriggering(null);
    }
  };

  const firing = alerts.filter((a) => a.status === "Firing").slice(0, 4);

  return (
    <Box sx={{ p: { xs: 2, sm: 3, lg: 4 } }}>
      {/* Welcome banner */}
      <Paper
        sx={{
          p: { xs: 3, sm: 4 },
          borderRadius: "10px",
          mb: 4,
          background: "linear-gradient(135deg, #0f1720 0%, #16233a 60%, #0f1720 100%)",
          color: "#fff",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <Grid container spacing={3} alignItems="center">
          <Grid size={{ xs: 12, lg: 7 }}>
            <Chip
              icon={<BoltIcon sx={{ color: "#8fcf77 !important" }} />}
              label="SRE Agents Overview"
              size="small"
              sx={{ bgcolor: "rgba(20,116,212,0.25)", color: "#8ec5f5", mb: 1.5, fontWeight: 600 }}
            />
            <Typography variant="h5" fontWeight={700} gutterBottom>
              Automated Alert Triage &amp; Noise Filtering
            </Typography>
            <Typography variant="body2" sx={{ color: "rgba(255,255,255,0.75)" }}>
              Pluggable SRE agents analyze incoming alerts, cross-reference the knowledge base, and generate advisory
              root-cause triage reports — recommendations only, nothing is executed automatically.
            </Typography>
          </Grid>
          <Grid size={{ xs: 12, lg: 5 }}>
            <Paper sx={{ p: 2, bgcolor: "rgba(0,0,0,0.35)", borderRadius: "10px" }}>
              <Stack direction="row" alignItems="center" gap={0.75} sx={{ mb: 1.5 }}>
                <TerminalIcon fontSize="small" sx={{ color: "#8fcf77" }} />
                <Typography variant="caption" fontWeight={700} textTransform="uppercase" letterSpacing={0.5}>
                  1-Click Alert Ingestion Simulator
                </Typography>
              </Stack>
              <Grid container spacing={1}>
                {QUICK_TRIGGERS.map((t) => (
                  <Grid size={6} key={t.type}>
                    <Card
                      variant="outlined"
                      sx={{ bgcolor: "rgba(20,116,212,0.18)", borderColor: "rgba(20,116,212,0.4)" }}
                    >
                      <CardActionArea
                        disabled={!!triggering}
                        onClick={() => handleTrigger(t.type)}
                        sx={{ p: 1.25, display: "flex", justifyContent: "space-between", alignItems: "center" }}
                      >
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="caption" fontWeight={700} noWrap display="block" sx={{ color: "#e2edff" }}>
                            {t.label}
                          </Typography>
                          <Typography variant="caption" sx={{ color: "rgba(226,237,255,0.6)", fontSize: 10 }} noWrap display="block">
                            {t.sub}
                          </Typography>
                        </Box>
                        {triggering === t.type ? (
                          <CircularProgress size={14} sx={{ color: "#8ec5f5" }} />
                        ) : (
                          <ArrowOutwardIcon sx={{ fontSize: 14, color: "#8ec5f5" }} />
                        )}
                      </CardActionArea>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            </Paper>
          </Grid>
        </Grid>
      </Paper>

      {/* Stat cards */}
      <Grid container spacing={2} sx={{ mb: 4 }}>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Ingested Alerts" value={stats?.total_alerts_ingested ?? 0} sub="Total webhook signals" icon={<BoltIcon fontSize="small" />} />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard
            label="Real Incidents"
            value={stats?.real_incidents_count ?? 0}
            sub="Action required"
            icon={<LocalFireDepartmentIcon fontSize="small" />}
            color="error.main"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard
            label="Filtered Noise"
            value={stats?.filtered_noise_count ?? 0}
            sub={`${stats?.noise_reduction_rate ?? 0}% suppressed`}
            icon={<FilterAltIcon fontSize="small" />}
            color="success.main"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Active Agents" value={stats?.active_agents_count ?? 0} sub="Pluggable SRE bots" icon={<SmartToyIcon fontSize="small" />} />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard
            label="Auto-Triaged"
            value={`${stats?.auto_triaged_percentage ?? 100}%`}
            sub="Llama 4 Scout"
            icon={<CheckCircleIcon fontSize="small" />}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Advisory Mode" value="ON" sub="No auto-remediation" icon={<AccessTimeIcon fontSize="small" />} color="warning.main" />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        {/* Firing alerts feed */}
        <Grid size={{ xs: 12, lg: 8 }}>
          <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px" }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
              <Box>
                <Typography variant="subtitle1" fontWeight={700} display="flex" alignItems="center" gap={1}>
                  <WarningAmberIcon fontSize="small" color="warning" /> Active Incident Alerts
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Live alerts triaged by pluggable SRE agents
                </Typography>
              </Box>
              <Button size="small" onClick={() => navigate("/alerts")}>
                View all ({alerts.length})
              </Button>
            </Stack>

            <Stack spacing={1.5}>
              {firing.map((alert) => (
                <Paper
                  key={alert.id}
                  variant="outlined"
                  sx={{ p: 2, borderRadius: "8px", cursor: "pointer", "&:hover": { borderColor: "primary.main" } }}
                  onClick={() => navigate("/alerts", { state: { alertId: alert.id } })}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
                    <Stack direction="row" alignItems="center" gap={1}>
                      <Chip label={alert.source} size="small" sx={sourceColor(alert.source)} />
                      <Typography variant="caption" color="text.secondary" fontFamily="monospace">
                        {new Date(alert.occurred_at).toLocaleTimeString()}
                      </Typography>
                    </Stack>
                    <Stack direction="row" gap={0.5}>
                      <Chip label={alert.severity} size="small" sx={severityColor(alert.severity)} />
                      <Chip label={alert.verdict} size="small" sx={verdictColor(alert.verdict)} />
                    </Stack>
                  </Stack>
                  <Typography variant="body2" fontWeight={600} sx={{ mt: 1 }}>
                    {alert.title}
                  </Typography>
                  {alert.triage_report && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", mt: 0.5 }}>
                      {alert.triage_report.summary}
                    </Typography>
                  )}
                </Paper>
              ))}
              {firing.length === 0 && (
                <Box sx={{ textAlign: "center", py: 6 }}>
                  <CheckCircleIcon sx={{ fontSize: 40, color: "success.main", mb: 1 }} />
                  <Typography variant="body2" color="text.secondary">
                    All active alerts triaged or resolved.
                  </Typography>
                </Box>
              )}
            </Stack>
          </Paper>
        </Grid>

        {/* Agents panel */}
        <Grid size={{ xs: 12, lg: 4 }}>
          <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px" }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
              <Box>
                <Typography variant="subtitle1" fontWeight={700} display="flex" alignItems="center" gap={1}>
                  <SmartToyIcon fontSize="small" color="primary" /> SRE Pluggable Agents
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Active automated triage processes
                </Typography>
              </Box>
              <Button size="small" onClick={() => navigate("/agents")}>
                Studio
              </Button>
            </Stack>

            <Stack spacing={1.5}>
              {agents.map((agent) => (
                <Paper key={agent.id} variant="outlined" sx={{ p: 1.5, borderRadius: "8px" }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Stack direction="row" alignItems="center" gap={1}>
                      <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: agent.enabled ? "success.main" : "grey.500" }} />
                      <Typography variant="body2" fontWeight={600}>
                        {agent.name}
                      </Typography>
                    </Stack>
                    <Chip label={agent.category} size="small" variant="outlined" />
                  </Stack>
                  <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {agent.description}
                  </Typography>
                  <Stack direction="row" justifyContent="space-between" sx={{ mt: 1, pt: 1, borderTop: 1, borderColor: "divider" }}>
                    <Typography variant="caption" color="text.secondary">
                      Triaged: <strong>{agent.total_triaged}</strong>
                    </Typography>
                    <Typography variant="caption" color="success.main">
                      Noise: {agent.noise_filtered_count}
                    </Typography>
                  </Stack>
                </Paper>
              ))}
              {agents.length === 0 && (
                <Typography variant="body2" color="text.secondary" textAlign="center" sx={{ py: 3 }}>
                  No agents configured yet.
                </Typography>
              )}
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}
