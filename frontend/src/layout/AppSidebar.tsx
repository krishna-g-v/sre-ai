import { Box, Chip, Drawer, List, ListItemButton, ListItemIcon, ListItemText, Toolbar, Typography, useMediaQuery, useTheme } from "@mui/material";
import DashboardIcon from "@mui/icons-material/DashboardOutlined";
import NotificationsIcon from "@mui/icons-material/NotificationsOutlined";
import SmartToyIcon from "@mui/icons-material/SmartToyOutlined";
import MenuBookIcon from "@mui/icons-material/MenuBookOutlined";
import ChatIcon from "@mui/icons-material/ChatBubbleOutlineOutlined";
import SettingsIcon from "@mui/icons-material/SettingsOutlined";
import ShieldIcon from "@mui/icons-material/ShieldOutlined";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const DRAWER_WIDTH = 260;

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/dashboard", label: "Dashboard", icon: <DashboardIcon fontSize="small" /> },
  { path: "/alerts", label: "Alert Incidents", icon: <NotificationsIcon fontSize="small" /> },
  { path: "/agents", label: "SRE Agent Studio", icon: <SmartToyIcon fontSize="small" /> },
  { path: "/knowledge-base", label: "Knowledge Base", icon: <MenuBookIcon fontSize="small" /> },
  { path: "/chat", label: "Assistant", icon: <ChatIcon fontSize="small" /> },
  { path: "/settings", label: "My AWS Accounts", icon: <SettingsIcon fontSize="small" /> },
];

interface Props {
  mobileOpen: boolean;
  onClose: () => void;
}

export default function AppSidebar({ mobileOpen, onClose }: Props) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  const content = (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar />
      <Box sx={{ p: 2, overflowY: "auto" }}>
        <Box
          sx={{
            bgcolor: "action.hover",
            borderRadius: "10px",
            p: 1.5,
            mb: 3,
            border: 1,
            borderColor: "divider",
          }}
        >
          <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 0.5 }}>
            <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase" letterSpacing={0.5}>
              Access Level
            </Typography>
            <Chip
              label={user?.isSuperuser ? "ADMIN" : "USER"}
              size="small"
              color={user?.isSuperuser ? "primary" : "default"}
              sx={{ height: 18, fontSize: 10, fontWeight: 700 }}
            />
          </Box>
          <Typography variant="body2" fontWeight={700} noWrap>
            {user?.displayName}
          </Typography>
        </Box>

        <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase" letterSpacing={0.5} sx={{ px: 1.5 }}>
          Platform Views
        </Typography>
        <List sx={{ mb: 2 }}>
          {NAV_ITEMS.map((item) => {
            const selected = location.pathname.startsWith(item.path);
            return (
              <ListItemButton
                key={item.path}
                selected={selected}
                onClick={() => {
                  navigate(item.path);
                  onClose();
                }}
                sx={{
                  borderRadius: "8px",
                  mb: 0.5,
                  "&.Mui-selected": {
                    bgcolor: "primary.main",
                    color: "primary.contrastText",
                    "&:hover": { bgcolor: "primary.dark" },
                    "& .MuiListItemIcon-root": { color: "inherit" },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: selected ? "inherit" : "text.secondary" }}>{item.icon}</ListItemIcon>
                <ListItemText primaryTypographyProps={{ fontSize: 13, fontWeight: selected ? 700 : 500 }}>{item.label}</ListItemText>
              </ListItemButton>
            );
          })}
        </List>

        {user?.isSuperuser && (
          <>
            <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase" letterSpacing={0.5} sx={{ px: 1.5 }}>
              Administration
            </Typography>
            <List>
              <ListItemButton
                selected={location.pathname.startsWith("/admin")}
                onClick={() => {
                  navigate("/admin");
                  onClose();
                }}
                sx={{
                  borderRadius: "8px",
                  mt: 0.5,
                  "&.Mui-selected": {
                    bgcolor: "primary.main",
                    color: "primary.contrastText",
                    "&:hover": { bgcolor: "primary.dark" },
                    "& .MuiListItemIcon-root": { color: "inherit" },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: location.pathname.startsWith("/admin") ? "inherit" : "text.secondary" }}>
                  <ShieldIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText primaryTypographyProps={{ fontSize: 13, fontWeight: 600 }}>Users &amp; Groups</ListItemText>
              </ListItemButton>
            </List>
          </>
        )}
      </Box>
    </Box>
  );

  if (isMobile) {
    return (
      <Drawer variant="temporary" open={mobileOpen} onClose={onClose} ModalProps={{ keepMounted: true }} sx={{ "& .MuiDrawer-paper": { width: DRAWER_WIDTH } }}>
        {content}
      </Drawer>
    );
  }

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: DRAWER_WIDTH,
        flexShrink: 0,
        "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" },
      }}
    >
      {content}
    </Drawer>
  );
}
