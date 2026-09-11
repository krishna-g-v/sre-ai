import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import MenuBookIcon from "@mui/icons-material/MenuBookOutlined";
import AddIcon from "@mui/icons-material/Add";
import SearchIcon from "@mui/icons-material/Search";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import AutoFixHighOutlinedIcon from "@mui/icons-material/AutoFixHighOutlined";
import { api } from "../api/client";
import type { DocumentOut, GroupOut } from "../types/api";

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [search, setSearch] = useState("");
  const [scopeFilter, setScopeFilter] = useState<"ALL" | "personal" | "group">("ALL");
  const [uploadOpen, setUploadOpen] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [docTitle, setDocTitle] = useState("");
  const [ownerScope, setOwnerScope] = useState<"personal" | "group">("personal");
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [tags, setTags] = useState("");
  const [chunkStrategy, setChunkStrategy] = useState<"whole_document" | "best_effort">("whole_document");
  const [convertToMarkdown, setConvertToMarkdown] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const isMarkdownFile = !!file && /\.(md|markdown)$/i.test(file.name);

  const load = async () => setDocuments(await api.get<DocumentOut[]>("/documents"));

  useEffect(() => {
    load();
    api.get<GroupOut[]>("/groups/mine").then(setGroups).catch(() => {});
  }, []);

  const groupName = (id: string) => groups.find((g) => g.id === id)?.name ?? id.slice(0, 8);

  const filtered = useMemo(() => {
    return documents.filter((d) => {
      const matchesSearch = d.title.toLowerCase().includes(search.toLowerCase()) || d.tags.some((t) => t.toLowerCase().includes(search.toLowerCase()));
      const matchesScope = scopeFilter === "ALL" || d.owner_scope === scopeFilter;
      return matchesSearch && matchesScope;
    });
  }, [documents, search, scopeFilter]);

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null;
    setFile(picked);
    if (picked && !docTitle) {
      setDocTitle(picked.name.replace(/\.[^./]+$/, ""));
    }
  };

  const handleUpload = async () => {
    if (!file || !docTitle.trim()) return;
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", docTitle.trim());
      form.append("owner_scope", ownerScope);
      form.append("group_ids", JSON.stringify(ownerScope === "group" ? selectedGroupIds : []));
      form.append("tags", JSON.stringify(tags.split(",").map((t) => t.trim()).filter(Boolean)));
      form.append("chunk_strategy", chunkStrategy);
      form.append("convert_to_markdown", String(convertToMarkdown && !isMarkdownFile));
      await api.postForm("/documents", form);
      setUploadOpen(false);
      setFile(null);
      setDocTitle("");
      setTags("");
      setSelectedGroupIds([]);
      setConvertToMarkdown(false);
      await load();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: string) => {
    await api.del(`/documents/${id}`);
    await load();
  };

  return (
    <Box sx={{ p: { xs: 2, sm: 3, lg: 4 } }}>
      <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px", mb: 3, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 2 }}>
        <Box>
          <Typography variant="h6" fontWeight={700} display="flex" alignItems="center" gap={1}>
            <MenuBookIcon color="primary" /> Knowledge Base
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Documents are access-controlled by group — you only retrieve what your groups (or personal KB) grant.
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setUploadOpen(true)}>
          Upload Document
        </Button>
      </Paper>

      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={2} sx={{ mb: 3 }}>
        <TextField
          size="small"
          placeholder="Search by title or tag..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 280 }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
        />
        <ToggleButtonGroup size="small" value={scopeFilter} exclusive onChange={(_, v) => v && setScopeFilter(v)}>
          <ToggleButton value="ALL" sx={{ textTransform: "none", fontSize: 12, px: 1.5 }}>
            All ({documents.length})
          </ToggleButton>
          <ToggleButton value="personal" sx={{ textTransform: "none", fontSize: 12, px: 1.5 }}>
            My Documents
          </ToggleButton>
          <ToggleButton value="group" sx={{ textTransform: "none", fontSize: 12, px: 1.5 }}>
            Group Documents
          </ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      <Grid container spacing={3}>
        {filtered.map((doc) => (
          <Grid size={{ xs: 12, sm: 6, lg: 4 }} key={doc.id}>
            <Paper variant="outlined" sx={{ p: 2.5, borderRadius: "10px", height: "100%", display: "flex", flexDirection: "column", gap: 1 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Chip label={doc.owner_scope === "personal" ? "Personal" : "Group"} size="small" color={doc.owner_scope === "personal" ? "default" : "primary"} variant="outlined" />
                <Chip
                  label={doc.status}
                  size="small"
                  color={doc.status === "ready" ? "success" : doc.status === "failed" ? "error" : "warning"}
                />
              </Stack>

              <Typography variant="subtitle2" fontWeight={700} noWrap>
                {doc.title}
              </Typography>
              <Stack direction="row" alignItems="center" gap={0.75} flexWrap="wrap">
                <Typography variant="caption" color="text.secondary">
                  {doc.content_type.toUpperCase()} · {doc.chunk_strategy === "whole_document" ? "Whole document" : `Best effort (${doc.best_effort_target_size})`}
                </Typography>
                {doc.converted_to_markdown && (
                  <Chip
                    icon={<AutoFixHighOutlinedIcon sx={{ fontSize: 12 }} />}
                    label="Markdown-converted"
                    size="small"
                    variant="outlined"
                    color="primary"
                    sx={{ height: 18, fontSize: 10 }}
                  />
                )}
              </Stack>

              {doc.group_ids.length > 0 && (
                <Stack direction="row" gap={0.5} flexWrap="wrap">
                  {doc.group_ids.map((gid) => (
                    <Chip key={gid} label={groupName(gid)} size="small" variant="outlined" sx={{ fontSize: 10 }} />
                  ))}
                </Stack>
              )}

              {doc.tags.length > 0 && (
                <Stack direction="row" gap={0.5} flexWrap="wrap">
                  {doc.tags.map((tag) => (
                    <Chip key={tag} label={tag} size="small" variant="outlined" sx={{ fontSize: 10, bgcolor: "action.hover" }} />
                  ))}
                </Stack>
              )}

              <Stack direction="row" justifyContent="flex-end" sx={{ mt: "auto", pt: 1, borderTop: 1, borderColor: "divider" }}>
                <IconButton size="small" color="error" onClick={() => handleDelete(doc.id)}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            </Paper>
          </Grid>
        ))}

        {filtered.length === 0 && (
          <Grid size={12}>
            <Paper variant="outlined" sx={{ p: 6, textAlign: "center", borderRadius: "10px" }}>
              <Typography variant="body2" color="text.secondary">
                No documents yet — upload one to start building the knowledge base.
              </Typography>
            </Paper>
          </Grid>
        )}
      </Grid>

      <Dialog open={uploadOpen} onClose={() => setUploadOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Upload Document</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Button component="label" variant="outlined" startIcon={<UploadFileIcon />}>
              {file ? file.name : "Choose file (PDF, DOCX, MD, TXT)"}
              <input type="file" hidden accept=".pdf,.docx,.md,.txt" onChange={handleFileChange} />
            </Button>

            <TextField
              label="Document Name"
              value={docTitle}
              onChange={(e) => setDocTitle(e.target.value)}
              fullWidth
              required
              helperText="Shown to users in chat citations — not the filename."
            />

            <TextField select label="Scope" value={ownerScope} onChange={(e) => setOwnerScope(e.target.value as "personal" | "group")} fullWidth>
              <MenuItem value="personal">Personal (only me)</MenuItem>
              <MenuItem value="group" disabled={groups.length === 0}>
                Group{groups.length === 0 ? " (no groups available)" : ""}
              </MenuItem>
            </TextField>

            {ownerScope === "group" && (
              <TextField
                select
                label="Groups"
                value={selectedGroupIds}
                onChange={(e) => setSelectedGroupIds(typeof e.target.value === "string" ? [e.target.value] : e.target.value)}
                slotProps={{ select: { multiple: true } }}
                fullWidth
              >
                {groups.map((g) => (
                  <MenuItem key={g.id} value={g.id}>
                    {g.name}
                  </MenuItem>
                ))}
              </TextField>
            )}

            <TextField
              select
              label="Chunking strategy"
              value={chunkStrategy}
              onChange={(e) => setChunkStrategy(e.target.value as "whole_document" | "best_effort")}
              fullWidth
            >
              <MenuItem value="whole_document">Whole document (recommended for short docs)</MenuItem>
              <MenuItem value="best_effort">Best effort (split into sections)</MenuItem>
            </TextField>

            <TextField label="Tags (comma separated)" value={tags} onChange={(e) => setTags(e.target.value)} fullWidth placeholder="runbook, onboarding" />

            <Box>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={convertToMarkdown}
                    disabled={isMarkdownFile}
                    onChange={(e) => setConvertToMarkdown(e.target.checked)}
                  />
                }
                label={
                  <Stack direction="row" alignItems="center" gap={0.75}>
                    <AutoFixHighOutlinedIcon fontSize="small" color={convertToMarkdown ? "primary" : "disabled"} />
                    <Typography variant="body2">Convert to Markdown before ingesting</Typography>
                  </Stack>
                }
              />
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", pl: 4.5 }}>
                {isMarkdownFile
                  ? "This file is already Markdown — nothing to convert."
                  : "Uses the LLM to rewrite the extracted content as clean, structured Markdown before chunking — usually improves retrieval accuracy and uses fewer tokens per answer. Adds a short delay to this upload."}
              </Typography>
            </Box>

            {uploadError && (
              <Typography variant="caption" color="error.main">
                {uploadError}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 3, pt: 1 }}>
          <Button onClick={() => setUploadOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleUpload} disabled={!file || !docTitle.trim() || uploading || (ownerScope === "group" && selectedGroupIds.length === 0)}>
            {uploading ? "Uploading…" : "Upload"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
