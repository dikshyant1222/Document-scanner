---
description: Select Full with Sol Medium for delegated implementation and final review
agent: sol-orchestrator
model: AgentRouter-openai-gateway/gpt-6.1-sol#medium
subagent: false
---

Handle this user-selected Full task:
$ARGUMENTS

If no task was supplied, ask what to work on without editing.
Follow sol-orchestrator and AGENTS.md: delegate every implementation edit to
the configured sol-implementer, review its diff, and personally run final
verification. Preserve the existing Full permissions and workflow.
