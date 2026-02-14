from __future__ import annotations

import json
import secrets
from pathlib import Path
from textwrap import dedent

from .models import utc_now_iso
from .state import ROOT_DIR

IDEAS_DIR = ROOT_DIR / "ideas"

PERSONAS: dict[str, str] = {
    "Dr. Scrutiny": "Questions assumptions, evidence, and logical consistency.",
    'Reginald "Rex" Mondo': "Focuses on feasibility, resources, and implementation realism.",
    'Valerie "Val" Uation': "Scrutinizes cost, ROI, and financial sustainability.",
    'Marcus "Mark" Iterate': "Represents a skeptical end-user lens.",
    "Dr. Ethos": "Examines ethics, fairness, and misuse risk.",
    "General K.O.": "Analyzes competition and strategic vulnerabilities.",
    "Professor Simplex": "Pushes for simpler, more elegant solutions.",
    "Wildcard Wally": "Introduces unexpected disruptions and edge-case shocks.",
}

DEFAULT_PANEL = [
    "Dr. Scrutiny",
    'Reginald "Rex" Mondo',
    'Marcus "Mark" Iterate',
    "Dr. Ethos",
    "Professor Simplex",
]


def ensure_ideas_dir() -> None:
    IDEAS_DIR.mkdir(parents=True, exist_ok=True)


def create_idea(
    title: str,
    proposal: str,
    *,
    context: str = "",
    task_id: str | None = None,
) -> dict:
    ensure_ideas_dir()
    idea_id = _new_idea_id()
    now = utc_now_iso()
    idea = {
        "id": idea_id,
        "task_id": task_id,
        "title": title.strip(),
        "proposal": proposal.strip(),
        "context": context.strip(),
        "status": "suggested",
        "created_at": now,
        "updated_at": now,
        "suggestions": generate_feature_suggestions(title, proposal, context=context),
        "crucible": None,
        "replies": [],
    }
    save_idea(idea)
    return idea


