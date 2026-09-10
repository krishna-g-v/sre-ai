/**
 * Production server — NOT used for local dev (that's `vite --host`, see the dev
 * Dockerfile). Serves the built static assets and proxies /api/* to the backend.
 *
 * Why a server at all, rather than a static host: this frontend's `ClusterIP`-only
 * backend Service (`sre-ai-backend`, no Ingress — see infra Helm values) is only
 * reachable from inside the cluster. The browser can never resolve or reach it
 * directly. Vite's own env vars are baked in at *build* time, so they can't carry a
 * runtime, per-environment value like the K8s Service DNS name either. Running a small
 * Node server alongside the static files lets it read BACKEND_URL from its actual
 * container environment at request time and proxy server-to-server — the only leg of
 * this that ever needs to reach `sre-ai-backend:8000` is this process, not the browser.
 * As a side effect, the browser only ever talks to one origin, so CORS doesn't apply.
 */
import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import path from "path";

const PORT = Number(process.env.PORT) || 3000;
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const app = express();

app.use(
  "/api",
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    // Express strips the "/api" mount prefix from req.url before this middleware ever
    // sees it (e.g. "/api/auth/login" arrives here as "/auth/login") — the backend's own
    // routes are themselves mounted under /api (see backend/app/main.py), so without this
    // rewrite every proxied request would 404 against the backend.
    pathRewrite: { "^/": "/api/" },
  }),
);

// esbuild bundles this file to dist/server.cjs, sitting alongside the static assets
// vite build also puts in dist/ — so __dirname at runtime is that same dist/ folder.
const staticDir = __dirname;

app.use(express.static(staticDir));

// SPA fallback: any non-file, non-/api route serves index.html so client-side routing
// (react-router) can take over.
app.get("*", (_req, res) => {
  res.sendFile(path.join(staticDir, "index.html"));
});

app.listen(PORT, () => {
  console.log(`sre-ai-frontend listening on :${PORT}, proxying /api -> ${BACKEND_URL}`);
});
