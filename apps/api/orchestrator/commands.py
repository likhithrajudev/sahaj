"""Text-only shortcuts handled without sending command text to the language model."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Command:
    name: str
    argument: str = ""


COMMANDS = {"/help", "/usage", "/clear", "/language"}


def parse(text: str) -> Optional[Command]:
    value = text.strip()
    if not value.startswith("/"):
        return None
    name, _, argument = value.partition(" ")
    return Command(name.lower(), argument.strip())
