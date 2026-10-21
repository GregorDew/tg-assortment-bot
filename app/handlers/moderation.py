import json
import logging
from datetime import datetime
from typing import Optional, Tuple

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.config import settings
from app.core.connectors.base import PreparedPost
from app.core.rules.engine import dispatch_to_channels
from app.database.database import async_session_maker
from app.database.models import PendingPublicationModel, Product, PublishRuleModel
from app.filters.admin import IsAdminFilter
from app.keyboards.admin_kb import (
    get_cancel_edit_kb,
    get_edit_menu_kb,
    get_preview_moderation_kb,
)
from app.services.delivery import broadcast_post, broadcast_product, format_broadcast_report
from app.services.product_service import ProductService
from app.services.publisher import PublisherService
from app.states.manual_post import EditProductFSM

logger = logging.getLogger(__name__)

router = Router()
router.callback_query.filter(IsAdminFilter())
router.message.filter(IsAdminFilter())

OPEN_STATUSES = ("pending", "waiting_approval")


async def _load_targets(session, raw_id: int) -> Tuple[Optional[Product], Optional[PendingPublicationModel]]:
    product = await ProductService.get_product_by_id(session, raw_id)
    pending = (
        await session.execute(select(PendingPublicationModel).where(PendingPublicationModel.id == raw_id))
    ).scalar_one_or_none()
    return product, pending


def _product_is_open(product: Optional[Product]) -> bool:
    return bool(product and product.status in OPEN_STATUSES)


def _pending_is_open(pending: Optional[PendingPublicationModel]) -> bool:
    return bool(pending and pending.status == "pending")


async def send_product_card(bot, chat_id: int, product: Product) -> None:
    await PublisherService.send_product_post(
        bot=bot,
        chat_id=chat_id,
        product=product,
        is_preview=True,
        reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME),
    )


async def send_pending_card(bot, chat_id: int, pending: PendingPublicationModel, rule_name: str = "") -> None:
    prepared = {}
    try:
        prepared = json.loads(pending.prepared_data_json or "{}")
    except Exception:
        prepared = {}
    body = prepared.get("body") or pending.prepared_data_json
    caption = (
        f"👁 <b>[ПОГОДЖЕННЯ #{pending.id}]</b>\n"
        f"{'Правило: ' + rule_name + chr(10) if rule_name else ''}"
        f"───────────────────────\n{body}"
    )
    markup = get_preview_moderation_kb(pending.id, settings.MANAGER_USERNAME)
    photo = prepared.get("photo_url")
    if photo:
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode="HTML", reply_markup=markup)
    else:
        await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML", reply_markup=markup)


async def send_next_queue_item(bot, chat_id: int, skip_product_id: Optional[int] = None, skip_pending_id: Optional[int] = None) -> bool:
    async with async_session_maker() as session:
        products = list(
            (
                await session.execute(
                    select(Product)
                    .where(Product.status.in_(OPEN_STATUSES))
                    .order_by(Product.created_at.asc())
                )
            ).scalars().all()
        )
        pendings = list(
            (
                await session.execute(
                    select(PendingPublicationModel)
                    .where(PendingPublicationModel.status == "pending")
                    .order_by(PendingPublicationModel.created_at.asc())
                )
            ).scalars().all()
        )

    products = [p for p in products if p.id != skip_product_id]
    pendings = [p for p in pendings if p.id != skip_pending_id]
    if not products and not pendings:
        await bot.send_message(chat_id, "✅ Черга порожня. Усі товари оброблено.")
        return False

    await bot.send_message(
        chat_id,
        f"📦 Наступний з черги. Залишилось: товарів {len(products)}, із джерел {len(pendings)}.",
    )
    if products:
        await send_product_card(bot, chat_id, products[0])
        return True
    await send_pending_card(bot, chat_id, pendings[0])
    return True


@router.callback_query(F.data == "mod:queue:next")
async def show_next_from_button(callback: CallbackQuery):
    await callback.answer()
    await send_next_queue_item(callback.bot, callback.from_user.id)


