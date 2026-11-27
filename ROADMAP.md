# Roadmap

**Policy-first enrichment.** The goal is not to out-feature Comfy's official
`comfy-mcp`; it is to be the MCP server you can point at a shared ComfyUI and
defend in a review.

Last updated: 2026-11-27 · Tracking issue:
[#214](https://github.com/hybridindie/comfyui_mcp/issues/214)

## Baseline (measured 2026-11-27)

- 53 tools, 5 resources, 4 prompts, ~8.9k LOC, 664 tests.
- Tool surface: ~33.3k chars (~8.3k tokens) per `tools/list`.
- Verified against ComfyUI **v0.46.3** — the newest tag; GitHub's "latest
  release" object is v0.46.0 because 0.46.1–3 were tagged without releases.
- 15/15 read-only client probes and a model-free execution round trip
  (`/prompt` → `/api/jobs` → `/history` → `/view`) pass against 0.46.3.
- Side-by-side with the official server:
  [docs/site/comparison.md](docs/site/comparison.md).

## Decisions

| Decision | Choice | Why |
|---|---|---|
| HTTP auth | Static bearer token first; a reverse proxy owns TLS and OIDC | Smallest safe step; no identity provider to operate |
| Multi-replica | Not a goal | Single-tenant per process stays the documented boundary |
| Policy file | Thin slice first | Unattended enforce has to work before the schema gets expressive |
| Core tool profile | Opt-in, after policy | Measure the need before changing the default surface |

## P0 — close gaps we already promise

| Issue | Item | Why now |
|---|---|---|
| [#205](https://github.com/hybridindie/comfyui_mcp/issues/205) | Consent before third-party code | Node installs run `pip` plus the pack's install script with no confirmation; the official server elicits and fails closed for this, and #142 promised enforce-mode gating for settings mutations |
| [#206](https://github.com/hybridindie/comfyui_mcp/issues/206) | Re-inspect the post-replacement graph | Documented residual bypass: `/node_replacements` can swap in a dangerous class after vetting |
| [#207](https://github.com/hybridindie/comfyui_mcp/issues/207) | Authentication for Streamable HTTP | We position for remote/shared/Docker; the current HTTP mode warns that it is unauthenticated |
| [#208](https://github.com/hybridindie/comfyui_mcp/issues/208) | Audit rotation and retention | Unbounded audit file on long-running deployments |

## P1 — durability

| Issue | Item | Why now |
|---|---|---|
| [#209](https://github.com/hybridindie/comfyui_mcp/issues/209) | Nightly compatibility probe | CI is fully mocked; drift was found by hand after five releases |
| [#210](https://github.com/hybridindie/comfyui_mcp/issues/210) | Elicitation on the sessionless protocol era | Enforce mode depends on `ctx.elicit()`, which the 2026-07-28 era cannot raise |

## P2 — enrichment bets

| Issue | Item | Why now |
|---|---|---|
| [#211](https://github.com/hybridindie/comfyui_mcp/issues/211) | Declarative workflow policy file | Turns binary enforce into CI-safe, expressible policy — the thing the official server structurally cannot do |
| [#212](https://github.com/hybridindie/comfyui_mcp/issues/212) | Core tool profile | 8.3k tokens and 53 tools is a real context and damage surface |

## Candidate backlog (open an issue when picked up)

- **Shared rate limiting** — only if multi-replica becomes a goal; in-process
  buckets multiply the effective quota per replica.
- **Metrics and OTel audit export** — calls by tool, rate-limit rejects,
  audit-write failures, queue depth.
- **Tamper-evident audit** — `prev_hash`/`hash` per record plus an
  `audit verify` command.
- **Outputs and jobs resources** — browse state over `comfyui://` without a
  tool call.
- **Bounded batch generation** — prompt/seed matrix with one `prompt_id` per
  variant.
- **Pre-install pack check** — resolve registry requirements and node impact
  before `install_custom_node`.
- **Asset export** — `/api/assets/export` zip for remote clients, after the
  path and size policy exists.

## Non-goals

- **Lifecycle management** (launch, stop, restart, update, version switch) —
  `comfy-cli` and the official server own it; it conflicts with "connect to
  a URL".
- **Partner/cloud generation, billing, credits** — the Comfy Cloud MCP owns it.
- **Template gallery, slot editing, graph routing** — Comfy owns the gallery;
  chasing it is the treadmill.
- **Multi-tenant SaaS** — one process per tenant stays the boundary.
- **A built-in web UI.**

## Sequencing

1. Land the positioning/currency docs ([#204](https://github.com/hybridindie/comfyui_mcp/issues/204))
   and this roadmap ([#213](https://github.com/hybridindie/comfyui_mcp/issues/213)).
2. **#205 + #206** — small, test-pinned security wins; no tool-schema changes.
3. **#209** — compatibility automation before adding more surface.
4. **#207** — needs a one-page design note (token storage, identity, bind guard).
5. **#211** — design issue, then a thin vertical slice
   (`deny_nodes` + `on_warning`).
6. **#208**, then re-evaluate **#210** and **#212** against use.

## Gates

Every item follows the repo pipeline: issue → red test → green code →
preflight → PR (closes the issue) → review comments resolved → squash merge.

- Run the **Phase 4 eval** before merging anything that changes a tool
  description, parameter schema, or return shape (rule 22).
- Extend `tests/test_security_invariants.py` whenever an enforcement path
  moves; the invariant is "enforced for every call", not "written inline".
- Re-run the compatibility probe for any change touching `client.py` or the
  security modules that read live state.
- Update `README.md`, `CHANGELOG.md`, and the docs site when a contract,
  default, or setup step changes.
