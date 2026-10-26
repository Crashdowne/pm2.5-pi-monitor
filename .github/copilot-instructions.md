# Copilot instructions

<!-- agent-bootstrap:start v7 -->

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

### Automatic commits and CI

- For completed, verified work in the user's repositories, automatically commit task-owned changes, push the current branch to its GitLab `origin`, and verify GitLab CI before reporting completion. This standing authorization applies to existing and new repositories; no separate commit or push request is needed.
- Before committing, review the diff, run the repository's relevant tests, lint and build checks, run `git diff --check`, and finish docs sync. Stage only task-owned changes; never sweep in unrelated edits, pre-existing staged changes, secrets, or another session's work.
- Ensure a real root `.gitlab-ci.yml` covers the project checks on branch and tag pushes. Review generated starters before committing them. For a new repository, establish its GitLab `origin` and pipeline before claiming remote CI works.
- After each push, capture `git rev-parse HEAD`, run `gitlab-ci wait`, and verify results belong to that exact commit. A missing, skipped, cancelled, timed-out, or failed required check is not a pass. Inspect failures with `gitlab-ci logs <job-id>`, fix task-caused failures, rerun local checks, commit and push the fix, and wait again.
- Do not auto-commit or push unfinished work, failing checks, read-only requests, or when the user says not to commit/push. Respect repository opt-outs and explicit approval gates. Never force push, bypass hooks, amend without permission, or create empty commits. If scope, credentials, remote, mirror, or CI tooling blocks completion, preserve the work and report the exact blocker; do not claim CI passed.

### Git hosting and CI: self-hosted GitLab

- GitLab CE 19.5.1 at https://gitlab.ariverse.ca is the primary host; repos are `ari/<name>`. Use HTTPS `origin` = `https://gitlab.ariverse.ca/ari/<name>.git`; credentials use the `osxkeychain` git helper and `glab` is logged in. A `github` remote may remain for reference. GitLab push-mirrors to GitHub `Crashdowne/<name>`; never push to GitHub directly.
- Create repos on GitLab (`git push` to that URL creates a private project, or `glab repo create`). If GitHub is needed, create its repo and add a GitLab push mirror.
- CI, builds, releases, and deploys use root `.gitlab-ci.yml`. Never add `.github/workflows/` or `.gitea/workflows/`; convert existing files to `.gitlab-ci.yml` and delete the old ones. Gitea (`git.ariverse.ca`) and `gitea-ci` are retired.
- Every job sets `tags:` with exactly one tag. `ubuntu-latest`: Docker executor on the GitLab server (`servy-docker`, Linux amd64). Set `default: image: catthehacker/ubuntu:act-latest` (node, python3, git, jq) or a job `image:`; the runner default is bare `alpine`. No `docker` commands, and jobs cannot reach `https://gitlab.ariverse.ca` (API, registry, releases); instance CI variables rewrite git clones to `http://gitlab`. `macos-arm64`: Mac Studio shell executor for Xcode, signing, docker CLI, registry pushes, releases, and deploys to the Mac; only while Ari is logged in. Untagged jobs land on the server runner.
- Run pipelines on every branch/tag push; use `workflow: rules:` to skip `merge_request_event` duplicates. Allow manual runs with `rules: - if: $CI_PIPELINE_SOURCE =~ /^(web|api)$/`.
- Store secrets as masked GitLab CI/CD variables via `glab variable set`; protect variables used only on protected branches/tags. Registry: `$CI_REGISTRY_IMAGE`, `$CI_REGISTRY_USER`/`$CI_REGISTRY_PASSWORD`. Releases: GitLab Releases API with `JOB-TOKEN: $CI_JOB_TOKEN`.
- After pushing, run `gitlab-ci wait` (HEAD's pipeline; exit 0 means all passed). Use `gitlab-ci status [REF]`, `gitlab-ci logs <job-id>`, `gitlab-ci run --ref <branch> [--var K=V]`, `glab ci view`, or `glab ci lint`. Results: `https://gitlab.ariverse.ca/ari/<name>/-/pipelines`; GitHub never shows them. Local checks remain fine.

<!-- agent-bootstrap:end -->
