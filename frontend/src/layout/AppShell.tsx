import { useState } from "react";
import { Box, Toolbar } from "@mui/material";
import { Outlet } from "react-router-dom";
import AppHeader from "./AppHeader";
import AppSidebar from "./AppSidebar";

export default function AppShell() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <Box sx={{ display: "flex", height: "100vh", bgcolor: "background.default" }}>
      <AppHeader onToggleMobileNav={() => setMobileNavOpen((o) => !o)} />
      <AppSidebar mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <Box component="main" sx={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, height: "100vh" }}>
        <Toolbar />
        <Box sx={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
          <Outlet />
        </Box>
      </Box>
    </Box>
  );
}
