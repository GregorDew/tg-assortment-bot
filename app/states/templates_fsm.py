from aiogram.fsm.state import State, StatesGroup


class TemplateWizardFSM(StatesGroup):
    """FSM для створення шаблонів повідомлень."""
    waiting_for_name = State()
    waiting_for_platform = State()
    waiting_for_title = State()
    waiting_for_body = State()
