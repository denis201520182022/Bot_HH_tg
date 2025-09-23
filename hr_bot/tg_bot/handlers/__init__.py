# hr_bot/tg_bot/handlers/__init__.py

from aiogram import Router
from . import common, admin

main_router = Router()
main_router.include_router(admin.router)
main_router.include_router(common.router)