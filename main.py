"""
AcademAudit Lead Qualification & Order Bot
Стек: Python 3.10+, aiogram 3.x, python-dotenv
"""

import os
import sys
import logging
from typing import Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    BotCommand,
)

# 1. Загрузка конфигурации
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID_RAW = os.getenv("ADMIN_CHAT_ID", "").strip()
MANAGER_USERNAME = os.getenv("MANAGER_USERNAME", "AcademAudit_Support").replace("@", "").strip()

if not BOT_TOKEN:
    logging.critical("Ошибка: BOT_TOKEN не задан в .env файле!")
    sys.exit(1)

try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW)
except ValueError:
    logging.critical("Ошибка: ADMIN_CHAT_ID должен быть числовым идентификатором Telegram!")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("AcademAuditBot")


# 2. Машина состояний (FSM)
class OrderStates(StatesGroup):
    waiting_for_subject = State()       # Выбор направления или ручной ввод
    waiting_for_custom_subject = State()# Ручной ввод направления, если нажато "Другое"
    waiting_for_topic = State()         # Ввод темы курсовой
    waiting_for_deadline = State()      # Выбор срока сдачи
    waiting_for_file = State()          # Загрузка методички/плана
    waiting_for_contact = State()       # Номер телефона или контакт в Telegram


# 3. Фабрики клавиатур (UI/UX)
def get_start_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Начать расчет стоимости",
                    callback_data="start_quiz",
                )
            ]
        ]
    )


def get_subjects_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚖️ Юриспруденция / Право", callback_data="subj_law"),
                InlineKeyboardButton(text="📊 Экономика / Менеджмент", callback_data="subj_econ"),
            ],
            [
                InlineKeyboardButton(text="💻 IT / Технические", callback_data="subj_tech"),
                InlineKeyboardButton(text="📚 Гуманитарные науки", callback_data="subj_hum"),
            ],
            [
                InlineKeyboardButton(text="🧪 Естественные науки", callback_data="subj_sci"),
                InlineKeyboardButton(text="✍️ Другое (ввести вручную)", callback_data="subj_other"),
            ],
        ]
    )


def get_topic_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❓ Темы еще нет (нужна помощь с выбором)",
                    callback_data="no_topic_yet",
                )
            ]
        ]
    )


def get_deadline_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡️ Срочно: 1–3 дня", callback_data="dl_urgent"),
            ],
            [
                InlineKeyboardButton(text="🔥 Оптимально: 4–7 дней", callback_data="dl_optimal"),
            ],
            [
                InlineKeyboardButton(text="⏳ Стандарт: от 10 дней", callback_data="dl_standard"),
            ],
        ]
    )


def get_file_skip_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➡️ Пропустить этот шаг (методички нет)",
                    callback_data="skip_file",
                )
            ]
        ]
    )


def get_contact_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📱 Отправить мой номер телефона", request_contact=True)
            ],
            [
                KeyboardButton(text="💬 Ответить здесь в Telegram")
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_final_expert_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написать эксперту прямо сейчас",
                    url=f"https://t.me/{MANAGER_USERNAME}",
                )
            ]
        ]
    )


# Словарь маппинга направлений
SUBJECT_MAP = {
    "subj_law": "Юриспруденция / Право",
    "subj_econ": "Экономика / Менеджмент",
    "subj_tech": "IT / Технические специальности",
    "subj_hum": "Гуманитарные науки / Педагогика",
    "subj_sci": "Естественные науки / Медицина",
}

# Словарь маппинга сроков
DEADLINE_MAP = {
    "dl_urgent": "⚡️ Срочно (1–3 дня)",
    "dl_optimal": "🔥 Оптимально (4–7 дней)",
    "dl_standard": "⏳ Стандарт (от 10 дней)",
}


# 4. Роутер и обработчики диалога
router = Router()


