---
description: Opt into Quick for a tiny, bounded, low-risk fix with Sol Medium
agent: sol-direct
model: AgentRouter-openai-gateway/gpt-6.1-sol#medium
subagent: false
---

Handle this user-selected Quick task:
$ARGUMENTS

If no task was supplied, ask what to fix without editing.
Follow sol-direct and AGENTS.md for tiny, bounded, low-risk work: inspect first,
implement directly without delegation or extra planning/handoff, keep edits
minimal, review the diff, personally run required checks, and briefly report
changed files, results, and limitations.
For security-sensitive work, upload validation/privacy changes, or coordinated
cross-module changes, stop before editing and ask the user to select Full.
Do not auto-switch agents/models.
