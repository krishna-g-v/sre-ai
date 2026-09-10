# Dev-mode image — runs the Vite dev server, per docs/06-deployment-and-environments.md §3
# ("Vite/Next dev server ... in Docker Compose" for local dev). Production serves a static
# build instead (see docs/06 §4) — that Dockerfile/stage gets added alongside the actual
# EKS manifests in infra/eks/.

FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
