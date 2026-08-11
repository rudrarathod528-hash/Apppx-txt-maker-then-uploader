"""FSM states — PRD section 1 (login flow)."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class LoginStates(StatesGroup):
    inst_search = State()   # institute name search
    manual_url = State()    # manual API URL
    username = State()      # course id / username
    password = State()      # password
