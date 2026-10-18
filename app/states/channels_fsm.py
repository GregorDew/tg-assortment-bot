from aiogram.fsm.state import State, StatesGroup


class ChannelWizardFSM(StatesGroup):
    """FSM для створення каналів публікації (Telegram, Discord, HTTP, Email)."""
    waiting_for_type = State()
    waiting_for_name = State()
    waiting_for_config = State()