# --- Шаг 0: Команда /start с обработкой кнопки из канала (?start=audit) ---
@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    
    raw_args = (command.args or "").strip().lower()
    first_name = message.from_user.first_name if message.from_user else "Студент"

    # СЦЕНАРИЙ: Клик по кнопке «Проверить курсовую в боте» из поста в канале (?start=audit)
    if raw_args and any(keyword in raw_args for keyword in ["audit", "calc", "check", "channel"]):
        utm_source = f"Telegram-канал (кнопка 'Проверить курсовую', метка: {raw_args})"
        await state.update_data(utm_source=utm_source)
        await state.set_state(OrderStates.waiting_for_subject)

        audit_intro = (
            f"Привет, {first_name}! 👋\n\n"
            f"🎯 <b>Запускаем экспресс-проверку курсовой работы по ГОСТ 2026.</b>\n"
            f"Мы бесплатно сверим тему со стандартами ВАК, оценим сложность расчетов "
            f"и риски закрытых баз Антиплагиат.ВУЗ.\n\n"
            f"<b>Шаг 1 из 4.</b> Выбери профиль твоей дисциплины:\n"
            f"<i>Это необходимо для подбора профильного эксперта кафедры 👇</i>"
        )
        await message.answer(
            text=audit_intro,
            reply_markup=get_subjects_inline_kb(),
        )
        return

    # ОБЫЧНЫЙ СТАРТ: Считывание любого другого реферального хвоста (например: ?start=avito_msk)
    utm_source = command.args if command.args else "Прямой переход (органический)"
    await state.update_data(utm_source=utm_source)
    
    greeting_text = (
        f"Привет, {first_name}! 👋\n"
        f"Я бот сервиса <b>AcademAudit</b>.\n\n"
        f"Помогу рассчитать точную стоимость и сроки подготовки твоей курсовой работы "
        f"по стандартам <b>ГОСТ 2026</b>, а также проверить тему и структуру на риски недопуска кафедрой.\n\n"
        f"Ответь на 4 коротких вопроса — это займет меньше минуты 👇"
    )
    
    await message.answer(
        text=greeting_text,
        reply_markup=get_start_inline_kb(),
    )


# Быстрые команды запуска проверки (/audit, /check, /calc)
@router.message(Command("audit", "check", "calc"))
async def handle_audit_command(message: Message, state: FSMContext):
    await state.clear()
    first_name = message.from_user.first_name if message.from_user else "Студент"
    await state.update_data(utm_source="Команда меню /audit")
    await state.set_state(OrderStates.waiting_for_subject)

    audit_text = (
        f"Привет, {first_name}! 👋\n\n"
        f"🎯 <b>Запускаем экспресс-проверку курсовой работы по ГОСТ 2026.</b>\n\n"
        f"<b>Шаг 1 из 4.</b> Выбери профиль твоей дисциплины 👇"
    )
    await message.answer(
        text=audit_text,
        reply_markup=get_subjects_inline_kb(),
    )


# Команда справки и поддержки (/help)
@router.message(Command("help"))
async def handle_help_command(message: Message):
    text = (
        "📚 <b>Сервис академического консалтинга и аудита «AcademAudit»</b>\n\n"
        "• Проверка по закрытым преподавательским базам <b>Антиплагиат.ВУЗ</b>\n"
        "• Соблюдение нормоконтроля по <b>ГОСТ 7.32-2017</b>\n"
        "• 0% предоплаты за первичный аудит темы и структуры\n"
        "• Бесплатные доработки до получения зачета\n\n"
        "Чтобы запустить расчет и проверку, нажмите /audit или /start."
    )
    await message.answer(text=text, reply_markup=get_final_expert_inline_kb())


# --- Шаг 1: Выбор дисциплины (waiting_for_subject) ---
@router.callback_query(F.data == "start_quiz")
async def start_quiz_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(OrderStates.waiting_for_subject)
    
    await callback.message.edit_text(
        text="<b>Шаг 1 из 4.</b> Выбери профиль твоей дисциплины:\n"
             "<i>Это необходимо для подбора профильного эксперта и актуальной базы нормоконтроля.</i>",
        reply_markup=get_subjects_inline_kb(),
    )


@router.callback_query(OrderStates.waiting_for_subject, F.data.startswith("subj_"))
async def process_subject_choice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    if callback.data == "subj_other":
        await state.set_state(OrderStates.waiting_for_custom_subject)
        await callback.message.edit_text(
            text="✍️ Напиши название твоей дисциплины или специальности в ответном сообщении:"
        )
        return
    
    subject_title = SUBJECT_MAP.get(callback.data, "Общая дисциплина")
    await state.update_data(subject=subject_title)
    
    await state.set_state(OrderStates.waiting_for_topic)
    await callback.message.edit_text(
        text=f"📚 Выбрано: <b>{subject_title}</b>\n\n"
             f"<b>Шаг 2 из 4.</b> Напиши тему твоей курсовой работы в ответном сообщении:",
        reply_markup=get_topic_inline_kb(),
    )


@router.message(OrderStates.waiting_for_custom_subject, F.text)
async def process_custom_subject(message: Message, state: FSMContext):
    subject_text = message.text.strip()
    if len(subject_text) < 2:
        await message.answer("Пожалуйста, введи корректное название предмета (минимум 2 буквы):")
        return

    await state.update_data(subject=subject_text)
    await state.set_state(OrderStates.waiting_for_topic)
    
    await message.answer(
        text=f"📚 Направление зафиксировано: <b>{subject_text}</b>\n\n"
             f"<b>Шаг 2 из 4.</b> Напиши тему твоей курсовой работы в ответном сообщении:",
        reply_markup=get_topic_inline_kb(),
    )


