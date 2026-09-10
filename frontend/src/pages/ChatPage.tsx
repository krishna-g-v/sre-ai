import { useEffect, useRef, useState } from "react";
import { Box, TextField, Typography, Chip, CircularProgress, IconButton, Paper, Stack } from "@mui/material";
import ArrowUpwardRoundedIcon from "@mui/icons-material/ArrowUpwardRounded";
import { api } from "../api/client";
import SessionSidebar from "../components/SessionSidebar";
import MessageBubble from "../components/MessageBubble";
import type { ChatMessage, ChatSession, SendMessageResponse } from "../types/api";

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [lastResponse, setLastResponse] = useState<SendMessageResponse | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;

  const loadSessions = async () => {
    const list = await api.get<ChatSession[]>("/chat/sessions");
    setSessions(list);
    return list;
  };

  const loadMessages = async (sessionId: string) => {
    const list = await api.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`);
    setMessages(list);
  };

  useEffect(() => {
    loadSessions().then((list) => {
      if (list.length > 0) setActiveSessionId(list[0].id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeSessionId) loadMessages(activeSessionId);
    else setMessages([]);
    setLastResponse(null);
  }, [activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleNewSession = async (prefill?: string) => {
    const session = await api.post<ChatSession>("/chat/sessions");
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(session.id);
    if (prefill) setInput(prefill);
  };

  const handleDeleteSession = async (id: string) => {
    await api.del(`/chat/sessions/${id}`);
    setSessions((prev) => {
      const remaining = prev.filter((s) => s.id !== id);
      if (activeSessionId === id) {
        setActiveSessionId(remaining[0]?.id ?? null);
      }
      return remaining;
    });
  };

  const handleSend = async () => {
    if (!input.trim()) return;
    let sessionId = activeSessionId;
    if (!sessionId) {
      const session = await api.post<ChatSession>("/chat/sessions");
      setSessions((prev) => [session, ...prev]);
      sessionId = session.id;
      setActiveSessionId(sessionId);
    }

    const content = input;
    setInput("");
    setSending(true);
    setMessages((prev) => [
      ...prev,
      { id: `temp-${Date.now()}`, role: "user", content, message_category: null, created_at: new Date().toISOString() },
    ]);

    try {
      const response = await api.post<SendMessageResponse>(`/chat/sessions/${sessionId}/messages`, { content });
      setMessages((prev) => [...prev, response.message]);
      setLastResponse(response);
      setSessions((prev) => {
        const updated = prev.map((s) => (s.id === response.session.id ? response.session : s));
        return updated.sort((a, b) => (a.id === response.session.id ? -1 : b.id === response.session.id ? 1 : 0));
      });
    } finally {
      setSending(false);
    }
  };

  return (
    <Box sx={{ display: "flex", height: "100%" }}>
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={setActiveSessionId}
        onNewSession={() => handleNewSession()}
        onDeleteSession={handleDeleteSession}
      />

      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <Stack
          direction="row"
          alignItems="center"
          gap={1}
          sx={{ px: 3, py: 1.5, borderBottom: 1, borderColor: "divider" }}
        >
          <Typography variant="subtitle1" fontWeight={700} sx={{ flex: 1 }} noWrap>
            {activeSession?.title ?? "SRE Agent"}
          </Typography>
          {activeSession?.status === "pinned" && (
            <Chip
              label={activeSession.pinned_document_title ?? "Pinned to document"}
              size="small"
              color="secondary"
              variant="outlined"
            />
          )}
        </Stack>

        <Box sx={{ flex: 1, overflowY: "auto", p: 3 }}>
          {messages.map((m) => {
            const isLast = lastResponse?.message.id === m.id;
            return (
              <MessageBubble
                key={m.id}
                message={m}
                retrievedTitles={isLast ? lastResponse?.retrieved_titles : undefined}
                drifted={isLast ? lastResponse?.drifted : undefined}
                onStartNewSession={
                  isLast && lastResponse?.drifted
                    ? () => {
                        const priorUserMessage = [...messages].reverse().find((msg) => msg.role === "user");
                        handleNewSession(priorUserMessage?.content);
                      }
                    : undefined
                }
              />
            );
          })}
          <div ref={messagesEndRef} />
        </Box>

        <Box sx={{ p: 2, borderTop: 1, borderColor: "divider" }}>
          <Paper
            elevation={0}
            sx={{
              maxWidth: 900,
              mx: "auto",
              display: "flex",
              alignItems: "flex-end",
              gap: 1,
              pl: 2.5,
              pr: 1,
              py: 1,
              borderRadius: "26px",
              border: 1,
              borderColor: "divider",
              bgcolor: "background.paper",
              transition: "border-color 0.15s",
              "&:focus-within": { borderColor: "primary.main" },
            }}
          >
            <TextField
              variant="standard"
              fullWidth
              multiline
              maxRows={8}
              placeholder="Message SRE Agent…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              disabled={sending}
              slotProps={{ input: { disableUnderline: true } }}
              sx={{ "& .MuiInputBase-input": { py: "8px", fontSize: 15 } }}
            />
            <IconButton
              onClick={handleSend}
              disabled={sending || !input.trim()}
              sx={{
                width: 36,
                height: 36,
                flexShrink: 0,
                bgcolor: input.trim() && !sending ? "primary.main" : "action.disabledBackground",
                color: input.trim() && !sending ? "primary.contrastText" : "text.disabled",
                "&:hover": { bgcolor: "primary.dark" },
                "&.Mui-disabled": { bgcolor: "action.disabledBackground" },
              }}
            >
              {sending ? <CircularProgress size={18} color="inherit" /> : <ArrowUpwardRoundedIcon fontSize="small" />}
            </IconButton>
          </Paper>
        </Box>
      </Box>
    </Box>
  );
}
