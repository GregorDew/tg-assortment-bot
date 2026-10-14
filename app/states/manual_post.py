from aiogram.fsm.state import State, StatesGroup


class ManualPostFSM(StatesGroup):
    """Стани FSM для покрокового створення посту адміном."""
    waiting_for_photo = State()        # Очікування фото товару
    waiting_for_title = State()        # Очікування назви товару
    waiting_for_description = State()  # Очікування опису
    waiting_for_price = State()        # Очікування ціни


class EditProductFSM(StatesGroup):
    """Стани FSM для редагування окремих полів посту перед публікацією."""
    waiting_for_new_title = State()        # Очікування нової назви
    waiting_for_new_description = State()  # Очікування нового опису
    waiting_for_new_price = State()        # Очікування нової ціни
    waiting_for_new_photo = State()        # Очікування нового фото