# --- Шаг 2: Тема работы (waiting_for_topic) ---
@router.callback_query(OrderStates.waiting_for_topic, F.data == "no_topic_yet")
async def process_no_topic(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    no_topic_text = "Тема не утверждена кафедрой (нужен бесплатный подбор 3 тем)"
    await state.update_data(topic=no_topic_text)
    
    await state.set_state(OrderStates.waiting_for_deadline)
    await callback.message.edit_text(
        text="💡 Отлично, наш эксперт подберет 3 темы под научного руководителя.\n\n"
             "<b>Шаг 3 из 4.</b> К какому числу нужна готовая работа?",
        reply_markup=get_deadline_inline_kb(),
    )


@router.message(OrderStates.waiting_for_topic, F.text)
async def process_topic_text(message: Message, state: FSMContext):
    topic_text = message.text.strip()
    if len(topic_text) < 4:
        await message.answer(
            "Слишком короткая тема. Напиши тему полнее или нажми кнопку ниже, если темы еще нет:",
            reply_markup=get_topic_inline_kb(),
        )
        return
        
    await state.update_data(topic=topic_text)
    await state.set_state(OrderStates.waiting_for_deadline)
    
    await message.answer(
        text=f"📝 Тема: <i>«{topic_text}»</i>\n\n"
             f"<b>Шаг 3 из 4.</b> К какому числу нужна готовая работа?",
        reply_markup=get_deadline_inline_kb(),
    )


# --- Шаг 3: Срок сдачи / Дедлайн (waiting_for_deadline) ---
@router.callback_query(OrderStates.waiting_for_deadline, F.data.startswith("dl_"))
async def process_deadline(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    deadline_text = DEADLINE_MAP.get(callback.data, "Стандартные сроки")
    await state.update_data(deadline=deadline_text)
    
    await state.set_state(OrderStates.waiting_for_file)
    await callback.message.edit_text(
        text=f"⏰ Срок: <b>{deadline_text}</b>\n\n"
             f"<b>Шаг 4 из 4.</b> Прикрепи методичку или утвержденный план <b>документом</b> (Word, PDF), если они есть.\n\n"
             f"<i>Если методички пока нет на руках — просто нажми кнопку «Пропустить»:</i>",
        reply_markup=get_file_skip_inline_kb(),
    )


# --- Шаг 4: Прикрепление файла методички (waiting_for_file) ---
@router.callback_query(OrderStates.waiting_for_file, F.data == "skip_file")
async def process_skip_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(file_id=None, file_name="Не прикреплена")
    
    await state.set_state(OrderStates.waiting_for_contact)
    await callback.message.answer(
        text="📞 <b>Последний шаг!</b> Куда направить предварительный расчет и ГОСТ-чеклист?\n\n"
             "Нажми кнопку <b>«📱 Отправить номер телефона»</b> или введи контакт вручную:",
        reply_markup=get_contact_reply_kb(),
    )


@router.message(OrderStates.waiting_for_file, F.document)
async def process_file_document(message: Message, state: FSMContext):
    document = message.document
    file_id = document.file_id
    file_name = document.file_name or "Методичка.pdf"
    
    await state.update_data(file_id=file_id, file_name=file_name)
    await state.set_state(OrderStates.waiting_for_contact)
    
    await message.answer(
        text=f"📎 Файл <b>«{file_name}»</b> успешно загружен!\n\n"
             f"📞 <b>Последний шаг!</b> Куда направить предварительный расчет и ГОСТ-чеклист?\n\n"
             f"Нажми кнопку ниже или введи контакт текстом в ответном сообщении:",
        reply_markup=get_contact_reply_kb(),
    )


# --- Шаг 5: Контактные данные и отправка заявки администратору ---
@router.message(OrderStates.waiting_for_contact, F.contact)
async def process_contact_button(message: Message, state: FSMContext, bot: Bot):
    phone_number = message.contact.phone_number
    if not phone_number.startswith("+"):
        phone_number = f"+{phone_number}"
    await finalize_order(message, state, bot, phone_contact=phone_number)


@router.message(OrderStates.waiting_for_contact, F.text)
async def process_contact_text(message: Message, state: FSMContext, bot: Bot):
    contact_text = message.text.strip()
    
    # Если нажал инлайн-вариант "Ответить здесь в Telegram"
    if "ответить здесь" in contact_text.lower():
        username = message.from_user.username
        contact_str = f"@{username}" if username else f"Telegram ID: {message.from_user.id}"
    else:
        contact_str = contact_text

    await finalize_order(message, state, bot, phone_contact=contact_str)


# Функция финализации заказа и отправки админу
async def finalize_order(message: Message, state: FSMContext, bot: Bot, phone_contact: str):
    data = await state.get_data()
    user = message.from_user
    
    username = f"@{user.username}" if user.username else "Не указан"
    full_name = user.full_name or "Без имени"
    user_id = user.id
    
    subject = data.get("subject", "Не указано")
    topic = data.get("topic", "Не утверждена")
    deadline = data.get("deadline", "Стандартный")
    file_id = data.get("file_id")
    file_name = data.get("file_name", "Не прикреплена")
    utm_source = data.get("utm_source", "Органический")
    
    has_file_str = f"Прикреплена ({file_name})" if file_id else "Не прикреплена"

    # Формируем карточку заказа для администратора
    admin_card_text = (
        "🚨 <b>НОВАЯ ЗАЯВКА НА КУРСОВУЮ!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Студент:</b> {username} (ID: <code>{user_id}</code>, Имя: {full_name})\n"
        f"📞 <b>Контакт:</b> {phone_contact}\n"
        f"📚 <b>Направление:</b> {subject}\n"
        f"📝 <b>Тема:</b> {topic}\n"
        f"⏰ <b>Дедлайн:</b> {deadline}\n"
        f"📎 <b>Методичка:</b> {has_file_str}\n"
        f"🏷 <b>Источник:</b> <code>{utm_source}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    
    # Кнопка для быстрого открытия диалога со студентом
    dialog_url = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user_id}"
    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Открыть диалог со студентом",
                    url=dialog_url,
                )
            ]
        ]
    )

    try:
        # 1. Отправляем карточку администратору
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_card_text,
            reply_markup=admin_kb,
        )
        
        # 2. Если был файл — пересылаем его следом за карточкой
        if file_id:
            await bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=file_id,
                caption=f"📎 Методичка к заказу от {username} (ID: {user_id})",
            )
        logger.info(f"Заявка от пользователя {user_id} ({username}) успешно доставлена админу.")
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу ({ADMIN_CHAT_ID}): {e}")

    # Финальное сообщение клиенту
    success_text = (
        "✅ <b>Заявка принята!</b>\n\n"
        "Наш академический специалист уже анализирует тему и методические требования. "
        "Мы свяжемся с тобой в течение <b>10–15 минут</b> с точным расчетом.\n\n"
        "🎁 Чек-лист по оформлению курсовой по ГОСТ 2026 уже зарезервирован за тобой!"
    )
    
    await message.answer(
        text=success_text,
        reply_markup=ReplyKeyboardRemove(),
    )
    
    await message.answer(
        text="Хочешь ускорить расчет или задать срочный вопрос?",
        reply_markup=get_final_expert_inline_kb(),
    )
    
    await state.clear()


