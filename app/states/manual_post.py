from aiogram.fsm.state import State, StatesGroup


class ManualPostFSM(StatesGroup):
    """Стани FSM для покрокового створення посту адміном."""
    waiting_for_photo = State()        # Очікування фото товару
    waiting_for_title = State()        # Очікування назви товару
    waiting_for_description = State()  # Очікування опису
    waiting_for_price = State()        # Очікування ціни
