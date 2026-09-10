# Access Control & RAG Design

See [[00-overview]] and [[01-architecture]] for context. See [[05-auth-and-users]] for the user/group data model itself.

## 1. Dynamic groups model (recap)

There is no fixed role enum. A **group** is just a named tag (e.g. `project-atlas`, `platform-core`, `sre-oncall`). Any user can belong to any number of groups. Every user also has an `is_superuser` boolean (see [[05-auth-and-users]]) independent of group membership.

Document (and, later, dashboard/integration) access is derived purely from: *does the requesting user belong to at least one group that this resource is tagged with?* Superusers can see/manage everything regardless of their own group memberships.

## 2. Document metadata & tagging

Every ingested document gets, at minimum:

```
document:
  id: uuid
  title: string
  source_filename: string
  uploaded_by: user_id
  uploaded_at: timestamp
  owner_scope: "group" | "personal"
  group_ids: [group_id]        # empty if owner_scope == "personal"
  personal_owner_id: user_id   # set only if owner_scope == "personal"
  content_type: "pdf" | "docx" | "md" | "txt"
  status: "processing" | "ready" | "failed"
  tags: [string]                # free-form, in addition to group_ids (e.g. "runbook", "onboarding")
  chunk_strategy: "whole_document" | "best_effort"        # see §3
  best_effort_target_size: "small" | "medium" | "large" | null  # only set when chunk_strategy == best_effort
```

- **Group documents** (`owner_scope: group`) must have at least one `group_ids` entry, set at upload time by whoever uploads it (any member of that group, or a superuser uploading on a group's behalf).
- **Personal documents** (`owner_scope: personal`) belong to exactly one user's personal knowledge base and are never visible to anyone else, including via group logic — only that user (or a superuser browsing for admin purposes, if that's later decided) can retrieve them.
- A document can be tagged into **multiple** groups.

## 3. Chunking strategy (ingestion-time, configurable)

Chosen model for inference is **Llama 4 Scout**, which has a large context window — large enough that a full 10–20 page document fits comfortably as a single piece of context. That makes "whole document as one chunk" a genuinely viable default for this document size, not just a fallback. See [[00-overview]] decision log and [[06-deployment-and-environments]].

Ingestion supports two chunking strategies. Neither uses exact token/character counts as a user-facing setting — the target sizes are qualitative, and the actual splitter picks natural boundaries (headings, paragraphs, sections) rather than hard-cutting mid-sentence:

```
chunk_strategy: "whole_document" | "best_effort"
best_effort_target_size: "small" | "medium" | "large"   # only meaningful when strategy == best_effort
```

- **`whole_document`**: the entire parsed document text becomes a single `kb.chunks` row (`chunk_type = whole_document`). Best suited to the common case here (short docs, large-context model) — retrieval can hand the model the complete document when it's the relevant one, with no risk of losing context via a bad split.
- **`best_effort`**: the document is split into multiple chunks sized approximately to the chosen qualitative target (`small`/`medium`/`large`), snapped to the nearest natural boundary. Better suited to longer documents, or documents made of many loosely-related sections where whole-document retrieval would pull in a lot of irrelevant text for a narrow query.

**Configuration scope** (decision recorded in [[00-overview]]): a system-wide default (set in an ingestion settings screen — see [[04-frontend-ui]]) applies to new uploads, with an explicit per-document override available at upload time for the person doing the upload.

## 4. Retrieval must mix chunk types and documents — not default to "summarize the whole doc"

A key requirement: **the presence of `whole_document` chunks must not turn every answer into "here's a summary of the document."** The retrieval/answer flow must still behave like real RAG:

- For a **general (non-pinned) query**, retrieval ranks and combines whatever chunks are most relevant to the actual question — this can be a mix of `whole_document` chunks from one document and `best_effort` chunks from others, across multiple documents, exactly as normal semantic search would produce. The model is expected to extract the specific answer from within a `whole_document` chunk, not summarize it wholesale, unless the user actually asked for a summary.
- For a **document-pinned session** (see [[08-chat-sessions-and-orchestration]]), retrieval is scoped to that single document's chunk(s) only — but if that document was ingested as `best_effort` (multiple chunks), the agent still retrieves and reasons over the specific relevant chunk(s) for the question asked, not the entire document by default.
- This behavior is a prompting/retrieval-logic requirement on `backend`, not a storage-layer concern — §3 just determines what chunk granularities exist to choose from.

## 5. Embedding model (local, baked into the Docker image)

