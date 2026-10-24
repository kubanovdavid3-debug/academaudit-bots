"""
Telegram-бот Редакции и Автопостинга «AcademAudit Publisher» (@AcademAuditPublishBot)
Предназначен исключительно для администратора.
Позволяет:
- Привязывать Telegram-канал прямо из диалога
- Создавать и форматировать статьи с обложками
- Использовать готовые вирусные шаблоны постов для студентов
- Просматривать предпросмотр (черновик) перед отправкой
- Публиковать посты в канал в 1 клик с кнопкой перехода в @AcademAuditBot
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv, set_key
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
    BotCommand,
    FSInputFile,
)

from publisher import ArticlePayload, TelegramChannelPublisher, VKPublisher, VCPublisher

# 1. Загрузка конфигурации
ENV_PATH = Path("d:/temka/.env")
load_dotenv(dotenv_path=ENV_PATH)

PUBLISHER_BOT_TOKEN = os.getenv("PUBLISHER_BOT_TOKEN", "").strip()
MANAGER_USERNAME = os.getenv("MANAGER_USERNAME", "AcademAudit_Support").strip()
CONTACT_URL = f"https://t.me/{MANAGER_USERNAME}"

ADMIN_CHAT_ID_RAW = os.getenv("ADMIN_CHAT_ID", "").strip()
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW)
except ValueError:
    ADMIN_CHAT_ID = 8869658382

if not PUBLISHER_BOT_TOKEN:
    print("Ошибка: PUBLISHER_BOT_TOKEN не задан в .env файле!")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("AcademAuditPublishBot")


# 2. Машина состояний (FSM)
class PostCreationStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_text = State()
    waiting_for_image = State()
    waiting_for_tags = State()


class ChannelSettingStates(StatesGroup):
    waiting_for_channel_id = State()


# 3. Готовые шаблоны экспертных статей
TEMPLATES = {
    "antiplagiat": ArticlePayload(
        title="🎓 Как пройти проверку в «Антиплагиат.ВУЗ» в 2026 году",
        excerpt="Новые нейросетевые детекторы, модуль перефразирования и почему синонимайзеры больше не работают.",
        text=(
            "Каждый семестр студенты сталкиваются с одной и той же проблемой: преподавательский пакет "
            "<b>«Антиплагиат.ВУЗ»</b> срезает процент до 30-40% из-за закрытых отраслевых баз.\n\n"
            "<b>Что важно знать в 2026 году:</b>\n"
            "1. <b>Детекторы ИИ:</b> тексты от ChatGPT и машинные переводы маркируются подозрительными фрагментами.\n"
            "2. <b>Модуль перефразирования:</b> замена каждого третьего слова на синоним не спасает — проверяется структура предложения.\n"
            "3. <b>Кольцо вузов:</b> все курсовые за последние 10 лет хранятся в едином закрытом пуле.\n\n"
            "<b>Как набрать честные 80%+:</b>\n"
            "• Оформляйте цитирования строго по ГОСТ 7.32 (прямые цитаты не считаются плагиатом при наличии сносок).\n"
            "• Применяйте глубокий смысловой рерайт с профессиональной академической терминологией.\n"
            "• Делайте предварительный аудит до сдачи научному руководителю.\n\n"
            "💡 <i>В сервисе AcademAudit первичный аудит структуры и темы проводится с 0% предоплаты!</i>"
        ),
        tags=["антиплагиат", "курсовая2026", "нормоконтроль", "советы_студентам"],
        cover_image_path="d:/temka/avatar.jpg" if Path("d:/temka/avatar.jpg").exists() else None,
        cta_link=CONTACT_URL,
        source_platform="editorial",
    ),
    "gost": ArticlePayload(
        title="📐 Нормоконтроль 2026: Главные требования ГОСТ 7.32-2017",
        excerpt="Чек-лист оформления курсовой, из-за которого чаще всего отправляют на переделку.",
        text=(
            "Даже блестящее исследование могут не допустить к защите из-за нарушений нормоконтроля.\n\n"
            "<b>Чек-лист идеального оформления:</b>\n"
            "• <b>Поля:</b> левое — 30 мм, правое — 15 мм, верхнее и нижнее — по 20 мм.\n"
            "• <b>Шрифт:</b> Times New Roman, 14 pt, полуторный межстрочный интервал.\n"
            "• <b>Абзацный отступ:</b> строго 1.25 см (не пробелами!).\n"
            "• <b>Нумерация страниц:</b> арабскими цифрами по центру нижней части листа, титульник считается, но не нумеруется.\n"
            "• <b>Таблицы и рисунки:</b> сквозная нумерация (Таблица 1.1, Рис. 2.3) со ссылками по тексту.\n\n"
            "Хотите получить полный PDF-чеклист под методичку вашей кафедры? Пишите эксперту 👇"
        ),
        tags=["гост7_32", "нормоконтроль", "оформление", "курсовая"],
        cover_image_path="d:/temka/avatar.jpg" if Path("d:/temka/avatar.jpg").exists() else None,
        cta_link=CONTACT_URL,
        source_platform="editorial",
    ),
    "deadlines": ArticlePayload(
        title="⚡️ Горит дедлайн по курсовой? Экспресс-план за 48 часов",
        excerpt="Пошаговая инструкция, как закрыть хвост, когда до проверки остались считанные дни.",
        text=(
            "Если защита на носу, а у вас есть только титульный лист и утвержденная тема — без паники.\n\n"
            "<b>План спасения на 2 дня:</b>\n"
            "1. <b>День 1:</b> Четкий скелет. Введение (актуальность, цель, 4 задачи) + 2 главы по 2-3 параграфа.\n"
            "2. <b>День 2:</b> Практическая часть или анализ источников + заключение по каждой задаче из введения.\n"
            "3. <b>Финальный штрих:</b> Сверка списка литературы (не менее 20 источников не старше 5 лет).\n\n"
            "🔥 <i>По срочному тарифу эксперты AcademAudit подключаются за 24 часа и доводят работу до утверждения научруком.</i>"
        ),
        tags=["дедлайн", "срочно", "сессия", "курсовая24часа"],
        cover_image_path="d:/temka/avatar.jpg" if Path("d:/temka/avatar.jpg").exists() else None,
        cta_link=CONTACT_URL,
        source_platform="editorial",
    ),
}

# Временное хранилище черновиков в памяти (user_id -> ArticlePayload)
drafts: dict[int, ArticlePayload] = {}

# 4. Клавиатуры панели управления
def get_main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Написать новый пост", callback_data="menu_newpost"),
            ],
            [
                InlineKeyboardButton(text="📚 Готовые экспертные шаблоны", callback_data="menu_templates"),
            ],
            [
                InlineKeyboardButton(text="👁 Тестовый предпросмотр", callback_data="menu_preview_test"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Привязать Telegram-канал", callback_data="menu_setchannel"),
            ],
        ]
    )


def get_templates_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎓 Антиплагиат.ВУЗ 2026", callback_data="tpl_antiplagiat"),
            ],
            [
                InlineKeyboardButton(text="📐 Нормоконтроль ГОСТ 7.32", callback_data="tpl_gost"),
            ],
            [
                InlineKeyboardButton(text="⚡️ Экспресс-план (горящий дедлайн)", callback_data="tpl_deadlines"),
            ],
            [
                InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu_back"),
            ],
        ]
    )


def get_preview_action_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Опубликовать везде (TG + VK + VC)", callback_data="action_publish_all"),
            ],
            [
                InlineKeyboardButton(text="📱 В Telegram-канал", callback_data="action_publish_tg"),
                InlineKeyboardButton(text="🔵 В группу ВКонтакте", callback_data="action_publish_vk"),
            ],
            [
                InlineKeyboardButton(text="📰 На VC.ru (лонгрид)", callback_data="action_publish_vc"),
            ],
            [
                InlineKeyboardButton(text="🗑 Отменить черновик", callback_data="action_cancel"),
            ],
        ]
    )


def get_skip_image_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➡️ Пропустить фото (только текст)", callback_data="skip_image"),
            ]
        ]
    )


# 5. Роутер и хэндлеры бота
router = Router()


# Проверка доступа (только ADMIN_CHAT_ID)
@router.message(lambda msg: msg.from_user and msg.from_user.id != ADMIN_CHAT_ID)
async def access_denied(message: Message):
    await message.answer("⛔ Доступ ограничен. Этот бот предназначен исключительно для редакции канала AcademAudit.")


# Главное меню /start
@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    current_channel = os.getenv("TG_CHANNEL_ID") or "<i>Не привязан (нажмите «Привязать»)</i>"

    text = (
        "👋 <b>Пульт управления публикациями «AcademAudit Publisher»</b>\n\n"
        f"📡 <b>Текущий канал:</b> {current_channel}\n"
        f"👤 <b>Контакт для заявок клиентов:</b> @{MANAGER_USERNAME}\n\n"
        "Выберите действие:"
    )
    await message.answer(text=text, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == "menu_back")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await handle_start(callback.message, state)


# --- Настройка канала ---
@router.callback_query(F.data == "menu_setchannel")
async def start_set_channel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ChannelSettingStates.waiting_for_channel_id)

    text = (
        "⚙️ <b>Привязка Telegram-канала</b>\n\n"
        "1. Добавьте этого бота (<b>@AcademAuditPublishBot</b>) в ваш канал в качестве <b>Администратора</b> "
        "с правом публикации сообщений.\n"
        "2. Отправьте в ответном сообщении юзернейм канала (например: <code>@academaudit_channel</code>) "
        "или числовой ID канала (начинается с <code>-100...</code>):"
    )
    await callback.message.answer(text=text)


@router.message(ChannelSettingStates.waiting_for_channel_id, F.text)
async def process_channel_input(message: Message, state: FSMContext):
    channel_input = message.text.strip()
    if not (channel_input.startswith("@") or channel_input.startswith("-100")):
        await message.answer("⚠️ Юзернейм должен начинаться с <b>@</b> (например @my_channel) или ID с <b>-100</b>. Попробуйте еще раз:")
        return

    # Сохраняем в .env файл
    try:
        set_key(str(ENV_PATH), "TG_CHANNEL_ID", channel_input)
        os.environ["TG_CHANNEL_ID"] = channel_input
        await state.clear()

        await message.answer(
            f"✅ Канал <b>{channel_input}</b> успешно привязан и сохранен в <code>.env</code>!\n"
            "Теперь бот готов к публикации статей.",
            reply_markup=get_main_menu_kb(),
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось сохранить в .env: {e}")


# --- Выбор готового шаблона ---
@router.callback_query(F.data == "menu_templates")
async def show_templates(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        text="📚 <b>Выберите готовый экспертный пост для публикации:</b>",
        reply_markup=get_templates_kb(),
    )


@router.callback_query(F.data.startswith("tpl_"))
async def process_template_selection(callback: CallbackQuery):
    await callback.answer()
    tpl_key = callback.data.replace("tpl_", "")
    article = TEMPLATES.get(tpl_key)

    if not article:
        await callback.message.answer("Шаблон не найден.")
        return

    drafts[callback.from_user.id] = article
    await send_draft_preview(callback.message, article)


# --- Быстрый тестовый предпросмотр ---
@router.callback_query(F.data == "menu_preview_test")
async def preview_test_article(callback: CallbackQuery):
    await callback.answer()
    article = TEMPLATES["antiplagiat"]
    drafts[callback.from_user.id] = article
    await send_draft_preview(callback.message, article)


# --- Пошаговое создание нового поста ---
@router.callback_query(F.data == "menu_newpost")
async def start_new_post(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(PostCreationStates.waiting_for_title)
    await callback.message.answer("✍️ <b>Шаг 1 из 4.</b> Введите заголовок статьи (можно с эмодзи):")


@router.message(PostCreationStates.waiting_for_title, F.text)
async def process_post_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(PostCreationStates.waiting_for_text)
    await message.answer("📄 <b>Шаг 2 из 4.</b> Отправьте основной текст статьи (поддерживается HTML-разметка <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>):")


@router.message(PostCreationStates.waiting_for_text, F.text)
async def process_post_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text.strip())
    await state.set_state(PostCreationStates.waiting_for_image)
    await message.answer(
        "🖼 <b>Шаг 3 из 4.</b> Прикрепите фото обложки (как фотографию) или нажмите кнопку «Пропустить» 👇",
        reply_markup=get_skip_image_kb(),
    )


@router.callback_query(PostCreationStates.waiting_for_image, F.data == "skip_image")
async def process_skip_image(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(cover_path=None)
    await state.set_state(PostCreationStates.waiting_for_tags)
    await callback.message.answer("🏷 <b>Шаг 4 из 4.</b> Введите теги через запятую (например: <code>антиплагиат, гост, диплом</code>) или отправьте минус (-), если теги не нужны:")


@router.message(PostCreationStates.waiting_for_image, F.photo)
async def process_post_photo(message: Message, state: FSMContext, bot: Bot):
    # Скачиваем фото в папку uploads
    upload_dir = Path("d:/temka/uploads")
    upload_dir.mkdir(exist_ok=True)

    photo = message.photo[-1]
    file_path = upload_dir / f"cover_{photo.file_id}.jpg"
    await bot.download(photo, destination=file_path)

    await state.update_data(cover_path=str(file_path))
    await state.set_state(PostCreationStates.waiting_for_tags)
    await message.answer("🏷 <b>Шаг 4 из 4.</b> Введите теги через запятую (например: <code>курсовая, гост2026, защита</code>) или отправьте минус (-):")


@router.message(PostCreationStates.waiting_for_tags, F.text)
async def process_post_tags(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    raw_tags = message.text.strip()
    tags_list = []
    if raw_tags != "-":
        tags_list = [t.strip().lstrip("#") for t in raw_tags.split(",") if t.strip()]

    article = ArticlePayload(
        title=data.get("title", "Без заголовка"),
        text=data.get("text", ""),
        excerpt="",
        tags=tags_list,
        cover_image_path=data.get("cover_path"),
        cta_link=f"https://t.me/{CLIENT_BOT_USERNAME}?start=user_post",
        source_platform="admin_panel",
    )

    drafts[message.from_user.id] = article
    await send_draft_preview(message, article)


# Функция показа предпросмотра
async def send_draft_preview(message: Message, article: ArticlePayload):
    tags_str = " ".join([f"#{t}" for t in article.tags])
    preview_header = "👁 <b>ПРЕДПРОСМОТР ПОСТА ДЛЯ КАНАЛА:</b>\n" + "—" * 25 + "\n\n"

    # Кнопка перехода, как она будет выглядеть в канале
    channel_btn_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Проверить курсовую в боте",
                    url=f"https://t.me/{CLIENT_BOT_USERNAME}?start=audit",
                )
            ]
        ]
    )

    full_body = f"<b>{article.title}</b>\n\n{article.text}"
    if tags_str:
        full_body += f"\n\n{tags_str}"

    # Если есть обложка
    if article.cover_image_path and Path(article.cover_image_path).exists():
        photo_file = FSInputFile(article.cover_image_path)
        caption_text = full_body[:1000] + ("..." if len(full_body) > 1000 else "")
        await message.answer_photo(
            photo=photo_file,
            caption=preview_header + caption_text,
            reply_markup=channel_btn_kb,
        )
        if len(full_body) > 1000:
            await message.answer(
                "<i>(Остальная часть текста лонгрида будет автоматически разбита на серию сообщений при публикации в канал)</i>"
            )
    else:
        await message.answer(
            text=preview_header + full_body,
            reply_markup=channel_btn_kb,
            disable_web_page_preview=True,
        )

    # Панель управления публикацией для администратора
    current_channel = os.getenv("TG_CHANNEL_ID") or "Не задан"
    admin_action_text = (
        "—" * 25 + "\n"
        f"🎯 <b>Целевой канал для отправки:</b> {current_channel}\n\n"
        "Нажмите <b>«Опубликовать»</b> для мгновенной отправки в канал:"
    )
    await message.answer(text=admin_action_text, reply_markup=get_preview_action_kb())


# --- Публикация из черновика в каналы ---
@router.callback_query(F.data.in_({"action_publish", "action_publish_tg", "action_publish_vk", "action_publish_vc", "action_publish_all"}))
async def execute_publication(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    article = drafts.get(user_id)
    action = callback.data

    if not article:
        await callback.message.answer("❌ Черновик устарел или не найден. Создайте новый пост.")
        return

    publish_tg = action in ["action_publish", "action_publish_tg", "action_publish_all"]
    publish_vk = action in ["action_publish_vk", "action_publish_all"]
    publish_vc = action in ["action_publish_vc", "action_publish_all"]

    channel_id = os.getenv("TG_CHANNEL_ID")
    vk_owner_id = os.getenv("VK_OWNER_ID")
    vc_subsite_id = os.getenv("VC_SUBSITE_ID", "6158482")

    results_report = []

    # 1. Публикация в Telegram
    if publish_tg:
        if not channel_id:
            results_report.append("❌ <b>Telegram:</b> Канал не привязан! Привяжите в меню.")
        else:
            await callback.message.answer(f"⏳ <i>Публикуем в Telegram-канал {channel_id}...</i>")
            tg_pub = TelegramChannelPublisher(
                bot_token=PUBLISHER_BOT_TOKEN,
                channel_id=channel_id,
                manager_username=MANAGER_USERNAME,
            )
            tg_res = await tg_pub.publish(article)
            if tg_res.success:
                results_report.append(f"✅ <b>Telegram ({channel_id}):</b> <a href='{tg_res.post_url}'>Открыть пост</a>")
            else:
                results_report.append(f"❌ <b>Telegram:</b> {tg_res.error_message}")

    # 2. Публикация во ВКонтакте
    if publish_vk:
        if not vk_owner_id or not os.getenv("VK_ACCESS_TOKEN"):
            results_report.append("❌ <b>ВКонтакте:</b> VK_ACCESS_TOKEN или VK_OWNER_ID не настроены в .env.")
        else:
            await callback.message.answer(f"⏳ <i>Публикуем на стену сообщества VK {vk_owner_id}...</i>")
            vk_pub = VKPublisher()
            vk_res = await vk_pub.publish(article)
            if vk_res.success:
                results_report.append(f"✅ <b>ВКонтакте ({vk_owner_id}):</b> <a href='{vk_res.post_url}'>Открыть запись</a>")
            else:
                results_report.append(f"❌ <b>ВКонтакте:</b> {vk_res.error_message}")

    # 3. Публикация на VC.ru
    if publish_vc:
        await callback.message.answer("⏳ <i>Публикуем материал на VC.ru...</i>")
        vc_pub = VCPublisher()
        vc_res = await vc_pub.publish(article)
        if vc_res.success:
            if vc_res.error_message:
                results_report.append(f"📝 <b>VC.ru ({vc_subsite_id}):</b> <a href='{vc_res.post_url}'>Черновик статьи</a>\n   ℹ️ {vc_res.error_message}")
            else:
                results_report.append(f"✅ <b>VC.ru ({vc_subsite_id}):</b> <a href='{vc_res.post_url}'>Открыть материал</a>")
        else:
            results_report.append(f"❌ <b>VC.ru:</b> {vc_res.error_message}")

    summary_text = "📊 <b>ОТЧЕТ О ПУБЛИКАЦИИ:</b>\n" + "—" * 25 + "\n" + "\n".join(results_report)
    await callback.message.answer(summary_text, reply_markup=get_main_menu_kb(), disable_web_page_preview=False)
    drafts.pop(user_id, None)


@router.callback_query(F.data == "action_cancel")
async def cancel_publication(callback: CallbackQuery):
    await callback.answer()
    drafts.pop(callback.from_user.id, None)
    await callback.message.answer("🗑 Черновик отменен.", reply_markup=get_main_menu_kb())


# 6. Запуск бота
async def main():
    logger.info("Запуск бота редакции AcademAudit Publisher (@AcademAuditPublishBot)...")

    bot = Bot(
        token=PUBLISHER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="📱 Пульт управления публикациями"),
            BotCommand(command="newpost", description="📝 Написать новый пост"),
            BotCommand(command="templates", description="📚 Готовые экспертные шаблоны"),
        ])
    except Exception as e:
        logger.warning(f"Не удалось обновить команды: {e}")

    logger.info("Бот редакции готов к работе.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот редакции остановлен.")
