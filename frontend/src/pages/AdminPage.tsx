import { useEffect, useState } from "react";
import {
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
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import ShieldIcon from "@mui/icons-material/Shield";
import AddIcon from "@mui/icons-material/Add";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import PersonAddIcon from "@mui/icons-material/PersonAddAlt";
import { api, ApiError } from "../api/client";
import type { GroupOut, UserOut } from "../types/api";

export default function AdminPage() {
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [users, setUsers] = useState<UserOut[]>([]);

  // Group modal — shared between create and edit; editingGroupId null = create mode.
  const [groupModalOpen, setGroupModalOpen] = useState(false);
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupDesc, setGroupDesc] = useState("");
  const [groupError, setGroupError] = useState<string | null>(null);

  // User modal — shared between create and edit; editingUserId null = create mode.
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [isSuperuser, setIsSuperuser] = useState(false);
  const [userError, setUserError] = useState<string | null>(null);

  const load = async () => {
    const [g, u] = await Promise.all([api.get<GroupOut[]>("/admin/groups"), api.get<UserOut[]>("/admin/users")]);
    setGroups(g);
    setUsers(u);
  };

  useEffect(() => {
    load();
  }, []);

  const openCreateGroup = () => {
    setEditingGroupId(null);
    setGroupName("");
    setGroupDesc("");
    setGroupError(null);
    setGroupModalOpen(true);
  };

  const openEditGroup = (group: GroupOut) => {
    setEditingGroupId(group.id);
    setGroupName(group.name);
    setGroupDesc(group.description);
    setGroupError(null);
    setGroupModalOpen(true);
  };

  const handleSaveGroup = async () => {
    if (!groupName.trim()) return;
    setGroupError(null);
    try {
      if (editingGroupId) {
        await api.put(`/admin/groups/${editingGroupId}`, { name: groupName.trim(), description: groupDesc.trim() });
      } else {
        await api.post("/admin/groups", { name: groupName.trim(), description: groupDesc.trim() });
      }
      setGroupModalOpen(false);
      await load();
    } catch (err) {
      setGroupError(err instanceof ApiError ? err.message : "Failed to save group");
    }
  };

  const handleDeleteGroup = async (id: string) => {
    if (!window.confirm("Delete this group? Documents/agents scoped to it will no longer be visible to its members.")) return;
    await api.del(`/admin/groups/${id}`);
    await load();
  };

  const openCreateUser = () => {
    setEditingUserId(null);
    setUsername("");
    setPassword("");
    setDisplayName("");
    setIsSuperuser(false);
    setUserError(null);
    setUserModalOpen(true);
  };

  const openEditUser = (user: UserOut) => {
    setEditingUserId(user.id);
    setUsername(user.username);
    setPassword("");
    setDisplayName(user.display_name);
    setIsSuperuser(user.is_superuser);
    setUserError(null);
    setUserModalOpen(true);
  };

  const handleSaveUser = async () => {
    setUserError(null);
    try {
      if (editingUserId) {
        await api.put(`/admin/users/${editingUserId}`, {
          display_name: displayName.trim() || undefined,
          password: password || undefined,
          is_superuser: isSuperuser,
        });
      } else {
        if (!username.trim() || !password.trim() || !displayName.trim()) {
          setUserError("Username, password, and display name are required.");
          return;
        }
        await api.post("/admin/users", {
          username: username.trim(),
          password,
          display_name: displayName.trim(),
          is_superuser: isSuperuser,
          group_ids: [],
        });
      }
      setUserModalOpen(false);
      await load();
    } catch (err) {
      setUserError(err instanceof ApiError ? err.message : "Failed to save user");
    }
  };

  const handleToggleUserGroup = async (targetUser: UserOut, groupId: string) => {
    const nextGroupIds = targetUser.group_ids.includes(groupId)
      ? targetUser.group_ids.filter((g) => g !== groupId)
      : [...targetUser.group_ids, groupId];
    await api.put(`/admin/users/${targetUser.id}/groups`, { group_ids: nextGroupIds });
    await load();
  };

  return (
    <Box sx={{ p: { xs: 2, sm: 3, lg: 4 } }}>
      <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px", mb: 3, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 2 }}>
        <Box>
          <Typography variant="h6" fontWeight={700} display="flex" alignItems="center" gap={1}>
            <ShieldIcon color="primary" /> Users &amp; Group Management
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Groups control document and dashboard access — assigning a user to a group grants them everything tagged to it.
          </Typography>
        </Box>
        <Stack direction="row" gap={1}>
          <Button variant="outlined" startIcon={<AddIcon />} onClick={openCreateGroup}>
            New Group
          </Button>
          <Button variant="contained" startIcon={<PersonAddIcon />} onClick={openCreateUser}>
            Create User
          </Button>
        </Stack>
      </Paper>

      <Grid container spacing={3}>
        {/* Groups */}
        <Grid size={{ xs: 12, lg: 4 }}>
          <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px", height: "100%" }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 2 }}>
              Groups ({groups.length})
            </Typography>
            <Stack spacing={1.5}>
              {groups.map((g) => (
                <Paper key={g.id} variant="outlined" sx={{ p: 1.5, borderRadius: "8px" }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" fontWeight={700} color="primary.main">
                        {g.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {g.description || "No description"}
                      </Typography>
                    </Box>
                    <Stack direction="row" gap={0.5} flexShrink={0}>
                      <IconButton size="small" onClick={() => openEditGroup(g)}>
                        <EditOutlinedIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" color="error" onClick={() => handleDeleteGroup(g.id)}>
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Stack>
                  </Stack>
                </Paper>
              ))}
              {groups.length === 0 && (
                <Typography variant="body2" color="text.secondary" textAlign="center" sx={{ py: 2 }}>
                  No groups yet.
                </Typography>
              )}
            </Stack>
          </Paper>
        </Grid>

        {/* Users */}
        <Grid size={{ xs: 12, lg: 8 }}>
          <Paper variant="outlined" sx={{ p: 3, borderRadius: "10px", height: "100%" }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 2 }}>
              Users ({users.length})
            </Typography>
            <Stack spacing={2}>
              {users.map((u) => (
                <Paper key={u.id} variant="outlined" sx={{ p: 2, borderRadius: "8px" }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                    <Stack direction="row" alignItems="center" gap={1}>
                      <Typography variant="body2" fontWeight={700}>
                        {u.display_name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" fontFamily="monospace">
                        @{u.username}
                      </Typography>
                      {u.is_superuser && <Chip label="ADMIN" size="small" color="warning" sx={{ height: 18, fontSize: 10 }} />}
                    </Stack>
                    <IconButton size="small" onClick={() => openEditUser(u)}>
                      <EditOutlinedIcon fontSize="small" />
                    </IconButton>
                  </Stack>

                  <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: "block" }}>
                    Group membership:
                  </Typography>
                  <Stack direction="row" gap={0.75} flexWrap="wrap">
                    {groups.map((g) => {
                      const assigned = u.group_ids.includes(g.id) || u.is_superuser;
                      return (
                        <Chip
                          key={g.id}
                          label={g.name}
                          size="small"
                          onClick={() => !u.is_superuser && handleToggleUserGroup(u, g.id)}
                          color={assigned ? "primary" : "default"}
                          variant={assigned ? "filled" : "outlined"}
                          sx={{ cursor: u.is_superuser ? "default" : "pointer" }}
                        />
                      );
                    })}
                    {groups.length === 0 && (
                      <Typography variant="caption" color="text.secondary">
                        No groups to assign yet.
                      </Typography>
                    )}
                  </Stack>
                </Paper>
              ))}
            </Stack>
          </Paper>
        </Grid>
      </Grid>

      {/* Group modal — create or edit */}
      <Dialog open={groupModalOpen} onClose={() => setGroupModalOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{editingGroupId ? "Edit Group" : "New Group"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Group Name" value={groupName} onChange={(e) => setGroupName(e.target.value)} fullWidth autoFocus />
            <TextField label="Description" value={groupDesc} onChange={(e) => setGroupDesc(e.target.value)} fullWidth multiline rows={2} />
            {groupError && (
              <Typography variant="caption" color="error.main">
                {groupError}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 3, pt: 1 }}>
          <Button onClick={() => setGroupModalOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSaveGroup} disabled={!groupName.trim()}>
            {editingGroupId ? "Save" : "Create"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* User modal — create or edit */}
      <Dialog open={userModalOpen} onClose={() => setUserModalOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{editingUserId ? "Edit User" : "Create User"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              fullWidth
              autoFocus
              disabled={!!editingUserId}
              helperText={editingUserId ? "Username can't be changed" : undefined}
            />
            <TextField
              label={editingUserId ? "New Password" : "Password"}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              fullWidth
              helperText={editingUserId ? "Leave blank to keep the current password" : undefined}
            />
            <TextField label="Display Name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} fullWidth />
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Typography variant="body2">Superuser</Typography>
              <Switch checked={isSuperuser} onChange={(e) => setIsSuperuser(e.target.checked)} />
            </Stack>
            {userError && (
              <Typography variant="caption" color="error.main">
                {userError}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 3, pt: 1 }}>
          <Button onClick={() => setUserModalOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSaveUser}>
            {editingUserId ? "Save" : "Create"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
