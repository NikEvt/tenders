"""Порт действующих настроек."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.api.domain.settings import EffectiveSettings


class RuntimeSettingsPort(ABC):
    @abstractmethod
    def effective(self) -> EffectiveSettings:
        """Значения, с которыми процесс работает прямо сейчас."""
