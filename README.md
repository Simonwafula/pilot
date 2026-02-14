# pilot-core

Clean-room reimplementation of the core idea behind agent workflow products:
- persistent task lifecycle state,
- explicit quality gates,
- resumable handoffs,
- provider adapters (Codex and OpenCode).

No proprietary components are required.

## Run Without Install (recommended)

```bash
./pilot --help
```

## Optional Install (editable)

If your environment has `setuptools` available:

```bash
python3 -m pip install -e . --no-build-isolation
```

## Using In Other Codebases

`pilot` is repo-local by design, so you can use it across many codebases.
Each repository keeps its own workflow state under `.pilot/`.

Install once from this repo:

```bash
python3 -m pip install -e /path/to/pilot --no-build-isolation
```

Then inside any target repository:

```bash
cd /path/to/target-repo
pilot init --provider codex      # or: opencode
pilot doctor
pilot sync
```

If `pilot` resolves to another tool on your machine, use this project's alternate command:

```bash
pilot-core init --provider codex
pilot-core doctor
pilot-core sync
```

For an already implemented app/codebase:

```bash
pilot audit --workspace
```

Note:
- `pilot verifier` requires the target repository to be a git repo.

## Quick Start

```bash
./pilot init --provider codex
./pilot new "Build authentication endpoint"         # phase=discover
./pilot spec advance --task-id <task_id>            # discover -> plan
./pilot plan <task_id> "Design request/response schema"
./pilot plan-ai <task_id> --dry-run                 # AI planning assist (high-reasoning profile)
./pilot suggest "Auth rollout" "Proposed auth approach" --task-id <task_id>
./pilot challenge <idea_id> --persona "Dr. Scrutiny"
./pilot reply <idea_id> --persona "Dr. Scrutiny" --response "Assumption validated via tests."
./pilot spec advance --task-id <task_id>            # plan -> implement
./pilot run <task_id> --dry-run
./pilot tdd red <task_id>
./pilot tdd green <task_id>
./pilot tdd refactor <task_id>
./pilot check <task_id> --dry-run
./pilot verify <task_id>
./pilot auto <task_id>
./pilot audit <task_id>
./pilot audit-ai <task_id> --dry-run                # AI audit assist (high-reasoning profile)
./pilot spec set complete --task-id <task_id>       # requires passing quality gates
./pilot handoff <task_id>
./pilot resume <task_id>
```

## Workflow Model

Task statuses:
- `planned`
- `in_progress`
- `blocked`
- `verifying`
- `completed`

Task phases (`pilot spec` enforces these gates):
- `discover`
- `plan`
- `implement`
- `verify`
- `complete`

Task data lives in `.pilot/tasks/<task_id>.json`.

Phase commands:

```bash
./pilot spec status --task-id <task_id>
./pilot spec advance --task-id <task_id>
./pilot spec set verify --task-id <task_id>
./pilot spec set complete --task-id <task_id>       # blocked if gates fail
./pilot spec set discover --task-id <task_id> --force
```

## Quality Gates

Edit `.pilot/config.json` and set project-specific commands:

```json
{
  "provider": "codex",
  "quality_gates": [
    { "name": "format", "command": "ruff format ." },
    { "name": "lint", "command": "ruff check ." },
    { "name": "test", "command": "pytest -q" }
  ],
  "pre_edit_hooks": ["ruff check ."],
  "post_edit_hooks": ["ruff check .", "pytest -q"],
  "provider_profiles": {
    "plan": {
      "codex": { "model": "gpt-5.3-codex", "reasoning_effort": "high" },
      "opencode": { "model": "glm-5", "variant": "max", "thinking": "true" }
    },
    "audit": {
      "codex": { "model": "gpt-5.3-codex", "reasoning_effort": "xhigh" },
      "opencode": { "model": "glm-5", "variant": "max", "thinking": "true" }
    },
    "verifier": {
      "codex": { "model": "gpt-5.3-codex", "reasoning_effort": "xhigh" },
      "opencode": { "model": "glm-5", "variant": "max", "thinking": "true" }
    },
    "implement": {
      "codex": { "model": "gpt-5.3-codex", "reasoning_effort": "medium" },
      "opencode": { "model": "glm-4.7", "variant": "medium" }
    }
  }
}
```

Then run:

```bash
./pilot check <task_id>
./pilot verify <task_id>
```

Completion gate:
- moving to phase `complete` requires the latest run of each configured quality gate to be passing.
- moving to phase `complete` is blocked when task status is `blocked` (unless `--force` is used).
- moving to phase `implement` requires at least one plan step and a passed idea pipeline for the task.
- moving to phase `verify` and `complete` requires a completed TDD cycle (`red -> green -> refactor`) unless `--force`.

`verify` command behavior:
- runs quality gates like `check`
- if all pass and phase is `verify`, it attempts `verify -> complete`
- if phase is not `verify`, it keeps status updated and skips completion

