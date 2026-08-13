"""Настройки: показ действующих значений и отметка о ротации токена."""

from __future__ import annotations

from fastapi import APIRouter, Response

from services.api.presentation.deps import ConfirmTokenRotation, ReadSettings
from services.api.presentation.schemas import SettingsOut

router = APIRouter(tags=["Настройки"], prefix="/settings")


@router.get("", response_model=SettingsOut)
async def settings(use_case: ReadSettings) -> SettingsOut:
    """То, с чем процесс работает прямо сейчас, а не содержимое `.env`.

    Секреты маскированы. `restart_required_keys` перечисляет ключи, которые
    читаются только на старте: правка без перезапуска ничего не изменит.
    """
    return SettingsOut.of(await use_case.execute())


@router.post("/eis-token/rotated", status_code=204)
async def confirm_token_rotation(use_case: ConfirmTokenRotation) -> Response:
    """Отметка «токен перевыпущен».

    Сам токен приходит из окружения и шлюзу неподвластен — записывается только
    факт и время.
    """
    await use_case.execute()
    return Response(status_code=204)