@router.callback_query(F.data.startswith("mod:publish:"))
async def process_publish_decision(callback: CallbackQuery):
    raw_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        product, pending = await _load_targets(session, raw_id)

        if _product_is_open(product):
            outcome = await broadcast_product(session, callback.bot, product)
            if outcome["ok"]:
                await ProductService.update_product_status(
                    session,
                    product.id,
                    "published",
                    moderated_by=callback.from_user.username or str(callback.from_user.id),
                )
                report = format_broadcast_report(
                    f"✅ Товар #{product.id} «{product.title}» погоджено.",
                    outcome,
                )
            else:
                report = format_broadcast_report(
                    f"❌ Товар #{product.id} погоджено в боті, але в канали НІЧОГО не пішло.",
                    outcome,
                )
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.answer("Готово" if outcome["ok"] else "Не відправлено", show_alert=not outcome["ok"])
            await callback.message.answer(report, parse_mode="HTML")
            await send_next_queue_item(callback.bot, callback.from_user.id, skip_product_id=product.id)
            return

        if _pending_is_open(pending):
            rule = (
                await session.execute(select(PublishRuleModel).where(PublishRuleModel.id == pending.rule_id))
            ).scalar_one_or_none()
            channel_ids = []
            if rule and rule.channel_ids_json:
                try:
                    channel_ids = [int(x) for x in json.loads(rule.channel_ids_json)]
                except Exception:
                    channel_ids = []
            prepared = {}
            try:
                prepared = json.loads(pending.prepared_data_json or "{}")
            except Exception:
                prepared = {}
            post = PreparedPost(
                title=prepared.get("title"),
                body=prepared.get("body") or "",
                photo_url=prepared.get("photo_url"),
                manager_button_url=prepared.get("manager_button_url"),
            )
            if channel_ids:
                ext_ids = await dispatch_to_channels(
                    session=session,
                    bot=callback.bot,
                    channel_ids=channel_ids,
                    post=post,
                    rule_id=pending.rule_id,
                    source_id=pending.source_id,
                    record_id=pending.record_id,
                    event_type=pending.event_type or "new",
                )
                ok = bool(ext_ids)
                reports = [f"Канали правила: {channel_ids}", f"Результат id: {ext_ids or 'порожньо'}"]
                if not ok:
                    # Fallback: усі активні канали, якщо правило нічого не відправило
                    outcome = await broadcast_post(
                        session,
                        callback.bot,
                        post,
                        record_id=str(pending.record_id),
                        event_type="pending",
                    )
                    report = format_broadcast_report(
                        f"{'✅' if outcome['ok'] else '❌'} Запис джерела #{pending.id}",
                        outcome,
                    )
                    ok = outcome["ok"]
                else:
                    report = "✅ Запис джерела опубліковано в канали правила.\n" + "\n".join(reports)
            else:
                outcome = await broadcast_post(
                    session,
                    callback.bot,
                    post,
                    record_id=str(pending.record_id),
                    event_type="pending",
                )
                report = format_broadcast_report(
                    f"{'✅' if outcome['ok'] else '❌'} Запис джерела #{pending.id}",
                    outcome,
                )
                ok = outcome["ok"]

            if ok:
                pending.status = "published"
                pending.moderated_by = callback.from_user.username or str(callback.from_user.id)
                pending.moderated_at = datetime.utcnow()
                await session.commit()
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.answer("Готово" if ok else "Не відправлено", show_alert=not ok)
            await callback.message.answer(report, parse_mode="HTML")
            await send_next_queue_item(callback.bot, callback.from_user.id, skip_pending_id=pending.id)
            return

        await callback.answer("Цей товар уже оброблено. Повторно не відправляю.", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("mod:reject:"))