## Provider Adapters

`./pilot init --provider codex|opencode` scaffolds:
- `.pilot/config.json`
- `.pilot/templates/agent-rules.md`
- `AGENTS.md` managed block for instruction integration

Use `./pilot handoff` to produce resumable handoff markdown and `./pilot resume` to print a provider-specific resume prompt.

## Provider Runs

Run your configured provider directly:

```bash
./pilot run <task_id>
./pilot run <task_id> --extra "Focus on smallest safe patch."
./pilot run <task_id> --timeout 1200
```

Behavior:
- Uses provider from `.pilot/config.json` (`codex` or `opencode`)
- Auto-creates handoff file if missing
- Generates a resume prompt with execution contract
- Executes provider CLI and stores report JSON in `.pilot/reports/`
- Appends run metadata to the task JSON
- Runs configured `pre_edit_hooks` before provider execution and `post_edit_hooks` after successful provider execution
- Marks task as `blocked` if any hook fails

## AI Assist Modes

Provider-assisted planning and audit with context-specific profiles:

```bash
./pilot plan-ai <task_id>
./pilot plan-ai <task_id> --dry-run
./pilot audit-ai <task_id>
./pilot audit-ai --workspace
./pilot audit-ai <task_id> --dry-run
```

Behavior:
- `plan-ai` uses the `plan` provider profile and returns actionable plan guidance
- `audit-ai` uses the `audit` provider profile and analyzes local audit output
- default routing:
- `codex`: `gpt-5.3-codex` high/xhigh for plan/audit/verifier, `gpt-5.3-codex` medium for implement
- `opencode`: `glm-5` for plan/audit/verifier, `glm-4.7` for implement
- profiles can be overridden in `provider_profiles`

## TDD Loop

Run and persist strict RED/GREEN/REFACTOR checkpoints:

```bash
./pilot tdd status <task_id>
./pilot tdd red <task_id>       # expects test gate to fail
./pilot tdd green <task_id>     # expects test gate to pass
./pilot tdd refactor <task_id>  # expects all quality gates to pass
```

Behavior:
- requires a quality gate named `test` for `red` and `green`
- stores cycle history in task state (`tdd_cycles`)
- blocks phase transitions to `verify`/`complete` until a cycle is completed

## Idea Modes

Run all ideas through feature suggestion mode and devil's advocate mode:

```bash
./pilot suggest "<title>" "<proposal>" --task-id <task_id>
./pilot challenge <idea_id>
./pilot challenge <idea_id> --persona "Dr. Scrutiny" --persona "Professor Simplex"
./pilot reply <idea_id> --persona "Dr. Scrutiny" --response "<response>"
./pilot ideas --task-id <task_id>
./pilot idea-show <idea_id>
```

Persistence:
- idea records are stored in `.pilot/ideas/<idea_id>.json`
- human-readable reports are stored in `.pilot/ideas/<idea_id>.md`
- each record includes suggestions, crucible critiques, synthesis, and persona replies

## Auto Pipeline

Run phased orchestration from current phase to completion:

```bash
./pilot auto <task_id>
./pilot auto <task_id> --extra "Keep patches minimal"
./pilot auto <task_id> --timeout 1800
./pilot auto <task_id> --skip-run
./pilot auto <task_id> --skip-verify
./pilot auto <task_id> --force
```

Behavior:
- `discover -> plan -> implement -> verify -> complete`
- executes provider run in `implement` unless `--skip-run`
- executes verification/completion in `verify` unless `--skip-verify`
- stops immediately on provider or verification failure
- requires at least one plan step in `plan` phase unless `--force`
- requires idea pipeline compliance for task-linked ideas (`suggest -> challenge -> reply`) before entering `implement` unless `--force`
- requires completed TDD cycle before entering `verify` unless `--force`

## Audit

Confirm workflow completion or assess an existing codebase after dropping in pilot:

```bash
./pilot audit <task_id>
./pilot audit <task_id> --strict
./pilot audit --workspace
./pilot audit --workspace --fix --provider opencode
```

Behavior:
- task audit checks completion status/phase, idea pipeline compliance, TDD cycle completion, edit hook health, quality readiness, handoff, and provider run history
- workspace audit checks pilot scaffolding and quality-gate health for already implemented apps
- runs quality gates by default (disable with `--no-run-gates`)
- `--strict` fails audit when warnings are present
- supports JSON output with `--json`

## Doctor

Check local prerequisites and configuration:

```bash
./pilot doctor
./pilot doctor --json
./pilot doctor --fix
./pilot doctor --fix --provider opencode
```

Checks include:
- workspace and report directory health
- provider executable resolution and `--help` invocation
- quality gate command executable availability

`--fix` applies safe remediations first:
- create/repair `.pilot/config.json`
- normalize invalid provider values
- repair malformed quality gate entries
- regenerate `.pilot/templates/agent-rules.md`
