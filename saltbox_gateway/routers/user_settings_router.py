from typing import Annotated

from fastapi import APIRouter, Body, Depends

from saltbox_gateway.services.user_settings import UserSettingsService, get_user_settings_service

router = APIRouter(prefix='/api/user-settings', tags=['User Settings'])


@router.get('', operation_id='get_user_settings')
async def get_user_settings(
    settings_service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> dict:
    return await settings_service.get()


@router.post('', operation_id='create_or_update_user_settings')
async def create_or_update_user_settings(
    settings: Annotated[dict, Body()],
    settings_service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> dict:
    return await settings_service.create_or_update(settings=settings)
