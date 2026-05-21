---
name: feedback-model-split-workflow
description: User splits work across models — Opus for analysis/architecture/spec-writing, Haiku for mechanical coding; hand off with precise self-contained specs
metadata:
  type: feedback
---

The user deliberately switches models mid-session via `/model`: a stronger model (Opus) for analysis, architecture decisions, and investigation, then a cheaper model (Haiku) for mechanical/repetitive coding execution.

**Why:** Observed directly — Opus was used for the class-architecture refactoring analysis, the stats homogenization (root-causing a latent dual-store bug), and writing QoL specs; then the user said "Let's have the Haiku model do the coding. Just tell it what to do." The expensive model's value is reasoning/diagnosis; the cheap model executes well-specified mechanical changes.

**How to apply:**
- When a design/diagnosis is settled and the remaining work is mechanical (find/replace across many call sites, applying a known pattern, wiring up an existing widget), offer a **precise, self-contained spec** the user can hand to Haiku instead of doing it all in the expensive model.
- Specs for Haiku must be explicit: exact file paths, line numbers, the current code string, and the target code string. Haiku does poorly with vague or open-ended instructions and needs the synthesis already done.
- Mark anything already implemented as DONE so the cheaper model rebuilds/verifies rather than redoing it.
- Related: [[feedback-gui-not-tested]], [[architecture-agent-as-character]].
