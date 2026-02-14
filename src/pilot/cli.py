from __future__ import annotations

import argparse
import json
import secrets
import shlex
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

from .audit import AuditCheck, audit_task, audit_workspace
from .doctor import apply_fixes, run_doctor, summarize
from .ideas import (
    add_reply,
    available_personas,
    create_idea,
    list_ideas as list_idea_records,
    load_idea,
    pending_personas,
    run_crucible,
    task_idea_compliance,
)
from .models import utc_now_iso
from .providers import (
    build_run_prompt,
    default_agent_rules,
    normalize_provider,
    provider_command,
    resolve_provider_settings,
    resume_prompt,
    run_provider_command,
)
from .state import (
    CONFIG_FILE,
    INDEX_DIR,
    REPORTS_DIR,
    ROOT_DIR,
    VERIFIER_DIR,
    create_task,
    ensure_layout,
    handoff_path,
    init_workspace,
    list_tasks,
    load_config,
    resolve_task,
    save_task,
)
from .sync_index import sync_workspace_index
from .verifier import (
    create_worktree,
    ensure_git_repo,
    remove_worktree,
    run_quality_gates_in_dir,
)
from .workflow import (
    SPEC_PHASES,
    VALID_STATUSES,
    add_note,
    add_plan_step,
    advance_phase,
    apply_quality_results,
    phase_report,
    render_handoff,
    run_quality_gates,
    set_phase,
    set_status,
    tdd_readiness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pilot",
        description="Provider-neutral workflow runner for coding agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Initialize .pilot workspace")
    init_cmd.add_argument("--provider", default="codex", choices=["codex", "opencode"])
    init_cmd.add_argument(
        "--force", action="store_true", help="Overwrite .pilot/config.json"
    )

    new_cmd = sub.add_parser("new", help="Create a task")
    new_cmd.add_argument("title", help="Task title")
    new_cmd.add_argument("--id", dest="task_id", help="Optional custom task id")

    plan_cmd = sub.add_parser("plan", help="Append a plan step to a task")
    plan_cmd.add_argument("task_id", help="Task id")
    plan_cmd.add_argument("step", help="Plan step text")

    plan_ai_cmd = sub.add_parser(
        "plan-ai", help="Run provider-assisted planning analysis"
    )
    plan_ai_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    plan_ai_cmd.add_argument("--extra", default="", help="Extra planning instruction")
    plan_ai_cmd.add_argument(
        "--dry-run", action="store_true", help="Print command and prompt only"
    )
    plan_ai_cmd.add_argument(
        "--timeout", type=int, default=0, help="Provider timeout seconds"
    )

    note_cmd = sub.add_parser("note", help="Append a note to a task")
    note_cmd.add_argument("task_id", help="Task id")
    note_cmd.add_argument("text", help="Note text")

    status_cmd = sub.add_parser("set-status", help="Update task status")
    status_cmd.add_argument("task_id", help="Task id")
    status_cmd.add_argument("status", choices=sorted(VALID_STATUSES))

    tasks_cmd = sub.add_parser("tasks", help="List tasks")
    tasks_cmd.add_argument(
        "--all", action="store_true", help="Show completed tasks too"
    )

    show_cmd = sub.add_parser("show", help="Show one task")
    show_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )

    check_cmd = sub.add_parser("check", help="Run quality gates")
    check_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    check_cmd.add_argument("--gate", help="Run one named gate")
    check_cmd.add_argument("--dry-run", action="store_true")

    verify_cmd = sub.add_parser(
        "verify", help="Run quality gates and attempt completion"
    )
    verify_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    verify_cmd.add_argument("--gate", help="Run one named gate")
    verify_cmd.add_argument("--dry-run", action="store_true")
    verify_cmd.add_argument(
        "--force-complete",
        action="store_true",
        help="Force completion transition if needed",
    )

    handoff_cmd = sub.add_parser("handoff", help="Write handoff markdown")
    handoff_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    handoff_cmd.add_argument("--notes", default="", help="Additional handoff notes")

    resume_cmd = sub.add_parser("resume", help="Print resume prompt for provider")
    resume_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )

    spec_cmd = sub.add_parser("spec", help="Manage phase-gated task workflow")
    spec_cmd.add_argument(
        "action", nargs="?", default="status", choices=["status", "advance", "set"]
    )
    spec_cmd.add_argument("phase", nargs="?", choices=SPEC_PHASES)
    spec_cmd.add_argument("--task-id", help="Task id (defaults to latest active task)")
    spec_cmd.add_argument(
        "--force", action="store_true", help="Override transition guardrails"
    )

    run_cmd = sub.add_parser(
        "run", help="Run provider CLI with generated prompt and logging"
    )
    run_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    run_cmd.add_argument(
        "--extra", default="", help="Extra instruction appended to provider prompt"
    )
    run_cmd.add_argument(
        "--dry-run", action="store_true", help="Print command and prompt only"
    )
    run_cmd.add_argument(
        "--timeout", type=int, default=0, help="Timeout seconds (0 means no timeout)"
    )

    sync_cmd = sub.add_parser(
        "sync", help="Build local workspace memory/index for continuity"
    )
    sync_cmd.add_argument(
        "--max-files", type=int, default=800, help="Maximum files to index"
    )
    sync_cmd.add_argument(
        "--max-bytes", type=int, default=250000, help="Maximum bytes per indexed file"
    )
    sync_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    verifier_cmd = sub.add_parser(
        "verifier", help="Run isolated verifier lane in a separate git worktree"
    )
    verifier_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    verifier_cmd.add_argument(
        "--base-ref", default="HEAD", help="Git ref for worktree base"
    )
    verifier_cmd.add_argument(
        "--skip-gates",
        action="store_true",
        help="Skip quality gate execution in verifier lane",
    )
    verifier_cmd.add_argument(
        "--skip-provider",
        action="store_true",
        help="Skip provider review pass in verifier lane",
    )
    verifier_cmd.add_argument(
        "--keep-worktree", action="store_true", help="Keep verifier worktree after run"
    )
    verifier_cmd.add_argument(
        "--dry-run", action="store_true", help="Print commands/prompts only"
    )
    verifier_cmd.add_argument(
        "--timeout", type=int, default=0, help="Provider timeout seconds"
    )

    auto_cmd = sub.add_parser("auto", help="Run end-to-end workflow pipeline")
    auto_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    auto_cmd.add_argument(
        "--extra", default="", help="Extra instruction for provider run"
    )
    auto_cmd.add_argument(
        "--timeout", type=int, default=0, help="Provider run timeout seconds"
    )
    auto_cmd.add_argument(
        "--force",
        action="store_true",
        help="Override blocked transitions when possible",
    )
    auto_cmd.add_argument(
        "--skip-run",
        action="store_true",
        help="Skip provider execution in implement phase",
    )
    auto_cmd.add_argument(
        "--skip-verify", action="store_true", help="Stop before verification/completion"
    )

    tdd_cmd = sub.add_parser("tdd", help="Run and record RED/GREEN/REFACTOR loop steps")
    tdd_cmd.add_argument("action", choices=["status", "red", "green", "refactor"])
    tdd_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    tdd_cmd.add_argument(
        "--dry-run", action="store_true", help="Run checks in dry-run mode"
    )

    suggest_cmd = sub.add_parser("suggest", help="Feature suggestion mode for ideas")
    suggest_cmd.add_argument("title", help="Idea title")
    suggest_cmd.add_argument("proposal", help="Core idea/proposal text")
    suggest_cmd.add_argument("--context", default="", help="Optional context or goal")
    suggest_cmd.add_argument("--task-id", help="Optional linked task id")
    suggest_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    challenge_cmd = sub.add_parser("challenge", help="Devil's advocate crucible mode")
    challenge_cmd.add_argument("idea_id", help="Idea record id")
    challenge_cmd.add_argument(
        "--persona",
        action="append",
        choices=available_personas(),
        help="Select specific persona(s); defaults to diverse panel",
    )
    challenge_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    reply_cmd = sub.add_parser("reply", help="Record a reply to a persona critique")
    reply_cmd.add_argument("idea_id", help="Idea record id")
    reply_cmd.add_argument(
        "--persona", required=True, choices=available_personas(), help="Persona name"
    )
    reply_cmd.add_argument("--response", required=True, help="Response text")
    reply_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    ideas_cmd = sub.add_parser("ideas", help="List idea records")
    ideas_cmd.add_argument("--task-id", help="Filter by task id")
    ideas_cmd.add_argument("--status", help="Filter by status")
    ideas_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    idea_show_cmd = sub.add_parser("idea-show", help="Show one idea record")
    idea_show_cmd.add_argument("idea_id", help="Idea record id")
    idea_show_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )

    audit_cmd = sub.add_parser(
        "audit", help="Audit task/workspace completion and readiness"
    )
    audit_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest task)"
    )
    audit_cmd.add_argument(
        "--workspace", action="store_true", help="Audit workspace instead of a task"
    )
    audit_cmd.add_argument(
        "--strict", action="store_true", help="Fail when warnings are present"
    )
    audit_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )
    audit_cmd.add_argument(
        "--dry-run", action="store_true", help="Dry-run quality gates during audit"
    )
    audit_cmd.add_argument(
        "--no-run-gates",
        dest="run_gates",
        action="store_false",
        help="Skip quality gate execution",
    )
    audit_cmd.add_argument("--gate", help="Run one named gate when executing gates")
    audit_cmd.add_argument(
        "--fix", action="store_true", help="Apply safe automatic fixes before audit"
    )
    audit_cmd.add_argument(
        "--provider",
        default="codex",
        choices=["codex", "opencode"],
        help="Provider used when creating/repairing config with --fix",
    )
    audit_cmd.set_defaults(run_gates=True)

    audit_ai_cmd = sub.add_parser(
        "audit-ai", help="Run provider-assisted audit analysis"
    )
    audit_ai_cmd.add_argument(
        "task_id", nargs="?", help="Task id (defaults to latest active task)"
    )
    audit_ai_cmd.add_argument(
        "--workspace",
        action="store_true",
        help="Analyze workspace audit instead of task",
    )
    audit_ai_cmd.add_argument(
        "--strict", action="store_true", help="Use strict local audit snapshot"
    )
    audit_ai_cmd.add_argument("--extra", default="", help="Extra audit instruction")
    audit_ai_cmd.add_argument(
        "--dry-run", action="store_true", help="Print command and prompt only"
    )
    audit_ai_cmd.add_argument(
        "--timeout", type=int, default=0, help="Provider timeout seconds"
    )

    doctor_cmd = sub.add_parser("doctor", help="Check provider/runtime prerequisites")
    doctor_cmd.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )
    doctor_cmd.add_argument(
        "--fix", action="store_true", help="Apply safe automatic fixes before checks"
    )
    doctor_cmd.add_argument(
        "--provider",
        default="codex",
        choices=["codex", "opencode"],
        help="Provider used when creating or repairing config",
    )

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    provider = normalize_provider(args.provider)
    config = init_workspace(provider=provider, force=args.force)

    rules_file = ROOT_DIR / "templates" / "agent-rules.md"
    rules_file.write_text(default_agent_rules(provider), encoding="utf-8")
    agents_file = Path("AGENTS.md")
    _ensure_agents_block(agents_file, provider)

    print(f"Initialized {ROOT_DIR} with provider={config.provider}")
    print(f"Edit quality gates in {CONFIG_FILE}")
    print(f"Agent rules scaffold written to {rules_file}")
    print(f"AGENTS integration updated in {agents_file}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    _require_initialized()
    task = create_task(args.title, task_id=args.task_id)
    print(f"Created task {task.id}")
    print(f"Title: {task.title}")
    print(f"Phase: {task.phase}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    _require_initialized()
    task = resolve_task(args.task_id)
    add_plan_step(task, args.step)
    save_task(task)
    print(f"Added plan step to {task.id}")
    return 0


def cmd_plan_ai(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    handoff_file = task.handoff_file or str(handoff_path(task.id))
    prompt = _build_plan_ai_prompt(task, handoff_file, extra=args.extra)
    rc, result, report_file = _run_analysis_context(
        config,
        context="plan",
        prompt=prompt,
        timeout=args.timeout,
        dry_run=args.dry_run,
        target_id=task.id,
    )
    if args.dry_run:
        return rc
    if result is not None and report_file is not None:
        add_note(task, f"Plan AI analysis completed: {report_file}")
        save_task(task)
    return rc


def cmd_note(args: argparse.Namespace) -> int:
    _require_initialized()
    task = resolve_task(args.task_id)
    add_note(task, args.text)
    save_task(task)
    print(f"Added note to {task.id}")
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    _require_initialized()
    task = resolve_task(args.task_id)
    set_status(task, args.status)
    save_task(task)
    print(f"Task {task.id} status -> {task.status}")
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    _require_initialized()
    tasks = list_tasks()
    if not tasks:
        print("No tasks found.")
        return 0
    for task in tasks:
        if not args.all and task.status == "completed":
            continue
        print(f"{task.id}  [{task.status}]  {task.title}  updated={task.updated_at}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    _require_initialized()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    print(f"id: {task.id}")
    print(f"title: {task.title}")
    print(f"status: {task.status}")
    print(f"phase: {task.phase}")
    print(f"created_at: {task.created_at}")
    print(f"updated_at: {task.updated_at}")
    print("plan:")
    if task.plan_steps:
        for item in task.plan_steps:
            print(f"- {item}")
    else:
        print("- (none)")
    print("notes:")
    if task.notes:
        for item in task.notes[-10:]:
            print(f"- {item}")
    else:
        print("- (none)")
    if task.handoff_file:
        print(f"handoff_file: {task.handoff_file}")
    if task.provider_runs:
        print(f"provider_runs: {len(task.provider_runs)}")
        last = task.provider_runs[-1]
        print(
            f"last_run: provider={last.get('provider')} exit_code={last.get('exit_code')} report={last.get('report_file')}"
        )
    if task.verifier_runs:
        print(f"verifier_runs: {len(task.verifier_runs)}")
        latest_verifier = task.verifier_runs[-1]
        print(
            f"latest_verifier: success={latest_verifier.get('success')} base_ref={latest_verifier.get('base_ref')}"
        )
    if task.hook_runs:
        print(f"hook_runs: {len(task.hook_runs)}")
    if task.tdd_cycles:
        print(f"tdd_cycles: {len(task.tdd_cycles)}")
        latest = task.tdd_cycles[-1]
        print(f"latest_tdd_cycle: id={latest.get('id')} status={latest.get('status')}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    results = run_quality_gates(config, gate_name=args.gate, dry_run=args.dry_run)
    apply_quality_results(task, results)
    save_task(task)

    failed = False
    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.name}: {result.command} (code={result.exit_code})")
        if result.stdout:
            print(f"stdout: {result.stdout}")
        if result.stderr:
            print(f"stderr: {result.stderr}")
        failed = failed or (not result.success)
    print(f"task status: {task.status}")
    return 1 if failed and not args.dry_run else 0


def cmd_verify(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    return _run_verify_for_task(
        task,
        config,
        gate=args.gate,
        dry_run=args.dry_run,
        force_complete=args.force_complete,
    )


def cmd_handoff(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    output_path = handoff_path(task.id)
    markdown = render_handoff(
        task, config.provider, str(output_path), extra_notes=args.notes
    )
    output_path.write_text(markdown, encoding="utf-8")
    task.handoff_file = str(output_path)
    task.touch()
    save_task(task)
    print(f"Wrote handoff: {output_path}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    handoff_file = task.handoff_file or str(handoff_path(task.id))
    print(resume_prompt(config.provider, task, handoff_file))
    return 0


def cmd_spec(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    action = args.action
    if action == "status":
        if args.phase:
            raise ValueError("Do not pass a phase for `pilot spec status`.")
        report = phase_report(task, config=config)
        print(f"task: {task.id}")
        print(f"phase: {report['phase']}")
        print(f"status: {report['status']}")
        print(f"next_phase: {report['next_phase']}")
        reasons = report["blocking_reasons"]
        if reasons:
            print("blocked_by:")
            for reason in reasons:
                print(f"- {reason}")
        else:
            print("blocked_by: (none)")
        return 0

    if action == "advance":
        if args.phase:
            raise ValueError("Do not pass a phase for `pilot spec advance`.")
        transition = advance_phase(task, config=config, force=args.force)
        save_task(task)
        print(f"Phase transition: {transition}")
        print(f"status -> {task.status}")
        return 0

    if args.phase is None:
        raise ValueError("`pilot spec set` requires a target phase.")
    transition = set_phase(task, args.phase, config=config, force=args.force)
    save_task(task)
    print(f"Phase transition: {transition}")
    print(f"status -> {task.status}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )
    return _run_provider_for_task(
        task,
        config,
        extra=args.extra,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )


def cmd_sync(args: argparse.Namespace) -> int:
    _require_initialized()
    result = sync_workspace_index(
        max_files=max(args.max_files, 1),
        max_file_bytes=max(args.max_bytes, 1),
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    manifest = result.get("manifest", {})
    summary = {}
    if isinstance(manifest, dict):
        summary = (
            manifest.get("summary", {})
            if isinstance(manifest.get("summary"), dict)
            else {}
        )
    print(f"index_dir: {INDEX_DIR}")
    print(f"manifest: {result.get('manifest_file')}")
    print(f"context: {result.get('context_file')}")
    print(f"indexed_files: {summary.get('indexed_files', 0)}")
    print(
        f"added: {summary.get('added', 0)} changed: {summary.get('changed', 0)} removed: {summary.get('removed', 0)}"
    )
    return 0


def cmd_verifier(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=[
            "planned",
            "in_progress",
            "blocked",
            "verifying",
            "completed",
        ],
    )
    sync_workspace_index()
    git_root = ensure_git_repo()

    settings = resolve_provider_settings(config, "verifier")
    worktree_path = VERIFIER_DIR / f"pending-{task.id}"
    prompt = _build_verifier_prompt(task, worktree_path, args.base_ref)

    if args.dry_run:
        print(f"git_root: {git_root}")
        print(f"worktree_dir: {VERIFIER_DIR}")
        print(f"base_ref: {args.base_ref}")
        print(f"provider_settings: {settings if settings else {}}")
        print(
            f"planned_git_command: git worktree add --detach <lane_path> {args.base_ref}"
        )
        if not args.skip_gates:
            print("planned_quality_gates:")
            for gate in config.quality_gates:
                print(f"- {gate.get('name')}: {gate.get('command')}")
        if not args.skip_provider:
            command = provider_command(config.provider, prompt, settings=settings)
            print("planned_provider_command:")
            print(" ".join(shlex.quote(part) for part in command))
            print("\nprompt:")
            print(prompt)
        return 0

    lane_path = None
    gate_results = []
    provider_result = None
    provider_report_file = None
    lanes_ok = True
    try:
        lane_path = create_worktree(task.id, base_ref=args.base_ref)
        print(f"verifier_worktree: {lane_path}")
        if not args.skip_gates:
            gate_results = run_quality_gates_in_dir(
                config, cwd=lane_path, dry_run=False
            )
            for result in gate_results:
                status = "PASS" if result.success else "FAIL"
                print(
                    f"[{status}] verifier gate {result.name}: {result.command} (code={result.exit_code})"
                )
            if any(not result.success for result in gate_results):
                lanes_ok = False

        if not args.skip_provider:
            prompt = _build_verifier_prompt(task, lane_path, args.base_ref)
            provider_result = run_provider_command(
                config.provider,
                prompt,
                timeout_seconds=max(args.timeout, 0),
                settings=settings,
                cwd=str(lane_path),
            )
            provider_report_file = _write_analysis_report(
                "verifier", task.id, provider_result
            )
            print(f"verifier_provider_report: {provider_report_file}")
            print(f"verifier_provider_exit: {provider_result['exit_code']}")
            if provider_result["exit_code"] != 0:
                lanes_ok = False
    finally:
        if lane_path is not None and not args.keep_worktree:
            try:
                remove_worktree(lane_path)
                print(f"verifier_cleanup: removed {lane_path}")
            except RuntimeError as exc:
                print(f"verifier_cleanup: failed ({exc})")

    run_record = {
        "ran_at": utc_now_iso(),
        "base_ref": args.base_ref,
        "worktree": str(lane_path) if lane_path else "",
        "kept_worktree": bool(args.keep_worktree),
        "skip_gates": bool(args.skip_gates),
        "skip_provider": bool(args.skip_provider),
        "settings": settings,
        "gate_results": [item.to_dict() for item in gate_results],
        "provider_exit_code": provider_result["exit_code"]
        if isinstance(provider_result, dict)
        else None,
        "provider_report_file": str(provider_report_file)
        if provider_report_file
        else None,
        "success": lanes_ok,
    }
    task.verifier_runs.append(run_record)
    add_note(
        task,
        f"Verifier lane {'passed' if lanes_ok else 'failed'} at {run_record['ran_at']}.",
    )
    if not lanes_ok:
        task.status = "blocked"
    save_task(task)
    return 0 if lanes_ok else 1


def cmd_auto(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )

    print(f"auto: task={task.id} phase={task.phase} status={task.status}")
    for _ in range(12):
        task = resolve_task(task.id)
        if task.phase == "complete":
            print("auto: already complete")
            return 0

        if task.phase == "discover":
            transition = set_phase(task, "plan", config=config, force=args.force)
            save_task(task)
            print(f"auto: {transition}")
            continue

        if task.phase == "plan":
            idea_ok, idea_detail = task_idea_compliance(task.id)
            if not idea_ok and not args.force:
                raise ValueError(
                    "Idea gate failed before implementation. "
                    + idea_detail
                    + " Run `pilot suggest`, `pilot challenge`, and `pilot reply` first "
                    + "or rerun with `--force`."
                )
            if not idea_ok:
                print(f"auto: idea gate bypassed (--force): {idea_detail}")
            else:
                print(f"auto: idea gate passed ({idea_detail})")
            if not task.plan_steps and not args.force:
                raise ValueError(
                    "Auto pipeline requires at least one plan step in `plan` phase. "
                    'Add one with `pilot plan <task_id> "..."` or rerun with --force.'
                )
            transition = set_phase(task, "implement", config=config, force=args.force)
            save_task(task)
            print(f"auto: {transition}")
            continue

        if task.phase == "implement":
            if args.skip_run:
                print("auto: provider run skipped (--skip-run)")
            else:
                run_rc = _run_provider_for_task(
                    task,
                    config,
                    extra=args.extra,
                    timeout=args.timeout,
                    dry_run=False,
                )
                if run_rc != 0:
                    print("auto: stopping because provider run failed")
                    return run_rc
            task = resolve_task(task.id)
            if task.status == "blocked" and not args.force:
                print("auto: task is blocked after implement step")
                return 1
            transition = set_phase(task, "verify", config=config, force=args.force)
            save_task(task)
            print(f"auto: {transition}")
            continue

        if task.phase == "verify":
            if args.skip_verify:
                print("auto: verify/completion skipped (--skip-verify)")
                return 0
            verify_rc = _run_verify_for_task(
                task,
                config,
                dry_run=False,
                force_complete=args.force,
            )
            if verify_rc != 0:
                print("auto: stopping because verification/completion failed")
                return verify_rc
            task = resolve_task(task.id)
            if task.phase == "complete":
                print("auto: completed")
                return 0
            continue

        raise ValueError(f"Unknown task phase `{task.phase}`.")

    raise RuntimeError("Auto pipeline exceeded step limit without reaching completion.")


def cmd_tdd(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = resolve_task(
        args.task_id,
        preferred_statuses=["planned", "in_progress", "blocked", "verifying"],
    )

    if args.action == "status":
        _print_tdd_status(task)
        return 0

    if task.phase not in {"implement", "verify"}:
        raise ValueError("TDD steps can only run in `implement` or `verify` phase.")

    if args.action in {"red", "green"}:
        _require_quality_gate(config, "test")

    if args.action == "red":
        cycle = _get_or_create_tdd_cycle(task)
        results = run_quality_gates(config, gate_name="test", dry_run=args.dry_run)
        _print_gate_results(results)
        if args.dry_run:
            print("tdd: red dry-run only (task state unchanged)")
            return 0
        task.quality_results.extend(results)
        task.touch()
        if all(result.success for result in results):
            save_task(task)
            raise ValueError("RED step requires at least one failing test result.")
        _record_tdd_step(cycle, "red", results, expectation="failing test")
        cycle["status"] = "red"
        cycle["updated_at"] = utc_now_iso()
        add_note(task, f"TDD RED step passed for cycle {cycle['id']}.")
        save_task(task)
        print(f"tdd: red passed (cycle={cycle['id']})")
        return 0

    cycle = _latest_open_tdd_cycle(task)
    if cycle is None:
        raise ValueError("No open TDD cycle found. Run `pilot tdd red` first.")
    steps = cycle.setdefault("steps", {})

    if args.action == "green":
        if "red" not in steps:
            raise ValueError("TDD GREEN requires a completed RED step first.")
        results = run_quality_gates(config, gate_name="test", dry_run=args.dry_run)
        _print_gate_results(results)
        if args.dry_run:
            print("tdd: green dry-run only (task state unchanged)")
            return 0
        task.quality_results.extend(results)
        task.touch()
        if any(not result.success for result in results):
            task.status = "blocked"
            add_note(task, f"TDD GREEN failed for cycle {cycle['id']}.")
            save_task(task)
            raise ValueError("GREEN step requires all test gates to pass.")
        _record_tdd_step(cycle, "green", results, expectation="passing test")
        cycle["status"] = "green"
        cycle["updated_at"] = utc_now_iso()
        if task.status == "blocked":
            task.status = "in_progress"
        add_note(task, f"TDD GREEN step passed for cycle {cycle['id']}.")
        save_task(task)
        print(f"tdd: green passed (cycle={cycle['id']})")
        return 0

    if "green" not in steps:
        raise ValueError("TDD REFACTOR requires a completed GREEN step first.")
    results = run_quality_gates(config, dry_run=args.dry_run)
    _print_gate_results(results)
    if args.dry_run:
        print("tdd: refactor dry-run only (task state unchanged)")
        return 0
    task.quality_results.extend(results)
    task.touch()
    if any(not result.success for result in results):
        task.status = "blocked"
        add_note(task, f"TDD REFACTOR failed for cycle {cycle['id']}.")
        save_task(task)
        raise ValueError("REFACTOR step requires all configured quality gates to pass.")
    _record_tdd_step(cycle, "refactor", results, expectation="all gates pass")
    cycle["status"] = "completed"
    cycle["updated_at"] = utc_now_iso()
    cycle["completed_at"] = utc_now_iso()
    if task.status == "blocked":
        task.status = "in_progress"
    add_note(task, f"TDD cycle {cycle['id']} completed.")
    save_task(task)
    print(f"tdd: refactor passed (cycle={cycle['id']} completed)")
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    _require_initialized()
    if args.task_id:
        resolve_task(args.task_id)
    idea = create_idea(
        args.title,
        args.proposal,
        context=args.context,
        task_id=args.task_id,
    )
    if args.json:
        print(json.dumps(idea, indent=2))
        return 0
    print(f"idea_id: {idea['id']}")
    print(f"title: {idea['title']}")
    print(f"task_id: {idea.get('task_id') or '(none)'}")
    print("feature_suggestions:")
    for item in idea.get("suggestions", []):
        print(f"- {item}")
    print(f"next: ./pilot challenge {idea['id']}")
    return 0


def cmd_challenge(args: argparse.Namespace) -> int:
    _require_initialized()
    idea = load_idea(args.idea_id)
    idea = run_crucible(idea, selected_personas=args.persona)
    crucible = idea.get("crucible") or {}
    if args.json:
        print(json.dumps(crucible, indent=2))
        return 0
    panel = crucible.get("selected_personas", [])
    print(f"idea_id: {idea['id']}")
    print("panel:")
    for persona in panel:
        print(f"- {persona}")
    for round_item in crucible.get("rounds", []):
        print(f"\n[{round_item.get('persona')}] {round_item.get('focus')}")
        for point in round_item.get("critiques", []):
            print(f"- {point}")
    synthesis = crucible.get("synthesis", {})
    print("\nsynthesis:")
    for item in synthesis.get("critical_vulnerabilities", []):
        print(f"- vulnerability: {item}")
    for item in synthesis.get("recurring_themes", []):
        print(f"- theme: {item}")
    print(f'next: ./pilot reply {idea["id"]} --persona "{panel[0]}" --response "..."')
    return 0


def cmd_reply(args: argparse.Namespace) -> int:
    _require_initialized()
    idea = load_idea(args.idea_id)
    idea = add_reply(
        idea,
        persona=args.persona,
        response=args.response,
    )
    pending = pending_personas(idea)
    if args.json:
        payload = {
            "idea_id": idea["id"],
            "status": idea["status"],
            "pending_personas": pending,
        }
        print(json.dumps(payload, indent=2))
        return 0
    print(f"idea_id: {idea['id']}")
    print(f"status: {idea['status']}")
    if pending:
        print("pending_personas:")
        for persona in pending:
            print(f"- {persona}")
    else:
        print("pending_personas: (none)")
        print("idea pipeline ready for implementation.")
    return 0


def cmd_ideas(args: argparse.Namespace) -> int:
    _require_initialized()
    ideas = list_idea_records(task_id=args.task_id, status=args.status)
    if args.json:
        print(json.dumps(ideas, indent=2))
        return 0
    if not ideas:
        print("No idea records found.")
        return 0
    for item in ideas:
        print(
            f"{item.get('id')}  [{item.get('status')}]  task={item.get('task_id') or '-'}  {item.get('title')}"
        )
    return 0


def cmd_idea_show(args: argparse.Namespace) -> int:
    _require_initialized()
    idea = load_idea(args.idea_id)
    if args.json:
        print(json.dumps(idea, indent=2))
        return 0
    print(f"id: {idea.get('id')}")
    print(f"title: {idea.get('title')}")
    print(f"task_id: {idea.get('task_id') or '(none)'}")
    print(f"status: {idea.get('status')}")
    print(f"proposal: {idea.get('proposal')}")
    print("suggestions:")
    for item in idea.get("suggestions", []):
        print(f"- {item}")
    crucible = idea.get("crucible")
    if isinstance(crucible, dict):
        print("panel:")
        for persona in crucible.get("selected_personas", []):
            print(f"- {persona}")
    else:
        print("panel: (not run)")
    pending = pending_personas(idea)
    if pending:
        print("pending_personas:")
        for persona in pending:
            print(f"- {persona}")
    else:
        print("pending_personas: (none)")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    audit_fix_actions = []
    if args.fix:
        config, audit_fix_actions = apply_fixes(preferred_provider=args.provider)
    else:
        _require_initialized()
        config = load_config()

    gate_results = None
    if args.run_gates:
        gate_results = run_quality_gates(
            config,
            gate_name=args.gate,
            dry_run=args.dry_run,
        )

    report = None
    if args.workspace:
        report = audit_workspace(
            config,
            gate_results=gate_results,
            strict=args.strict,
            dry_run=args.dry_run,
        )
    else:
        task = _resolve_task_for_audit(args.task_id)
        if task is None:
            report = audit_workspace(
                config,
                gate_results=gate_results,
                strict=args.strict,
                dry_run=args.dry_run,
            )
            report.checks.insert(
                0,
                AuditCheck(
                    "task_resolution",
                    "warn",
                    "No tasks found; workspace audit was executed instead.",
                ),
            )
            report.summary = {
                "pass": sum(1 for item in report.checks if item.status == "pass"),
                "warn": sum(1 for item in report.checks if item.status == "warn"),
                "fail": sum(1 for item in report.checks if item.status == "fail"),
            }
            report.done = report.done and (
                not args.strict or report.summary["warn"] == 0
            )
        else:
            if gate_results is not None:
                apply_quality_results(task, gate_results)
                save_task(task)
            report = audit_task(
                task,
                config,
                gate_results=gate_results,
                strict=args.strict,
            )

    if args.json:
        payload = report.to_dict()
        if audit_fix_actions:
            payload["fixes"] = [
                {"name": item.name, "status": item.status, "detail": item.detail}
                for item in audit_fix_actions
            ]
        print(json.dumps(payload, indent=2))
    else:
        print(f"audit: target={report.target} id={report.target_id or '-'}")
        if audit_fix_actions:
            print("fixes:")
            for item in audit_fix_actions:
                print(f"- [{item.status.upper()}] {item.name}: {item.detail}")
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.detail}")
        print(
            f"summary: pass={report.summary['pass']} warn={report.summary['warn']} fail={report.summary['fail']}"
        )
        print(f"done: {'yes' if report.done else 'no'}")

    return 0 if report.done else 1


def cmd_audit_ai(args: argparse.Namespace) -> int:
    _require_initialized()
    config = load_config()
    task = None
    if args.workspace:
        report = audit_workspace(
            config,
            gate_results=None,
            strict=args.strict,
            dry_run=False,
        )
        target_label = "workspace"
    else:
        task = resolve_task(args.task_id)
        report = audit_task(
            task,
            config,
            gate_results=None,
            strict=args.strict,
        )
        target_label = task.id

    prompt = _build_audit_ai_prompt(report.to_dict(), extra=args.extra)
    rc, result, report_file = _run_analysis_context(
        config,
        context="audit",
        prompt=prompt,
        timeout=args.timeout,
        dry_run=args.dry_run,
        target_id=target_label,
    )
    if args.dry_run:
        return rc
    if task is not None and result is not None and report_file is not None:
        add_note(task, f"Audit AI analysis completed: {report_file}")
        save_task(task)
    return rc


def cmd_doctor(args: argparse.Namespace) -> int:
    fixes = []
    if args.fix:
        config, fixes = apply_fixes(preferred_provider=args.provider)
    else:
        _require_initialized()
        config = load_config()

    results = run_doctor(config)
    if args.json:
        payload = {
            "fixes": [
                {"name": item.name, "status": item.status, "detail": item.detail}
                for item in fixes
            ],
            "checks": [
                {"name": item.name, "status": item.status, "detail": item.detail}
                for item in results
            ],
        }
        payload["summary"] = summarize(results)
        print(json.dumps(payload, indent=2))
    else:
        if fixes:
            print("fixes:")
            for item in fixes:
                print(f"- [{item.status.upper()}] {item.name}: {item.detail}")
        for item in results:
            print(f"[{item.status.upper()}] {item.name}: {item.detail}")
        counts = summarize(results)
        print(
            f"summary: pass={counts['pass']} warn={counts['warn']} fail={counts['fail']}"
        )
    counts = summarize(results)
    return 1 if counts["fail"] > 0 else 0


def _run_provider_for_task(
    task,
    config,
    *,
    extra: str = "",
    timeout: int = 0,
    dry_run: bool = False,
) -> int:
    ensure_layout()
    sync_workspace_index()
    output_path = handoff_path(task.id)
    if not output_path.exists():
        markdown = render_handoff(task, config.provider, str(output_path))
        output_path.write_text(markdown, encoding="utf-8")
        task.handoff_file = str(output_path)
        task.touch()
        save_task(task)

    prompt = build_run_prompt(
        config.provider,
        task,
        str(output_path),
        extra_instructions=extra,
    )
    settings = resolve_provider_settings(config, "implement")
    command = provider_command(config.provider, prompt, settings=settings)
    if dry_run:
        print("provider_settings:")
        if settings:
            for key, value in settings.items():
                print(f"- {key}: {value}")
        else:
            print("- (none)")
        if config.pre_edit_hooks:
            print("pre_edit_hooks:")
            for idx, hook in enumerate(config.pre_edit_hooks, start=1):
                print(f"{idx}. {hook}")
        if config.post_edit_hooks:
            print("post_edit_hooks:")
            for idx, hook in enumerate(config.post_edit_hooks, start=1):
                print(f"{idx}. {hook}")
        print("command:")
        print(" ".join(shlex.quote(part) for part in command))
        print("\nprompt:")
        print(prompt)
        return 0

    pre_ok, pre_results = _run_hook_commands(
        config.pre_edit_hooks,
        hook_name="pre_edit",
        dry_run=False,
    )
    if pre_results:
        task.hook_runs.extend(pre_results)
        task.touch()
    if not pre_ok:
        task.status = "blocked"
        add_note(task, "Pre-edit hooks failed; provider run aborted.")
        save_task(task)
        return 1

    result = run_provider_command(
        config.provider,
        prompt,
        timeout_seconds=max(timeout, 0),
        settings=settings,
    )
    report_file = _write_provider_report(task.id, result)
    task.provider_runs.append(
        {
            "provider": result["provider"],
            "settings": result.get("settings", {}),
            "command": result["command"],
            "exit_code": result["exit_code"],
            "duration_seconds": result["duration_seconds"],
            "ran_at": result["started_at"],
            "report_file": str(report_file),
        }
    )

    if result["exit_code"] == 0:
        add_note(task, f"Provider run succeeded: {report_file}")
    else:
        task.status = "blocked"
        add_note(
            task, f"Provider run failed (exit={result['exit_code']}): {report_file}"
        )
    if result["exit_code"] == 0:
        post_ok, post_results = _run_hook_commands(
            config.post_edit_hooks,
            hook_name="post_edit",
            dry_run=False,
        )
        if post_results:
            task.hook_runs.extend(post_results)
            task.touch()
        if not post_ok:
            task.status = "blocked"
            add_note(task, "Post-edit hooks failed after provider run.")
    save_task(task)

    print(f"provider: {result['provider']}")
    print(f"exit_code: {result['exit_code']}")
    print(f"duration_seconds: {result['duration_seconds']}")
    print(f"report: {report_file}")
    if result["stdout"]:
        print("stdout:")
        print(_preview_text(str(result["stdout"])))
    if result["stderr"]:
        print("stderr:")
        print(_preview_text(str(result["stderr"])))
    if result["exit_code"] != 0:
        return 1
    if task.status == "blocked":
        return 1
    return 0


def _run_verify_for_task(
    task,
    config,
    *,
    gate: str | None = None,
    dry_run: bool = False,
    force_complete: bool = False,
) -> int:
    results = run_quality_gates(config, gate_name=gate, dry_run=dry_run)
    apply_quality_results(task, results)

    failed = any(not result.success for result in results)
    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.name}: {result.command} (code={result.exit_code})")
        if result.stdout:
            print(f"stdout: {result.stdout}")
        if result.stderr:
            print(f"stderr: {result.stderr}")

    if dry_run:
        save_task(task)
        print(f"task status: {task.status}")
        return 0

    if failed:
        save_task(task)
        print("verification: failed quality gates")
        print(f"task status: {task.status}")
        return 1

    completion_blocked = False
    if task.phase == "verify":
        try:
            transition = set_phase(
                task,
                "complete",
                config=config,
                force=force_complete,
            )
            print(f"completion: {transition}")
        except ValueError as exc:
            completion_blocked = True
            print(f"completion: blocked ({exc})")
    else:
        print(
            "completion: skipped (task phase is not `verify`; use `pilot spec` to reach verify first)"
        )

    save_task(task)
    print(f"task status: {task.status}")
    print(f"task phase: {task.phase}")
    return 1 if completion_blocked else 0


def _run_analysis_context(
    config,
    *,
    context: str,
    prompt: str,
    timeout: int = 0,
    dry_run: bool = False,
    target_id: str = "workspace",
) -> tuple[int, dict[str, object] | None, Path | None]:
    sync_workspace_index()
    settings = resolve_provider_settings(config, context)
    command = provider_command(
        config.provider,
        prompt,
        settings=settings,
    )
    if dry_run:
        print(f"profile_context: {context}")
        print("provider_settings:")
        if settings:
            for key, value in settings.items():
                print(f"- {key}: {value}")
        else:
            print("- (none)")
        print("command:")
        print(" ".join(shlex.quote(part) for part in command))
        print("\nprompt:")
        print(prompt)
        return 0, None, None

    result = run_provider_command(
        config.provider,
        prompt,
        timeout_seconds=max(timeout, 0),
        settings=settings,
    )
    report_file = _write_analysis_report(context, target_id, result)
    print(f"analysis_context: {context}")
    print(f"provider: {result['provider']}")
    print(f"exit_code: {result['exit_code']}")
    print(f"duration_seconds: {result['duration_seconds']}")
    print(f"report: {report_file}")
    if result.get("stdout"):
        print("stdout:")
        print(_preview_text(str(result["stdout"])))
    if result.get("stderr"):
        print("stderr:")
        print(_preview_text(str(result["stderr"])))
    return (0 if result["exit_code"] == 0 else 1), result, report_file


def _build_plan_ai_prompt(task, handoff_file: str, *, extra: str = "") -> str:
    extra_block = (
        f"\n\nOperator instructions:\n{extra.strip()}" if extra.strip() else ""
    )
    return (
        dedent(
            f"""\
        You are assisting with planning for task `{task.id}`: {task.title}.

        Use this context:
        - `.pilot/tasks/{task.id}.json`
        - `{handoff_file}`
        - Existing notes and plan steps

        Output format:
        1. Top risks and assumptions (max 5)
        2. Concrete implementation plan steps (max 7, testable)
        3. Suggested first execution step
        4. Verification strategy linked to quality gates
        """
        ).strip()
        + extra_block
    )


def _build_audit_ai_prompt(report: dict[str, object], *, extra: str = "") -> str:
    extra_block = (
        f"\n\nOperator instructions:\n{extra.strip()}" if extra.strip() else ""
    )
    serialized = json.dumps(report, indent=2)
    return (
        dedent(
            f"""\
        Analyze this local audit report and produce a focused remediation plan.

        Audit report JSON:
        {serialized}

        Output format:
        1. Critical failures and root causes
        2. Fastest path to passing audit
        3. Recommended sequence of commands
        4. Residual risks after remediation
        """
        ).strip()
        + extra_block
    )


def _build_verifier_prompt(task, worktree_path: Path, base_ref: str) -> str:
    return dedent(
        f"""\
        Independent verifier lane for task `{task.id}`: {task.title}

        Context:
        - Worktree path: {worktree_path}
        - Base ref: {base_ref}
        - Task state file: .pilot/tasks/{task.id}.json

        Required outputs:
        1. Top implementation risks and likely regressions
        2. Files/areas requiring deeper review
        3. Confidence score (0-100) with justification
        4. Explicit pass/fail recommendation for merge readiness
        """
    ).strip()


def _run_hook_commands(
    commands: list[str],
    *,
    hook_name: str,
    dry_run: bool = False,
) -> tuple[bool, list[dict[str, object]]]:
    if not commands:
        return True, []

    results: list[dict[str, object]] = []
    for idx, command in enumerate(commands, start=1):
        if dry_run:
            print(f"[DRY-RUN] hook:{hook_name}:{idx}: {command}")
            continue
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
        )
        elapsed = round(time.perf_counter() - started, 3)
        success = completed.returncode == 0
        result = {
            "hook": hook_name,
            "index": idx,
            "command": command,
            "exit_code": completed.returncode,
            "success": success,
            "duration_seconds": elapsed,
            "ran_at": utc_now_iso(),
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
        results.append(result)
        status = "PASS" if success else "FAIL"
        print(
            f"[{status}] hook:{hook_name}:{idx}: {command} (code={completed.returncode})"
        )
        if result["stdout"]:
            print(f"stdout: {_preview_text(str(result['stdout']), limit=800)}")
        if result["stderr"]:
            print(f"stderr: {_preview_text(str(result['stderr']), limit=800)}")
        if not success:
            return False, results
    return True, results


def _print_gate_results(results) -> None:
    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.name}: {result.command} (code={result.exit_code})")
        if result.stdout:
            print(f"stdout: {result.stdout}")
        if result.stderr:
            print(f"stderr: {result.stderr}")


def _require_quality_gate(config, gate_name: str) -> None:
    names = {gate.get("name", "") for gate in config.quality_gates}
    if gate_name not in names:
        raise ValueError(
            f"TDD requires a quality gate named `{gate_name}` in .pilot/config.json."
        )


def _print_tdd_status(task) -> None:
    ready, detail = tdd_readiness(task)
    print(f"task: {task.id}")
    print(f"tdd_ready: {'yes' if ready else 'no'}")
    print(f"detail: {detail}")
    if not task.tdd_cycles:
        print("cycles: (none)")
        return
    print("cycles:")
    for cycle in task.tdd_cycles[-5:]:
        steps = cycle.get("steps", {})
        red = "yes" if "red" in steps else "no"
        green = "yes" if "green" in steps else "no"
        refactor = "yes" if "refactor" in steps else "no"
        print(
            f"- {cycle.get('id')} status={cycle.get('status')} red={red} green={green} refactor={refactor}"
        )


def _latest_open_tdd_cycle(task) -> dict | None:
    if not task.tdd_cycles:
        return None
    latest = task.tdd_cycles[-1]
    if not isinstance(latest, dict):
        return None
    if latest.get("status") == "completed":
        return None
    return latest


def _get_or_create_tdd_cycle(task) -> dict:
    existing = _latest_open_tdd_cycle(task)
    if existing is not None:
        steps = existing.get("steps", {})
        if "green" not in steps and "refactor" not in steps:
            return existing
    cycle_id = f"{utc_now_iso().replace(':', '').replace('-', '').replace('+00:00', 'Z')}-tdd-{secrets.token_hex(2)}"
    cycle = {
        "id": cycle_id,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "status": "started",
        "steps": {},
    }
    task.tdd_cycles.append(cycle)
    task.touch()
    return cycle


def _record_tdd_step(cycle: dict, step: str, results, *, expectation: str) -> None:
    cycle.setdefault("steps", {})
    cycle["steps"][step] = {
        "ran_at": utc_now_iso(),
        "expectation": expectation,
        "results": [
            {
                "name": result.name,
                "exit_code": result.exit_code,
                "success": result.success,
                "command": result.command,
                "ran_at": result.ran_at,
            }
            for result in results
        ],
    }


def _resolve_task_for_audit(task_id: str | None):
    if task_id:
        return resolve_task(task_id)
    tasks = list_tasks()
    if not tasks:
        return None
    return tasks[0]


def _require_initialized() -> None:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            "Workspace not initialized. Run `pilot init --provider codex|opencode`."
        )


def _write_provider_report(task_id: str, result: dict[str, object]) -> Path:
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    report_file = REPORTS_DIR / f"provider-run-{task_id}-{stamp}.json"
    report_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return report_file


def _write_analysis_report(
    context: str, target_id: str, result: dict[str, object]
) -> Path:
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    slug = target_id.replace("/", "_").replace(" ", "_")
    report_file = REPORTS_DIR / f"analysis-{context}-{slug}-{stamp}.json"
    report_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return report_file


def _preview_text(text: str, limit: int = 4000) -> str:
    cleaned = text.replace("\x00", "\\0")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n...[truncated]..."


def _ensure_agents_block(path: Path, provider: str) -> None:
    begin = "<!-- pilot-core:begin -->"
    end = "<!-- pilot-core:end -->"
    managed = (
        f"{begin}\n"
        "## pilot-core\n"
        "- Load and follow `.pilot/templates/agent-rules.md`.\n"
        "- Source of truth for task state: `.pilot/tasks/*.json`.\n"
        "- Use `pilot handoff` and `pilot resume` for session continuity.\n"
        f"- Active provider adapter: `{provider}`.\n"
        f"{end}\n"
    )

    if path.exists():
        content = path.read_text(encoding="utf-8")
        if begin in content and end in content:
            start = content.index(begin)
            finish = content.index(end) + len(end)
            new_content = content[:start] + managed + content[finish:]
            path.write_text(new_content, encoding="utf-8")
            return
        if content and not content.endswith("\n"):
            content += "\n"
        path.write_text(content + "\n" + managed, encoding="utf-8")
        return

    path.write_text(managed, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command_handlers = {
        "init": cmd_init,
        "new": cmd_new,
        "plan": cmd_plan,
        "plan-ai": cmd_plan_ai,
        "note": cmd_note,
        "set-status": cmd_set_status,
        "tasks": cmd_tasks,
        "show": cmd_show,
        "check": cmd_check,
        "verify": cmd_verify,
        "handoff": cmd_handoff,
        "resume": cmd_resume,
        "spec": cmd_spec,
        "run": cmd_run,
        "sync": cmd_sync,
        "verifier": cmd_verifier,
        "auto": cmd_auto,
        "tdd": cmd_tdd,
        "suggest": cmd_suggest,
        "challenge": cmd_challenge,
        "reply": cmd_reply,
        "ideas": cmd_ideas,
        "idea-show": cmd_idea_show,
        "audit": cmd_audit,
        "audit-ai": cmd_audit_ai,
        "doctor": cmd_doctor,
    }
    handler = command_handlers[args.command]
    try:
        return handler(args)
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
