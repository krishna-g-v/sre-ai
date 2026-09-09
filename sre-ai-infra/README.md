# sre-ai-infra

Source of truth for requirements/architecture docs and deployment configuration for the SRE Agent project.

- **Requirements & architecture docs**: see [`docs/00-overview.md`](docs/00-overview.md) — start there.
- **Local dev**: `docker-compose/` (Docker Compose stack for Ubuntu VM dev). Copy `docker-compose/.env.example` to `docker-compose/.env` and fill in real values — `.env` is git-ignored, never commit it.
- **Production**: `eks/` (Kubernetes manifests/Helm) and `terraform/` (RDS, IAM, networking) for AWS EKS + RDS.

Related repos (checked out as siblings): `../sre-ai-frontend`, `../sre-ai-backend`.
