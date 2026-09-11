import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import SettingsIcon from "@mui/icons-material/SettingsOutlined";
import AddIcon from "@mui/icons-material/Add";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import KeyOutlinedIcon from "@mui/icons-material/KeyOutlined";
import { api, ApiError } from "../api/client";
import type { UserAwsAccount } from "../types/api";

export default function SettingsPage() {
  const [accounts, setAccounts] = useState<UserAwsAccount[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [accountId, setAccountId] = useState("");
  const [roleArn, setRoleArn] = useState("");
  const [externalId, setExternalId] = useState("");
  const [region, setRegion] = useState("");
  const [accessKeyId, setAccessKeyId] = useState("");
  const [secretAccessKey, setSecretAccessKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setAccounts(await api.get<UserAwsAccount[]>("/settings/aws-accounts"));
  };

  useEffect(() => {
    load();
  }, []);

  const resetForm = () => {
    setLabel("");
    setAccountId("");
    setRoleArn("");
    setExternalId("");
    setRegion("");
    setAccessKeyId("");
    setSecretAccessKey("");
    setError(null);
  };

  const openCreate = () => {
    setEditingId(null);
    resetForm();
    setModalOpen(true);
  };

  const openEdit = (a: UserAwsAccount) => {
    setEditingId(a.id);
    setLabel(a.label);
    setAccountId(a.account_id);
    setRoleArn(a.role_arn);
    setExternalId(a.external_id);
    setRegion(a.region);
    setAccessKeyId("");
    setSecretAccessKey("");
    setError(null);
    setModalOpen(true);
  };

  const handleSave = async () => {
    setError(null);
    try {
      if (editingId) {
        const payload: Record<string, string> = {
          role_arn: roleArn.trim(),
          account_id: accountId.trim(),
          external_id: externalId.trim(),
          region: region.trim(),
        };
        // Only touch stored credentials if the user actually typed something in this
        // session — leaving both blank means "don't change what's already saved."
        if (accessKeyId.trim() || secretAccessKey.trim()) {
          payload.access_key_id = accessKeyId.trim();
          payload.secret_access_key = secretAccessKey.trim();
        }
        await api.patch(`/settings/aws-accounts/${editingId}`, payload);
      } else {
        await api.post("/settings/aws-accounts", {
          label: label.trim(),
          account_id: accountId.trim(),
          role_arn: roleArn.trim(),
          external_id: externalId.trim(),
          region: region.trim(),
          access_key_id: accessKeyId.trim(),
          secret_access_key: secretAccessKey.trim(),
        });
      }
      setModalOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save AWS account");
    }
  };

  const handleDelete = async (id: string, accountLabel: string) => {
    if (!window.confirm(`Remove "${accountLabel}"? Any chat questions that need it will stop working until you re-add it.`)) return;
    await api.del(`/settings/aws-accounts/${id}`);
    await load();
  };

  return (
    <Box sx={{ p: { xs: 2, sm: 3, lg: 4 }, maxWidth: 800 }}>
      <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px", mb: 3 }}>
        <Typography variant="h6" fontWeight={700} display="flex" alignItems="center" gap={1}>
          <SettingsIcon color="primary" /> My AWS Accounts
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Register the AWS accounts you personally have read-only access to. The Assistant uses these — and only
          these — when it runs AWS CLI/kubectl commands on your behalf; nobody else sees or uses your accounts,
          and admin-provisioned group integrations are unaffected by this list.
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
          Access Key ID / Secret Access Key are optional — the identity that assumes your Role ARN. Leave blank to
          use this application's shared identity instead (still requires your role's trust policy to allow it);
          fill them in to use your own IAM user instead. Either way, only the read-only role is ever actually
          used for AWS calls.
        </Typography>
      </Paper>

      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 2 }}>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          Add AWS Account
        </Button>
      </Stack>

      <Stack spacing={1.5}>
        {accounts.map((a) => (
          <Paper key={a.id} variant="outlined" sx={{ p: 2, borderRadius: "8px" }}>
            <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
              <Box sx={{ minWidth: 0 }}>
                <Stack direction="row" alignItems="center" gap={1}>
                  <Typography variant="body2" fontWeight={700} color="primary.main">
                    {a.label}
                  </Typography>
                  {a.has_own_credentials && (
                    <Chip
                      icon={<KeyOutlinedIcon sx={{ fontSize: 14 }} />}
                      label="own credentials"
                      size="small"
                      variant="outlined"
                      sx={{ height: 20, fontSize: 10 }}
                    />
                  )}
                </Stack>
                <Typography variant="caption" color="text.secondary" display="block">
                  {a.account_id ? `Account ${a.account_id}` : "No account ID set"}
                  {a.region ? ` · ${a.region}` : ""}
                </Typography>
                <Typography variant="caption" color="text.secondary" fontFamily="monospace" sx={{ wordBreak: "break-all" }}>
                  {a.role_arn}
                </Typography>
              </Box>
              <Stack direction="row" gap={0.5} flexShrink={0}>
                <IconButton size="small" onClick={() => openEdit(a)}>
                  <EditOutlinedIcon fontSize="small" />
                </IconButton>
                <IconButton size="small" color="error" onClick={() => handleDelete(a.id, a.label)}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            </Stack>
          </Paper>
        ))}
        {accounts.length === 0 && (
          <Typography variant="body2" color="text.secondary" textAlign="center" sx={{ py: 4 }}>
            No AWS accounts registered yet. Add one to let the Assistant answer AWS/EKS questions for you.
          </Typography>
        )}
      </Stack>

      <Dialog open={modalOpen} onClose={() => setModalOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{editingId ? "Edit AWS Account" : "Add AWS Account"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Label"
              placeholder="e.g. nonprod"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              fullWidth
              autoFocus={!editingId}
              disabled={!!editingId}
              helperText={editingId ? "Label can't be changed — delete and re-add to rename" : "A short name you'll use to refer to this account in chat"}
            />
            <TextField
              label="Role ARN"
              placeholder="arn:aws:iam::111111111111:role/sre-agent-readonly"
              value={roleArn}
              onChange={(e) => setRoleArn(e.target.value)}
              fullWidth
            />
            <TextField label="AWS Account ID" value={accountId} onChange={(e) => setAccountId(e.target.value)} fullWidth />
            <TextField label="Region" placeholder="us-east-1" value={region} onChange={(e) => setRegion(e.target.value)} fullWidth />
            <TextField
              label="External ID (optional)"
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              fullWidth
              helperText="Only if you set one in the role's trust policy"
            />
            <TextField
              label="Access Key ID (optional)"
              value={accessKeyId}
              onChange={(e) => setAccessKeyId(e.target.value)}
              fullWidth
              autoComplete="off"
              helperText={editingId ? "Leave blank to keep the current one" : "Leave blank to use the shared application identity"}
            />
            <TextField
              label="Secret Access Key (optional)"
              type="password"
              value={secretAccessKey}
              onChange={(e) => setSecretAccessKey(e.target.value)}
              fullWidth
              autoComplete="off"
              helperText={editingId ? "Leave blank to keep the current one" : "Stored so the Assistant can authenticate as you — treat like any other credential"}
            />
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 3, pt: 1 }}>
          <Button onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSave} disabled={!label.trim() || !roleArn.trim()}>
            {editingId ? "Save" : "Add"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
