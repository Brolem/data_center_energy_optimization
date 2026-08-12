from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class PaperCommand:
    name: str
    study: str | None
    arguments: argparse.Namespace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m experiments.paper")
    commands = parser.add_subparsers(dest="name", required=True)
    commands.add_parser("day-ahead")
    sensitivity = commands.add_parser("sensitivity")
    sensitivity.add_subparsers(dest="study", required=True).add_parser(
        "flex-ratio"
    )
    return parser


def parse_command(argv: list[str] | None = None) -> PaperCommand:
    arguments = _build_parser().parse_args(argv)
    return PaperCommand(
        name=arguments.name,
        study=getattr(arguments, "study", None),
        arguments=arguments,
    )
