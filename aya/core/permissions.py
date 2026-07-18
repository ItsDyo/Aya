from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum


logger = logging.getLogger(__name__)


class AccessChannel(StrEnum):
    LOCAL_TERMINAL = "local_terminal"
    LOCAL_GRADIO = "local_gradio"
    REMOTE_GRADIO = "remote_gradio"
    LIMITED_INTEGRATION = "limited_integration"


class Capability(StrEnum):
    CHAT = "chat"
    COMPANION = "companion"
    STUDY = "study"
    STATUS = "status"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    MEMORY_AUTO_WRITE = "memory_auto_write"
    MEMORY_CURATE = "memory_curate"
    KNOWLEDGE_READ = "knowledge_read"
    KNOWLEDGE_WRITE = "knowledge_write"
    RAG_READ = "rag_read"
    FILE_INGEST = "file_ingest"
    PROJECT_ACCESS = "project_access"
    BACKUP_MANAGE = "backup_manage"
    SYSTEM_ADMIN = "system_admin"
    SYSTEM_DIAGNOSTICS = "system_diagnostics"
    DATA_EXPORT = "data_export"


ALL_CAPABILITIES = frozenset(Capability)

REMOTE_CAPABILITIES = frozenset(
    {
        Capability.CHAT,
        Capability.COMPANION,
        Capability.STUDY,
        Capability.STATUS,
        Capability.MEMORY_READ,
        Capability.KNOWLEDGE_READ,
        Capability.RAG_READ,
    }
)

LIMITED_CAPABILITIES = frozenset(
    {
        Capability.CHAT,
        Capability.STUDY,
        Capability.STATUS,
        Capability.KNOWLEDGE_READ,
    }
)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    channel: AccessChannel
    capability: Capability
    reason: str


class PermissionManager:
    """Autoriza capacidades de acordo com a origem da solicitacao."""

    POLICIES = {
        AccessChannel.LOCAL_TERMINAL: ALL_CAPABILITIES,
        AccessChannel.LOCAL_GRADIO: ALL_CAPABILITIES,
        AccessChannel.REMOTE_GRADIO: REMOTE_CAPABILITIES,
        AccessChannel.LIMITED_INTEGRATION: LIMITED_CAPABILITIES,
    }

    def normalize_channel(self, channel: AccessChannel | str) -> AccessChannel:
        if isinstance(channel, AccessChannel):
            return channel
        try:
            return AccessChannel(str(channel))
        except ValueError:
            logger.warning("Canal de acesso desconhecido; aplicando perfil limitado")
            return AccessChannel.LIMITED_INTEGRATION

    def decide(self, channel: AccessChannel | str, capability: Capability) -> PermissionDecision:
        normalized = self.normalize_channel(channel)
        allowed = capability in self.POLICIES[normalized]
        reason = "capacidade permitida" if allowed else "capacidade bloqueada neste canal"
        return PermissionDecision(allowed, normalized, capability, reason)

    def allows(self, channel: AccessChannel | str, capability: Capability) -> bool:
        return self.decide(channel, capability).allowed

    def denial_message(self, channel: AccessChannel | str, capability: Capability) -> str:
        decision = self.decide(channel, capability)
        logger.warning(
            "Acao negada: channel=%s capability=%s",
            decision.channel.value,
            decision.capability.value,
        )
        return (
            "Esta acao administrativa esta bloqueada neste canal por seguranca. "
            "Execute-a pelo terminal local ou pelo Gradio aberto somente neste computador."
        )
