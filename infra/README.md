# infra

Deployment configuration for the SRE Agent. Part of the `sre-ai` monorepo — requirements/architecture docs live in [`../docs/`](../docs/00-overview.md), not here.

- **Local dev**: `docker-compose/` (Docker Compose stack for Ubuntu VM dev). Copy `docker-compose/.env.example` to `docker-compose/.env` and fill in real values — `.env` is git-ignored, never commit it.
- **Production**: `eks/` (Kubernetes manifests/Helm) and `terraform/` (RDS, IAM, networking) for AWS EKS + RDS.