# --- Обработчик некорректного контента (стикеры, аудио, кружочки) ---
@router.message()
async def fallback_unsupported_content(message: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state is None:
        await message.answer(
            "Для расчета курсовой нажми /start, /audit или воспользуйся меню бота 👇",
            reply_markup=get_start_inline_kb(),
        )
        return

    if current_state == OrderStates.waiting_for_file:
        await message.answer(
            "Пожалуйста, отправь методичку именно как <b>документ</b> (файл Word или PDF) "
            "или нажми кнопку «Пропустить этот шаг» 👇",
            reply_markup=get_file_skip_inline_kb(),
        )
    elif current_state == OrderStates.waiting_for_subject:
        await message.answer(
            "Пожалуйста, выбери один из вариантов направления на клавиатуре выше 👆"
        )
    else:
        await message.answer(
            "Пожалуйста, отправь текстовый ответ или воспользуйся кнопками клавиатуры 👆"
        )


# 5. Точка входа в приложение
async def main():
    logger.info("Инициализация бота AcademAudit...")
    
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Пропуск накопившихся апдейтов перед стартом
    await bot.delete_webhook(drop_pending_updates=True)

    # Регистрация команд бота в меню Telegram
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🚀 Главное меню и расчет"),
            BotCommand(command="audit", description="🔍 Экспресс-проверка курсовой"),
            BotCommand(command="help", description="💬 Связь с экспертом и условия"),
        ])
    except Exception as e:
        logger.warning(f"Не удалось обновить меню команд бота: {e}")

    logger.info("Бот успешно запущен и готов к приему заявок в режиме Long Polling.")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
