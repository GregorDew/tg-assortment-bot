from aiogram.fsm.state import State, StatesGroup


class SourceWizardFSM(StatesGroup):
    """FSM для покрокового 10-етапного майстра підключення джерела даних."""
    waiting_for_type = State()
    waiting_for_name = State()
    waiting_for_params = State()
    waiting_for_table = State()
    waiting_for_fields = State()
    waiting_for_pk = State()
    waiting_for_tracking_mode = State()
    waiting_for_tracking_field = State()
    waiting_for_confirmation = State()