def load_idea(idea_id: str) -> dict:
    path = idea_json_path(idea_id)
    if not path.exists():
        raise FileNotFoundError(f"Idea `{idea_id}` not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def list_ideas(*, task_id: str | None = None, status: str | None = None) -> list[dict]:
    ensure_ideas_dir()
    ideas: list[dict] = []
    for file in IDEAS_DIR.glob("*.json"):
        try:
            idea = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if task_id and idea.get("task_id") != task_id:
            continue
        if status and idea.get("status") != status:
            continue
        ideas.append(idea)
    ideas.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return ideas


def save_idea(idea: dict) -> None:
    ensure_ideas_dir()
    idea["updated_at"] = utc_now_iso()
    idea_json_path(idea["id"]).write_text(
        json.dumps(idea, indent=2) + "\n", encoding="utf-8"
    )
    idea_md_path(idea["id"]).write_text(render_idea_markdown(idea), encoding="utf-8")


def run_crucible(
    idea: dict,
    *,
    selected_personas: list[str] | None = None,
) -> dict:
    panel = selected_personas or DEFAULT_PANEL
    panel = _normalize_panel(panel)
    rounds = [
        {
            "persona": persona,
            "focus": PERSONAS[persona],
            "critiques": _persona_critiques(persona, idea),
        }
        for persona in panel
    ]
    synthesis = _synthesize(rounds, idea)
    crucible = {
        "ran_at": utc_now_iso(),
        "selected_personas": panel,
        "rounds": rounds,
        "synthesis": synthesis,
    }
    idea["crucible"] = crucible
    idea["status"] = "challenged"
    save_idea(idea)
    return idea


def add_reply(idea: dict, *, persona: str, response: str) -> dict:
    if idea.get("crucible") is None:
        raise ValueError("Run `pilot challenge <idea_id>` before adding replies.")
    panel = idea["crucible"].get("selected_personas", [])
    if persona not in panel:
        raise ValueError(
            f"Persona `{persona}` is not in this idea panel. Expected one of: {', '.join(panel)}"
        )
    idea.setdefault("replies", []).append(
        {
            "persona": persona,
            "response": response.strip(),
            "replied_at": utc_now_iso(),
        }
    )
    pending = pending_personas(idea)
    idea["status"] = "replied" if not pending else "challenged"
    save_idea(idea)
    return idea


def pending_personas(idea: dict) -> list[str]:
    crucible = idea.get("crucible") or {}
    panel = crucible.get("selected_personas", [])
    replied = {
        item.get("persona")
        for item in idea.get("replies", [])
        if isinstance(item, dict)
    }
    return [persona for persona in panel if persona not in replied]


def task_idea_compliance(task_id: str) -> tuple[bool, str]:
    ideas = list_ideas(task_id=task_id)
    if not ideas:
        return False, "No idea record found for this task."
    latest = ideas[0]
    if not latest.get("suggestions"):
        return False, "Feature suggestion mode has no output."
    crucible = latest.get("crucible")
    if not isinstance(crucible, dict):
        return False, "Devil's advocate mode has not been run."
    panel = list(crucible.get("selected_personas", []) or [])
    if not panel:
        return False, "Devil's advocate panel is empty."
    pending = pending_personas(latest)
    if pending:
        return False, f"Missing replies for: {', '.join(pending)}."
    return True, f"Idea `{latest['id']}` passed suggestion + crucible + reply flow."


def idea_json_path(idea_id: str) -> Path:
    return IDEAS_DIR / f"{idea_id}.json"


def idea_md_path(idea_id: str) -> Path:
    return IDEAS_DIR / f"{idea_id}.md"


def generate_feature_suggestions(
    title: str, proposal: str, *, context: str = ""
) -> list[str]:
    snippet = _snippet(proposal)
    suggestions = [
        f"Define measurable success criteria for `{title}` before implementation.",
        f"Break `{title}` into phased milestones with explicit acceptance tests.",
        f"Create observability checkpoints (logs/metrics) for `{title}` rollout.",
        f"Add rollback and failure-mode strategy for `{title}` in case `{snippet}` underperforms.",
        f"Document user impact assumptions and validation plan{_context_suffix(context)}.",
    ]
    return suggestions


def available_personas() -> list[str]:
    return list(PERSONAS.keys())


def render_idea_markdown(idea: dict) -> str:
    suggestions = (
        "\n".join(f"- {item}" for item in idea.get("suggestions", [])) or "- (none)"
    )
    replies = idea.get("replies", [])
    reply_lines = (
        "\n".join(
            f"- {item.get('persona')}: {item.get('response')}"
            for item in replies
            if isinstance(item, dict)
        )
        or "- (none)"
    )
    crucible = idea.get("crucible")
    rounds_block = "- (not run)"
    synthesis_block = "- (not run)"
    if isinstance(crucible, dict):
        rounds = []
        for round_item in crucible.get("rounds", []):
            persona = round_item.get("persona", "Unknown")
            focus = round_item.get("focus", "")
            critiques = "\n".join(
                f"  - {point}" for point in round_item.get("critiques", [])
            )
            rounds.append(f"- **{persona}** ({focus})\n{critiques}")
        rounds_block = "\n".join(rounds) if rounds else "- (none)"
        synthesis = crucible.get("synthesis", {})
        vulnerabilities = (
            "\n".join(
                f"- {item}" for item in synthesis.get("critical_vulnerabilities", [])
            )
            or "- (none)"
        )
        themes = (
            "\n".join(f"- {item}" for item in synthesis.get("recurring_themes", []))
            or "- (none)"
        )
        strengths = (
            "\n".join(f"- {item}" for item in synthesis.get("potential_strengths", []))
            or "- (none)"
        )
        reflection = (
            "\n".join(f"- {item}" for item in synthesis.get("reflection_questions", []))
            or "- (none)"
        )
        synthesis_block = (
            "### Critical Vulnerabilities\n"
            f"{vulnerabilities}\n\n"
            "### Recurring Themes\n"
            f"{themes}\n\n"
            "### Potential Strengths\n"
            f"{strengths}\n\n"
            "### Reflection Questions\n"
            f"{reflection}"
        )

    context_line = idea.get("context", "").strip() or "(none)"
    return (
        dedent(
            f"""\
        # Idea Record: {idea.get("id")}

        ## Meta
        - Title: {idea.get("title")}
        - Task: {idea.get("task_id") or "(none)"}
        - Status: {idea.get("status")}
        - Created: {idea.get("created_at")}
        - Updated: {idea.get("updated_at")}

        ## Proposal
        {idea.get("proposal", "").strip()}

        ## Context
        {context_line}

        ## Feature Suggestions
        {suggestions}

        ## Crucible Rounds
        {rounds_block}

        ## Crucible Synthesis
        {synthesis_block}

        ## Replies
        {reply_lines}
        """
        ).strip()
        + "\n"
    )


def _new_idea_id() -> str:
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    return f"{stamp}-idea-{secrets.token_hex(2)}"


def _normalize_panel(panel: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in panel:
        if item not in PERSONAS:
            valid = ", ".join(PERSONAS.keys())
            raise ValueError(f"Unknown persona `{item}`. Valid: {valid}")
        if item not in normalized:
            normalized.append(item)
    if not normalized:
        raise ValueError("At least one persona is required.")
    return normalized


def _persona_critiques(persona: str, idea: dict) -> list[str]:
    title = idea.get("title", "this proposal")
    proposal = idea.get("proposal", "")
    snippet = _snippet(proposal)
    prompts = {
        "Dr. Scrutiny": [
            f"What evidence proves the core premise behind `{title}` is true?",
            f"Which assumptions in `{snippet}` could fail first, and how would we detect that early?",
            "What is the strongest argument against doing this at all?",
        ],
        'Reginald "Rex" Mondo': [
            f"What is the smallest build plan that can realistically deliver `{title}`?",
            "Which dependencies, people, or tooling create schedule risk?",
            "What must be cut if scope or timeline becomes constrained?",
        ],
        'Valerie "Val" Uation': [
            f"What are one-time and ongoing costs for `{title}`?",
            "What measurable return justifies those costs?",
            "If adoption is 50% lower than expected, is this still viable?",
        ],
        'Marcus "Mark" Iterate': [
            "Why should a skeptical user switch from current behavior?",
            "Where is the current proposal adding friction or confusion?",
            "What proof will users require before trusting this?",
        ],
        "Dr. Ethos": [
            "Who could be harmed or disadvantaged by this decision?",
            "How could this be abused, and what safeguards exist?",
            "What transparency or consent obligations are required?",
        ],
        "General K.O.": [
            "What prevents a competitor from copying this quickly?",
            "Where are we strategically weak if rivals undercut on price/speed?",
            "What moat can we build in the first release cycle?",
        ],
        "Professor Simplex": [
            "What is the simplest version that still creates core value?",
            "Which components look over-engineered for day one?",
            "What can be removed without harming outcomes?",
        ],
        "Wildcard Wally": [
            "What black-swan event could instantly invalidate this approach?",
            "How resilient is the plan to major platform or policy shifts?",
            "What contingency path keeps progress alive under disruption?",
        ],
    }
    return prompts.get(persona, ["What is the core risk?"])


def _synthesize(rounds: list[dict], idea: dict) -> dict:
    vulnerabilities: list[str] = []
    themes: list[str] = []
    for item in rounds:
        critiques = item.get("critiques", [])
        if critiques:
            vulnerabilities.append(f"{item.get('persona')}: {critiques[0]}")
        themes.append(
            f"{item.get('persona')} emphasized {item.get('focus', '').lower()}."
        )
    vulnerabilities = vulnerabilities[:3]
    themes = themes[:3]
    strengths = [
        f"`{idea.get('title')}` has a clear core intent that can be staged incrementally.",
        "The plan can be made resilient by resolving high-risk assumptions first.",
    ]
    reflection = [
        "Which critique revealed the most costly blind spot?",
        "What concrete change will you make before implementation begins?",
        "What evidence will prove this idea is working after launch?",
    ]
    return {
        "critical_vulnerabilities": vulnerabilities,
        "recurring_themes": themes,
        "potential_strengths": strengths,
        "reflection_questions": reflection,
    }


def _snippet(text: str, limit: int = 72) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        return "the current proposal"
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _context_suffix(context: str) -> str:
    if not context.strip():
        return ""
    return " for the stated context"
