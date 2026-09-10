import { Box, Chip, Paper, Stack, Typography, Button, useTheme } from "@mui/material";
import type { ChatMessage } from "../types/api";
import MarkdownContent from "./MarkdownContent";

interface Props {
  message: ChatMessage;
  retrievedTitles?: string[];
  drifted?: boolean;
  onStartNewSession?: () => void;
}

export default function MessageBubble({ message, retrievedTitles, drifted, onStartNewSession }: Props) {
  const isUser = message.role === "user";
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  return (
    <Box sx={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start", mb: 2 }}>
      <Box sx={{ maxWidth: "75%" }}>
        <Paper
          elevation={0}
          sx={{
            p: 1.5,
            borderRadius: "14px",
            // Light mode: a soft, professional light-blue tint with near-black text
            // rather than a solid saturated primary-color bubble. Dark mode is left as
            // it was — a solid primary bubble already reads well against the dark page.
            bgcolor: isUser ? (isDark ? "primary.main" : "#e3f0fd") : "background.paper",
            color: isUser ? (isDark ? "primary.contrastText" : "#12202e") : "text.primary",
            border: isUser ? "none" : 1,
            borderColor: "divider",
          }}
        >
          {isUser ? (
            <Typography variant="body1" sx={{ whiteSpace: "pre-wrap" }}>
              {message.content}
            </Typography>
          ) : (
            <MarkdownContent content={message.content} />
          )}
        </Paper>

        {!isUser && (retrievedTitles?.length || message.message_category) && (
          <Stack direction="row" spacing={1} sx={{ mt: 0.75, flexWrap: "wrap", gap: 0.5 }}>
            {message.message_category && (
              <Chip label={message.message_category.replace("_", " ")} size="small" variant="outlined" />
            )}
            {retrievedTitles?.map((title) => (
              <Chip key={title} label={title} size="small" color="secondary" variant="outlined" />
            ))}
          </Stack>
        )}

        {drifted && onStartNewSession && (
          <Button size="small" variant="outlined" sx={{ mt: 1 }} onClick={onStartNewSession}>
            Start new session
          </Button>
        )}
      </Box>
    </Box>
  );
}
