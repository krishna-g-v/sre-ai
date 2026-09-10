# Auth & User Model

See [[00-overview]] and [[02-access-control-and-rag]].

## 1. v1 login flow (intentionally simple)

- Username + password only. **No hashing/encryption in v1** — this is an explicit, deliberate simplification for the initial build, not an oversight. Passwords are stored and compared as plaintext in the `users` table.
  - This must be clearly called out in code comments and in this doc so nobody mistakes it for a bug later, and so it's easy to find and replace when hardening the auth layer.
- On successful login, backend issues a **JWT** containing `user_id`, `username`, `group_ids`, `is_superuser`, with a reasonable expiry (e.g. 8–24h). Frontend stores it and sends `Authorization: Bearer <token>` on every request.
- No refresh-token flow needed for v1 — on expiry, the user just logs in again.
- No rate limiting, no MFA, no account lockout in v1.

## 2. Data model

```
users:
  id: uuid
  username: string (unique)
  password: string        # plaintext for v1 — see note above
  display_name: string
  is_superuser: boolean
  created_at: timestamp

groups:
  id: uuid
  name: string (unique)
  description: string
  created_at: timestamp

user_group_memberships:
  user_id: uuid (fk -> users.id)
  group_id: uuid (fk -> groups.id)
  # composite PK (user_id, group_id)
```

No separate "role" table/enum — groups themselves carry all authorization meaning (see [[02-access-control-and-rag]]). `is_superuser` is the only special flag, orthogonal to group membership.

## 3. Bootstrapping

Since there's no fixed role model, the very first superuser must be created out-of-band (e.g. a seed script / DB migration that inserts one superuser account, or an env-var-driven `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` that the backend ensures exists on startup if no superuser exists yet). Define the exact mechanism in `backend` when building auth, but it must not require manual SQL in production.

## 4. Future: Microsoft Entra ID

Explicitly deferred (see [[00-overview]]), but the auth layer should be structured so this swap is additive, not a rewrite:

- Keep an internal `users` table as the source of truth for group membership and `is_superuser` regardless of how identity is verified.
- The login flow should be behind a single `AuthProvider` abstraction (interface) with one implementation today: `LocalPasswordAuthProvider`. Adding `EntraIdAuthProvider` later (OIDC flow, mapping Entra groups/claims to local `groups`, or just matching on username/email to provision a local user record on first SSO login) should not require touching the JWT issuance, the group model, or the RAG access-control filter.
- Do not build anything today that assumes passwords are the only possible credential (e.g. don't hardcode a password field as required at the DB level if it can be reasonably left nullable for future SSO-only accounts) — but don't over-engineer this either; a simple provider interface is enough for v1.
