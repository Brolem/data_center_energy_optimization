from __future__ import annotations

import unittest


class PaperCliRoutingTests(unittest.TestCase):
    @staticmethod
    def _parse_command(arguments: list[str]) -> object:
        try:
            from experiments.paper.cli import parse_command
        except ModuleNotFoundError as error:
            raise AssertionError(
                "experiments.paper.cli must provide parse_command"
            ) from error
        return parse_command(arguments)

    def test_day_ahead_command_preserves_formal_defaults(self) -> None:
        command = self._parse_command(["day-ahead"])

        self.assertEqual(command.name, "day-ahead")
        self.assertIsNone(command.study)

    def test_sensitivity_command_requires_exact_study_name(self) -> None:
        command = self._parse_command(["sensitivity", "flex-ratio"])

        self.assertEqual(command.name, "sensitivity")
        self.assertEqual(command.study, "flex-ratio")


if __name__ == "__main__":
    unittest.main()
