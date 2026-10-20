# Copilot instructions

<!-- agent-bootstrap:start v4 -->
## Agent defaults (managed by ~/.copilot/hooks/repo-bootstrap.mjs)

Repo-specific rules go outside this block; edits inside are overwritten. Opt out: set `{"bootstrap": false}` in `.github/docs-sync.json`, then delete this block.

### Responses

- Caveman mode: terse. Answer first, then reason, then next step. No greetings, hedging, recaps, or closers.
- Keep code, commands, paths, numbers, API names, and exact errors verbatim. Keep every `not`, `never`, `no`, and `only` that carries meaning.
- Use normal prose for code, comments, commits, docs, issues, PRs, security warnings, irreversible actions, ordered procedures, or a confused user.
- "stop caveman" or "normal mode" turns this off.

### Start fast

1. Read repo rules outside this block, then `AGENTS.md` if present, for status, blockers, and next steps.
2. If SuperLocalMemory (SLM) tools are available: call `session_init(project_path=<repo root>)` once, then `recall("<task> <area>")` before exploring code.
3. Treat memory as a lead, not proof. Verify with one targeted read before editing. Explore only what docs and memory do not answer.
4. If `recall` returns `abstained` or no confident match, refine the query once; otherwise treat the fact as unknown.

### Leave context for the next agent

- Save only what is costly to rediscover: decisions and why, constraints, gotchas, non-obvious commands, contracts, root causes, blockers.
- Skip what code, git history, or README already show. Never save secrets, tokens, PII, raw logs, or transcripts.
- Make each fact self-contained: name the file, command, or component, state what is true, and say why. Bad: "fixed auth". Good: "`src/auth.ts` refresh fails on localhost until `NGROK_URL` is set; Teams rejects http callbacks."
- SLM: one fact per `remember`, with `project=<repo name>`, tags, and `kind` (`decision`, `rule`, `procedure`, `status`, or `semantic`). Importance 8-10 for blockers, security, and architecture; 5 otherwise.
- `recall` before `remember`. Correct near-duplicates with `update_memory`, or pass `replaces=<fact_id>` when a fact is superseded.
- Before ending meaningful work, save one `kind="status"` memory (done, changed, blocked, next) that replaces the previous status, then call `close_session`.
- Without SLM, put the same handoff in the `docs-sync` brief so it lands in `AGENTS.md`.

### Docs sync

- After a completed code change, run the `docs-sync` subagent before the final answer. Brief it with what changed and why, checks run with results (or "not run"), publish state, gaps, and next step.
- Do not edit status docs yourself; `docs-sync` owns them. Skip it for formatting-only or exploratory work.
- Status doc: `AGENTS.md` if present, otherwise `README.md` only when user-facing behavior, setup, or configuration changed.

### CI and builds: Gitea Actions

- GitHub stays the source of truth. CI, builds, releases, and deploys run on self-hosted Gitea Actions at https://git.ariverse.ca, which syncs this repo's mirror within about 30 seconds of a push.
- Put workflows in `.gitea/workflows/`, never `.github/workflows/`; GitHub Actions costs money. Move any GitHub workflow files you find to `.gitea/workflows/`.
- Use one `runs-on` label: `ubuntu-latest` (Linux container, no `docker` commands) or `macos-arm64` (the Mac Studio with Xcode; runs only while Ari is logged in). Trigger on `push` or `workflow_dispatch`; `pull_request` never fires on the mirror.
- After pushing, run `gitea-ci wait` for the results; `gitea-ci logs <task>` prints a job log, and `gitea-ci run <workflow>.yml` starts a build. Local test and build runs during development are still fine.
<!-- agent-bootstrap:end -->
