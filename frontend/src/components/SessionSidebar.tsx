import type { MouseEvent } from "react";
import {
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import type { ChatSession } from "../types/api";

interface Props {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
}

export default function SessionSidebar({ sessions, activeSessionId, onSelect, onNewSession, onDeleteSession }: Props) {
  const handleDelete = (e: MouseEvent, session: ChatSession) => {
    e.stopPropagation();
    if (window.confirm(`Delete "${session.title}"? This can't be undone.`)) {
      onDeleteSession(session.id);
    }
  };

  return (
    <Box
      sx={{
        width: 280,
        flexShrink: 0,
        borderRight: 1,
        borderColor: "divider",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      <Box sx={{ p: 2 }}>
        <Button startIcon={<AddIcon />} variant="outlined" fullWidth onClick={onNewSession}>
          New Chat
        </Button>
      </Box>
      <Divider />
      <List sx={{ overflowY: "auto", flex: 1 }}>
        {sessions.map((session) => (
          <ListItemButton
            key={session.id}
            selected={session.id === activeSessionId}
            onClick={() => onSelect(session.id)}
            sx={{
              alignItems: "flex-start",
              gap: 0.5,
              "&:hover .session-delete-btn": { opacity: 1 },
            }}
          >
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <ListItemText
                primary={session.title}
                slotProps={{ primary: { noWrap: true, fontSize: 14 } }}
              />
              {session.status === "pinned" && (
                <Chip
                  label={session.pinned_document_title ?? "Pinned"}
                  size="small"
                  color="secondary"
                  variant="outlined"
                  sx={{ maxWidth: "100%" }}
                />
              )}
            </Box>
            <IconButton
              className="session-delete-btn"
              size="small"
              onClick={(e) => handleDelete(e, session)}
              aria-label="delete session"
              sx={{ opacity: { xs: 1, sm: 0 }, transition: "opacity 0.15s", flexShrink: 0 }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </ListItemButton>
        ))}
        {sessions.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
            No chats yet — start a new one.
          </Typography>
        )}
      </List>
    </Box>
  );
}
