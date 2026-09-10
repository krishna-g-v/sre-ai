import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import AddIcon from "@mui/icons-material/Add";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import CodeIcon from "@mui/icons-material/Code";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL, api } from "../api/client";
import type { Agent, AgentCategory } from "../types/api";
import { sourceColor } from "../components/alertColors";

const CATEGORIES: AgentCategory[] = ["Grafana", "Synthetics", "Prometheus", "Kubernetes", "CloudWatch", "Custom"];

export default function AgentsPage() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const [name, setName] = useState("");
  const [category, setCategory] = useState<AgentCategory>("Custom");
  const [owner, setOwner] = useState("");
  const [description, setDescription] = useState("");
  const [triagePrompt, setTriagePrompt] = useState(
    "Evaluate alert parameters, separate transient noise from true outage, and provide remediation steps.",
  );

  const load = async () => setAgents(await api.get<Agent[]>("/agents"));

  useEffect(() => {
    load();
  }, []);

  const handleCreate = async () => {
    if (!name.trim()) return;
    await api.post("/agents", {
      name: name.trim(),
      category,
      owner: owner.trim(),
      description: description.trim(),
      triage_prompt: triagePrompt.trim(),
    });
    setName("");
    setOwner("");
    setDescription("");
    setCreateOpen(false);
    await load();
  };

  const handleToggle = async (id: string) => {
    await api.post(`/agents/${id}/toggle`);
    await load();
  };

  const handleDelete = async (id: string) => {
    await api.del(`/agents/${id}`);
    await load();
  };

  const webhookUrl = (agent: Agent) => `${API_BASE_URL}${agent.webhook_path}`;

  return (
    <Box sx={{ p: { xs: 2, sm: 3, lg: 4 } }}>
      <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px", mb: 3, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 2 }}>
        <Box>
          <Typography variant="h6" fontWeight={700} display="flex" alignItems="center" gap={1}>
            <SmartToyIcon color="primary" /> SRE Agent Studio
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Create and configure pluggable SRE agents for your observability pipeline
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
          Plug-in New Agent
        </Button>
      </Paper>

      <Grid container spacing={3}>
        {agents.map((agent) => (
          <Grid size={{ xs: 12, sm: 6, lg: 4 }} key={agent.id}>
            <Paper variant="outlined" sx={{ p: 2.5, borderRadius: "10px", height: "100%", display: "flex", flexDirection: "column", gap: 1.5, opacity: agent.enabled ? 1 : 0.6 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Chip label={agent.category} size="small" sx={sourceColor(agent.category)} />
                <Chip
                  label={agent.enabled ? "Active" : "Paused"}
                  size="small"
                  color={agent.enabled ? "success" : "default"}
                  onClick={() => handleToggle(agent.id)}
                  sx={{ cursor: "pointer" }}
                />
              </Stack>

              <Box>
                <Typography variant="subtitle2" fontWeight={700}>
                  {agent.name}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {agent.description}
                </Typography>
              </Box>

              <Paper variant="outlined" sx={{ p: 1.25, bgcolor: "action.hover", fontSize: 11 }}>
                <Typography variant="caption" display="block">
                  Owner: <strong>{agent.owner || "—"}</strong>
                </Typography>
                <Typography variant="caption" color="text.secondary" fontFamily="monospace" noWrap display="block">
                  {agent.webhook_path}
                </Typography>
              </Paper>

              <Grid container spacing={1} textAlign="center">
                <Grid size={4}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Total
                  </Typography>
                  <Typography variant="body2" fontWeight={700} fontFamily="monospace">
                    {agent.total_triaged}
                  </Typography>
                </Grid>
                <Grid size={4}>
                  <Typography variant="caption" color="error.main" display="block">
                    Real
                  </Typography>
                  <Typography variant="body2" fontWeight={700} fontFamily="monospace" color="error.main">
                    {agent.real_issues_detected}
                  </Typography>
                </Grid>
                <Grid size={4}>
                  <Typography variant="caption" color="success.main" display="block">
                    Noise
                  </Typography>
                  <Typography variant="body2" fontWeight={700} fontFamily="monospace" color="success.main">
                    {agent.noise_filtered_count}
                  </Typography>
                </Grid>
              </Grid>

              <Stack direction="row" gap={1} sx={{ mt: "auto" }}>
                <Button fullWidth size="small" variant="contained" color="inherit" startIcon={<CodeIcon />} onClick={() => setSelected(agent)}>
                  Webhook &amp; Test
                </Button>
                <IconButton size="small" color="error" onClick={() => handleDelete(agent.id)}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            </Paper>
          </Grid>
        ))}

        {agents.length === 0 && (
          <Grid size={12}>
            <Paper variant="outlined" sx={{ p: 6, textAlign: "center", borderRadius: "10px" }}>
              <Typography variant="body2" color="text.secondary">
                No agents plugged in yet — create one to start triaging alerts.
              </Typography>
            </Paper>
          </Grid>
        )}
      </Grid>

      {/* Webhook / detail drawer */}
      <Drawer anchor="right" open={!!selected} onClose={() => setSelected(null)}>
        {selected && (
          <Box sx={{ width: { xs: "100vw", sm: 460 }, height: "100%", display: "flex", flexDirection: "column" }}>
            <Box sx={{ p: 3, bgcolor: "#0f1720", color: "#fff" }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Box>
                  <Typography variant="caption" sx={{ color: "#8ec5f5" }}>
                    Agent Webhook &amp; Testing
                  </Typography>
                  <Typography variant="subtitle1" fontWeight={700}>
                    {selected.name}
                  </Typography>
                </Box>
                <IconButton size="small" onClick={() => setSelected(null)} sx={{ color: "#fff" }}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Stack>
            </Box>

            <Box sx={{ flex: 1, overflowY: "auto", p: 3 }}>
              <Paper sx={{ p: 2, bgcolor: "#0f1720", color: "#fff", borderRadius: "8px", mb: 3 }}>
                <Typography variant="caption" sx={{ color: "rgba(255,255,255,0.6)" }}>
                  Ingestion webhook (POST JSON payload here)
                </Typography>
                <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mt: 1, p: 1, bgcolor: "rgba(255,255,255,0.06)", borderRadius: "8px" }}>
                  <Typography variant="caption" fontFamily="monospace" noWrap sx={{ color: "#8ec5f5" }}>
                    {webhookUrl(selected)}
                  </Typography>
                  <Button
                    size="small"
                    startIcon={<ContentCopyIcon sx={{ fontSize: 14 }} />}
                    sx={{ color: "#fff", flexShrink: 0 }}
                    onClick={() => {
                      navigator.clipboard.writeText(webhookUrl(selected));
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }}
                  >
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </Stack>
              </Paper>

              <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 1 }}>
                AI Triage Instructions
              </Typography>
              <Paper variant="outlined" sx={{ p: 1.5, mb: 3, bgcolor: "action.hover" }}>
                <Typography variant="caption" fontFamily="monospace">
                  {selected.triage_prompt}
                </Typography>
              </Paper>

              <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 1 }}>
                Try it from the dashboard's 1-click simulator, or point a real Grafana/Prometheus/Synthetics
                Alertmanager webhook at the URL above.
              </Typography>
              <Button
                fullWidth
                variant="contained"
                color="success"
                startIcon={<PlayArrowIcon />}
                sx={{ mt: 1 }}
                onClick={() => navigate("/dashboard")}
              >
                Go to Dashboard Simulator
              </Button>
            </Box>
          </Box>
        )}
      </Drawer>

      {/* Create agent modal */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Plug-in New SRE Agent</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Agent Name" value={name} onChange={(e) => setName(e.target.value)} fullWidth required />
            <Stack direction="row" spacing={2}>
              <TextField select label="Category" value={category} onChange={(e) => setCategory(e.target.value as AgentCategory)} fullWidth>
                {CATEGORIES.map((c) => (
                  <MenuItem key={c} value={c}>
                    {c}
                  </MenuItem>
                ))}
              </TextField>
              <TextField label="Owner" value={owner} onChange={(e) => setOwner(e.target.value)} fullWidth />
            </Stack>
            <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} fullWidth />
            <TextField
              label="AI Triage Instructions"
              value={triagePrompt}
              onChange={(e) => setTriagePrompt(e.target.value)}
              fullWidth
              multiline
              rows={3}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 3, pt: 1 }}>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={!name.trim()}>
            Create Agent
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
