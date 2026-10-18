from aiogram.fsm.state import State, StatesGroup


class RuleWizardFSM(StatesGroup):
    """FSM для створення правил маршрутизації та публікації."""
    waiting_for_name = State()
    waiting_for_source = State()
    waiting_for_channels = State()
    waiting_for_template = State()
    waiting_for_mode = State()
    waiting_for_update_action = State()
    waiting_for_interval = State()