async def process_reject_decision(callback: CallbackQuery):
    raw_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        product, pending = await _load_targets(session, raw_id)
        who = callback.from_user.username or str(callback.from_user.id)
        if _product_is_open(product):
            await ProductService.update_product_status(session, product.id, "rejected", moderated_by=who)
            skip_p, skip_u = product.id, None
        elif _pending_is_open(pending):
            pending.status = "rejected"
            pending.moderated_by = who
            pending.moderated_at = datetime.utcnow()
            await session.commit()
            skip_p, skip_u = None, pending.id
        else:
            await callback.answer("Цей товар уже оброблено.", show_alert=True)
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("Відхилено")
    await callback.message.answer("❌ Товар відхилено. У канали нічого не надсилалось.")
    await send_next_queue_item(callback.bot, callback.from_user.id, skip_product_id=skip_p, skip_pending_id=skip_u)


@router.callback_query(F.data.startswith("mod:edit:"))
async def start_edit_product(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[-1])
    async with async_session_maker() as session:
        product = await ProductService.get_product_by_id(session, product_id)
    if not _product_is_open(product):
        await callback.answer("Редагувати можна лише товар із черги бота (не запис джерела).", show_alert=True)
        return
    await state.clear()
    await callback.message.answer(
        f"✏️ Редагування товару #{product_id}. Що змінити?",
        reply_markup=get_edit_menu_kb(product_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_f:back:"))
async def back_to_preview(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[-1])
    await state.clear()
    async with async_session_maker() as session:
        product = await ProductService.get_product_by_id(session, product_id)
    if not product:
        await callback.answer("Товар не знайдено", show_alert=True)
        return
    await send_product_card(callback.bot, callback.from_user.id, product)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_f:title:"))
async def edit_title(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[-1])
    await state.update_data(edit_product_id=product_id)
    await state.set_state(EditProductFSM.waiting_for_new_title)
    await callback.message.answer("Введіть нову назву:", reply_markup=get_cancel_edit_kb(product_id))
    await callback.answer()


@router.callback_query(F.data.startswith("edit_f:desc:"))
async def edit_desc(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[-1])
    await state.update_data(edit_product_id=product_id)
    await state.set_state(EditProductFSM.waiting_for_new_description)
    await callback.message.answer("Введіть новий опис:", reply_markup=get_cancel_edit_kb(product_id))
    await callback.answer()


@router.callback_query(F.data.startswith("edit_f:price:"))
async def edit_price(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[-1])
    await state.update_data(edit_product_id=product_id)
    await state.set_state(EditProductFSM.waiting_for_new_price)
    await callback.message.answer("Введіть нову ціну:", reply_markup=get_cancel_edit_kb(product_id))
    await callback.answer()


@router.callback_query(F.data.startswith("edit_f:photo:"))
async def edit_photo(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[-1])
    await state.update_data(edit_product_id=product_id)
    await state.set_state(EditProductFSM.waiting_for_new_photo)
    await callback.message.answer(
        "Надішліть нове фото:",
        reply_markup=get_cancel_edit_kb(product_id, allow_remove_photo=True),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_f:remove_photo:"))
async def remove_photo(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[-1])
    await state.clear()
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, clear_photo=True)
    if product:
        await send_product_card(callback.bot, callback.from_user.id, product)
    await callback.answer("Фото прибрано")


@router.message(EditProductFSM.waiting_for_new_title, F.text)
async def save_new_title(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    await state.clear()
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, title=message.text.strip())
    if product:
        await send_product_card(message.bot, message.chat.id, product)


@router.message(EditProductFSM.waiting_for_new_description, F.text)
async def save_new_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    await state.clear()
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, description=message.text.strip())
    if product:
        await send_product_card(message.bot, message.chat.id, product)


@router.message(EditProductFSM.waiting_for_new_price, F.text)
async def save_new_price(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    await state.clear()
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, price=message.text.strip())
    if product:
        await send_product_card(message.bot, message.chat.id, product)


@router.message(EditProductFSM.waiting_for_new_photo, F.photo)
async def save_new_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    await state.clear()
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(
            session, product_id, photo_file_id=message.photo[-1].file_id
        )
    if product:
        await send_product_card(message.bot, message.chat.id, product)