Document ingestion (and query-time embedding) uses a **local embedding model**, not a hosted API — the corporate network does not allow reaching Hugging Face at runtime. This is separate from [[00-overview]]'s LLM choice (Llama 4 Scout, via a generic OpenAI-compatible adapter in dev / Bedrock in prod, used for chat completions/reasoning) — embeddings are a different, much smaller model, run in-process inside the backend.

- **Model**: `BAAI/bge-large-en-v1.5` — open weights, MIT license, 1024-dim output, strong retrieval quality for its size, and fast enough on CPU for this workload's volume (small documents, no GPU assumed in prod — see [[06-deployment-and-environments]]).
- **Scope decision**: only the embedding step is local-model-based. Text extraction from PDF/DOCX/Markdown/TXT uses standard non-ML parsing libraries (e.g. PyPDF/pdfplumber, python-docx, a markdown parser) — no ML model needed there for v1's plain, text-based documents.
- **Language**: English-only is the assumed scope for both documents and queries (decision recorded in [[00-overview]]); `bge-large-en-v1.5` is English-optimized, not multilingual.
- **Consistency requirement**: the exact same model (and same pooling/normalization settings) must be used for both ingesting documents and embedding incoming chat queries at retrieval time — mismatched embedding spaces silently break vector similarity search.
- See [[06-deployment-and-environments]] for how the model weights get into the Docker image and the runtime env vars involved.

## 6. pgvector schema layout

Single PostgreSQL instance (RDS in prod), two logical schemas:

### `kb` schema — document knowledge base
- `kb.documents` — metadata table as in §2.
- `kb.chunks` — `id, document_id, chunk_index, chunk_type ("whole_document" | "best_effort"), content, embedding vector(1024), token_count`. A `whole_document`-strategy document produces exactly one row here; a `best_effort`-strategy document produces many, each tagged `chunk_type = best_effort` so retrieval knows what granularity it's mixing (§4).
- Retention: indefinite (documents live until explicitly deleted by an owner/superuser).

### `ops` schema — operational / log data for day-to-day SRE activity
- `ops.sources` — registered ingestion sources (e.g. "eks-cluster-prod-1 log stream", "cloudwatch export job").
- `ops.events` — `id, source_id, occurred_at, raw_content, embedding vector(1024), metadata jsonb` (metadata carries cluster/namespace/pod/severity/etc. as applicable).
- Retention: TTL-based (e.g. rolling N days — exact window is an infra/ops decision, keep it config-driven, not hardcoded), since this is high-volume operational data, not durable knowledge.

`vector(1024)` matches the local embedding model's output dimension (§5). Both schemas use the same embedding model, so cross-schema similarity comparisons (if ever needed) stay meaningful. Keeping both schemas in one Postgres instance (decision recorded in [[00-overview]]) means one set of credentials/connection pooling to operate, while retention jobs, indexing strategy, and access patterns stay independent per schema.

## 7. Retrieval scoping (access control, query time)

Per the decision in [[00-overview]], retrieval is **combined automatically** — no manual scope toggle in v1:

```sql
-- Conceptual filter applied to kb.documents before/with the vector search
WHERE (owner_scope = 'group' AND group_ids && :user_group_ids)
   OR (owner_scope = 'personal' AND personal_owner_id = :user_id)
```

The RAG agent (see [[03-agent-and-integrations]]) always applies this filter — it is never optional and never bypassable by prompt content. This is the core security boundary of the system: **filter at the query layer, not by trusting the LLM to only mention things it should.**

`ops` schema retrieval (for live investigation queries) is scoped by which integrations/clusters/accounts the user's groups grant access to (see [[03-agent-and-integrations]] for how group-to-integration-scope mapping works) rather than per-document tags.

## 8. Admin / superuser document & group management

Superusers get an admin UI (see [[04-frontend-ui]]) to:
- Create/rename/delete groups.
- Add/remove users from groups.
- Grant/revoke the `is_superuser` flag on other users.
- Re-tag or delete any document (group or personal), and change its chunking strategy (triggers re-ingestion).
- Set the system-wide default chunking strategy (§3).
- View which groups exist and how many documents/members each has.

Non-superuser users can:
- Upload documents into any group they already belong to, choosing to accept the default chunking strategy or override it for that upload.
- Manage (upload/delete) their own personal KB documents.
- **Cannot** create new groups or add themselves/others to a group they're not already in — that requires a superuser (prevents self-service privilege escalation into another team's docs).

## 9. Personal knowledge base

Each user implicitly has exactly one personal KB (no explicit "create a KB" step — it exists as soon as they upload their first personal document). The UI's knowledge-base management screen shows, per user: their personal documents, and (read-only list, or upload if they belong to the group) documents in each group they belong to.
