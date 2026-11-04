"""Structural checks of small definitions, not YAML/JSONC parsing or live loading."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMAND_PROFILES = {
    'quick': ('sol-direct', 'AgentRouter-openai-gateway/gpt-6.1-sol#medium'),
    'full': ('sol-orchestrator', 'AgentRouter-openai-gateway/gpt-6.1-sol#medium'),
}
IMPLEMENTER_MODEL = 'AgentRouter-openai-gateway/gpt-5.6-sol#medium'


class OpenCodeWorkflowTests(unittest.TestCase):
    def read_definition(self, relative_path):
        text = (ROOT / relative_path).read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---\n'), relative_path)
        frontmatter, separator, body = text[4:].partition('\n---\n')
        self.assertTrue(separator, relative_path)
        return frontmatter, body.strip()

    def assert_field(self, frontmatter, key, expected):
        lines = [line for line in frontmatter.splitlines()
                 if line.startswith(f'{key}:')]
        self.assertEqual(lines, [f'{key}: {expected}'])

    def test_commands_select_exact_current_session_profiles(self):
        for command, (agent, model) in COMMAND_PROFILES.items():
            with self.subTest(command=command):
                frontmatter, _ = self.read_definition(
                    f'.opencode/commands/{command}.md')
                self.assert_field(frontmatter, 'agent', agent)
                self.assert_field(frontmatter, 'model', model)
                self.assert_field(frontmatter, 'subagent', 'false')
                self.assertRegex(frontmatter, r'(?m)^description: \S.+$')
                self.assertEqual(len(frontmatter.splitlines()), 4)

    def test_no_stale_full_high_variant_remains(self):
        for relative_path in (
            '.opencode/agents/sol-orchestrator.md',
            '.opencode/commands/full.md',
            'AGENTS.md',
            'README.md',
        ):
            with self.subTest(relative_path=relative_path):
                text = (ROOT / relative_path).read_text(encoding='utf-8')
                self.assertNotRegex(
                    text,
                    r'AgentRouter-openai-gateway/gpt-6\.1-sol#high'
                    r'|Sol(?: 6\.1)? High',
                )

    def test_command_arguments_are_plain_prompt_text(self):
        for command in COMMAND_PROFILES:
            with self.subTest(command=command):
                _, body = self.read_definition(f'.opencode/commands/{command}.md')
                self.assertEqual(body.splitlines().count('$ARGUMENTS'), 1)
                self.assertEqual(body.count('$'), 1)
                self.assertNotRegex(body, r'(?m)!\s*`|\$\(|\$\{|^\s*(?:```|~~~)')

    def test_templates_keep_empty_task_and_workflow_guards(self):
        bodies = {}
        for command in COMMAND_PROFILES:
            with self.subTest(command=command):
                _, body = self.read_definition(f'.opencode/commands/{command}.md')
                bodies[command] = ' '.join(body.split())
                self.assertIn('If no task was supplied, ask', bodies[command])
                self.assertIn('without editing.', bodies[command])
        self.assertIn('without delegation or extra planning/handoff', bodies['quick'])
        self.assertIn('stop before editing and ask the user to select Full', bodies['quick'])
        self.assertIn('Do not auto-switch agents/models.', bodies['quick'])
        self.assertIn('delegate every implementation edit', bodies['full'])
        self.assertIn('personally run final verification.', bodies['full'])

    def test_full_remains_the_new_session_default(self):
        config = (ROOT / 'opencode.jsonc').read_text(encoding='utf-8')
        self.assertIn('  "$schema": "https://opencode.ai/config.json",\n', config)
        self.assertIn('  "default_agent": "sol-orchestrator",\n', config)
        self.assertIn('  "model": "AgentRouter-openai-gateway/gpt-6.1-sol",\n', config)

    def test_explore_remains_read_only_without_children(self):
        config = (ROOT / 'opencode.jsonc').read_text(encoding='utf-8')
        expected = (
            '    "explore": {\n'
            '      "permissions": [\n'
            '        { "action": "edit", "resource": "*", "effect": "deny" },\n'
            '        { "action": "shell", "resource": "*", "effect": "deny" },\n'
            '        { "action": "subagent", "resource": "*", "effect": "deny" }\n'
            '      ]\n'
            '    }'
        )
        self.assertIn(expected, config)

    def test_primary_and_implementation_profiles_remain_separate(self):
        profiles = {
            'sol-orchestrator': ('primary', COMMAND_PROFILES['full'][1]),
            'sol-direct': ('primary', 'AgentRouter-openai-gateway/gpt-5.6-sol#medium'),
            'sol-implementer': ('subagent', IMPLEMENTER_MODEL),
        }
        for agent, (mode, model) in profiles.items():
            with self.subTest(agent=agent):
                frontmatter, _ = self.read_definition(f'.opencode/agents/{agent}.md')
                self.assert_field(frontmatter, 'mode', mode)
                self.assert_field(frontmatter, 'model', model)

    def test_sol_profiles_cannot_launch_children(self):
        for agent in ('sol-direct', 'sol-implementer'):
            with self.subTest(agent=agent):
                frontmatter, _ = self.read_definition(f'.opencode/agents/{agent}.md')
                self.assertEqual(
                    frontmatter.partition('permissions:\n')[2],
                    '  - action: subagent\n    resource: "*"\n    effect: deny',
                )

    def test_orchestrator_cannot_edit_or_use_quick_as_a_fallback(self):
        frontmatter, _ = self.read_definition('.opencode/agents/sol-orchestrator.md')
        expected = (
            '  - action: edit\n    resource: "*"\n    effect: deny\n'
            '  - action: subagent\n    resource: "*"\n    effect: deny\n'
            '  - action: subagent\n    resource: sol-implementer\n'
            '    effect: allow\n'
            '  - action: subagent\n    resource: explore\n    effect: allow'
        )
        self.assertEqual(frontmatter.partition('permissions:\n')[2], expected)

    def test_no_stale_astra_primary_remains(self):
        self.assertFalse((ROOT / '.opencode/agents/astra-orchestrator.md').exists())
        for relative_path in (
            '.opencode/agents/sol-orchestrator.md',
            '.opencode/agents/sol-implementer.md',
            '.opencode/commands/full.md',
            'opencode.jsonc', 'AGENTS.md', 'README.md',
        ):
            with self.subTest(relative_path=relative_path):
                text = (ROOT / relative_path).read_text(encoding='utf-8')
                self.assertNotIn('astra', text.lower())

    def test_full_instructions_require_the_5_6_implementer(self):
        _, body = self.read_definition('.opencode/agents/sol-orchestrator.md')
        instructions = ' '.join(body.split())
        self.assertIn('Delegate every implementation edit', instructions)
        self.assertIn('`sol-implementer`', instructions)
        self.assertIn(f'`{IMPLEMENTER_MODEL}`', instructions)
        self.assertIn(
            'Stop and report if its profile is missing or does not use',
            instructions,
        )
        for relative_path in ('AGENTS.md', 'README.md'):
            with self.subTest(relative_path=relative_path):
                text = ' '.join(
                    (ROOT / relative_path).read_text(encoding='utf-8').split())
                self.assertIn('`sol-orchestrator`', text)
                self.assertIn(f'`{COMMAND_PROFILES["full"][1]}`', text)
                self.assertIn(f'`{IMPLEMENTER_MODEL}`', text)
                self.assertIn('stop and report the blocker', text)
                self.assertIn('Existing sessions do not auto-switch', text)
                self.assertIn('updated `/full <task>`', text)
                self.assertIn('fresh session', text)


if __name__ == '__main__':
    unittest.main()
