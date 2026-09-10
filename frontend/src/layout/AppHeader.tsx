import { AppBar, Avatar, Box, Chip, IconButton, Toolbar, Typography, useMediaQuery, useTheme } from "@mui/material";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import LogoutIcon from "@mui/icons-material/Logout";
import MenuIcon from "@mui/icons-material/Menu";
import { useAuth } from "../context/AuthContext";
import { useThemeMode } from "../context/ThemeModeContext";

interface Props {
  onToggleMobileNav: () => void;
}

export default function AppHeader({ onToggleMobileNav }: Props) {
  const { user, logout } = useAuth();
  const { mode, toggle } = useThemeMode();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  return (
    <AppBar position="fixed" color="transparent" elevation={0} sx={{ bgcolor: "background.paper", zIndex: (t) => t.zIndex.drawer + 1 }}>
      <Toolbar sx={{ gap: 1.5 }}>
        {isMobile && (
          <IconButton edge="start" onClick={onToggleMobileNav} aria-label="open navigation">
            <MenuIcon />
          </IconButton>
        )}

        <Box
          sx={{
            width: 36,
            height: 36,
            borderRadius: "8px",
            background: "linear-gradient(135deg, #1474d4, #0d5aa8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            fontWeight: 800,
            fontSize: 13,
            flexShrink: 0,
          }}
        >
          SRE
        </Box>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" fontWeight={700} noWrap>
            SRE Agent
          </Typography>
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
            <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: "success.main" }} />
            <Typography variant="caption" color="text.secondary">
              Active
            </Typography>
          </Box>
        </Box>

        <IconButton onClick={toggle} aria-label="toggle theme" title={mode === "dark" ? "Switch to light" : "Switch to dark"}>
          {mode === "dark" ? <LightModeIcon fontSize="small" /> : <DarkModeIcon fontSize="small" />}
        </IconButton>

        <Box sx={{ display: "flex", alignItems: "center", gap: 1, bgcolor: "action.hover", borderRadius: "10px", px: 1, py: 0.5 }}>
          <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: "secondary.main" }}>
            {(user?.username ?? "?").slice(0, 2).toUpperCase()}
          </Avatar>
          <Box sx={{ display: { xs: "none", sm: "block" }, lineHeight: 1.1 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <Typography variant="caption" fontWeight={700} noWrap sx={{ maxWidth: 120 }}>
                {user?.displayName}
              </Typography>
              {user?.isSuperuser && <Chip label="ADMIN" size="small" color="warning" sx={{ height: 16, fontSize: 9, fontWeight: 700 }} />}
            </Box>
          </Box>
          <IconButton size="small" onClick={logout} aria-label="logout" title="Log out">
            <LogoutIcon fontSize="small" />
          </IconButton>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
