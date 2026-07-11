from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aya.core.permissions import AccessChannel, Capability, PermissionManager


CapabilityResolver = Callable[[str, str], Capability]


@dataclass(frozen=True)
class ParsedCommand:
    raw: str
    name: str
    payload: str
    original_name: str
    is_command: bool


@dataclass(frozen=True)
class CommandRoute:
    parsed: ParsedCommand
    known: bool
    capability: Capability
    allowed: bool


class CommandRouter:
    """Interpreta comandos explicitos sem executar regras de negocio."""

    def __init__(
        self,
        commands: set[str],
        permissions: PermissionManager,
        capability_resolver: CapabilityResolver,
    ):
        self.commands = set(commands)
        self.permissions = permissions
        self.capability_resolver = capability_resolver

    def parse(self, text: str) -> ParsedCommand:
        raw = (text or "").strip()
        original_name, _, payload = raw.partition(" ")
        name = original_name.lower()
        return ParsedCommand(
            raw=raw,
            name=name,
            payload=payload.strip(),
            original_name=original_name,
            is_command=name.startswith("/"),
        )

    def route(self, text: str, channel: AccessChannel | str) -> CommandRoute:
        normalized_channel = self.permissions.normalize_channel(channel)
        parsed = self.parse(text)
        known = parsed.name in self.commands
        capability = self.capability_resolver(parsed.name, parsed.payload)
        allowed = self.permissions.allows(normalized_channel, capability)
        return CommandRoute(
            parsed=parsed,
            known=known,
            capability=capability,
            allowed=allowed,
        )
