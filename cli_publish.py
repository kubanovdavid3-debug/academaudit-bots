#!/usr/bin/env python3
"""
CLI-менеджер публикаций сервиса «AcademAudit» (cli_publish.py).

Позволяет публиковать статьи и посты из Markdown-файлов с Frontmatter
в целевые платформы (Telegram, ВКонтакте, VC.ru) в 1 консольную команду.

Использование:
    python cli_publish.py --file content/draft/antiplagiat_2026.md --targets tg,vk,vc
"""

import os
import sys
import re
import yaml
import shutil
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional

# Настройка UTF-8 для консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from publisher import ArticlePayload, PublishResult, PublisherManager


def parse_markdown_with_frontmatter(file_path: Path) -> Tuple[Dict[str, Any], str]:
    """
    Извлекает Frontmatter (YAML) и текст статьи из .md файла.
    
    :param file_path: Путь к файлу статьи
    :return: Кортеж (метаданные dict, чистый текст статьи str)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Файл статьи не найден: {file_path}")

    content = file_path.read_text(encoding="utf-8")

    # Регулярное выражение для поиска YAML фронтматтера между --- и ---
    fm_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
    match = fm_pattern.match(content)

    if match:
        raw_yaml, body = match.groups()
        try:
            metadata = yaml.safe_load(raw_yaml) or {}
        except Exception as e:
            print(f"⚠️ Предупреждение: ошибка парсинга YAML фронтматтера: {e}")
            metadata = {}
        return metadata, body.strip()
    else:
        # Если фронтматтер отсутствует, ищем первый H1 как заголовок
        lines = content.strip().split("\n")
        title = "Статья AcademAudit"
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return {"title": title}, content.strip()


def resolve_cover_path(cover_val: Optional[str], doc_dir: Path) -> Optional[str]:
    """Находит абсолютный путь к обложке."""
    if not cover_val:
        return None

    # 1. Прямой абсолютный путь
    p = Path(cover_val)
    if p.is_absolute() and p.exists():
        return str(p)

    # 2. Относительно папки с документом
    doc_rel = (doc_dir / cover_val).resolve()
    if doc_rel.exists():
        return str(doc_rel)

    # 3. Относительно корня проекта d:/temka
    root_rel = (Path("d:/temka") / cover_val).resolve()
    if root_rel.exists():
        return str(root_rel)

    return None


def format_table(rows: List[List[str]], headers: List[str]) -> str:
    """Генерирует аккуратную таблицу для терминала с выравниванием колонок."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            # Учитываем визуальную длину строки без ANSI (если есть)
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # Разделители
    sep_top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
    sep_mid = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
    sep_bot = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"

    header_line = "│" + "│".join(f" {headers[i].ljust(col_widths[i])} " for i in range(len(headers))) + "│"

    table_lines = [sep_top, header_line, sep_mid]
    for row in rows:
        row_line = "│" + "│".join(f" {str(row[i]).ljust(col_widths[i])} " for i in range(len(row))) + "│"
        table_lines.append(row_line)
    table_lines.append(sep_bot)

    return "\n".join(table_lines)


def update_and_move_article(
    original_path: Path,
    metadata: Dict[str, Any],
    body: str,
    results: Dict[str, PublishResult],
) -> Path:
    """
    Дополняет фронтматтер полученными ссылками и перемещает файл
    из content/draft/ в content/published/.
    """
    published_dir = Path("d:/temka/content/published")
    published_dir.mkdir(parents=True, exist_ok=True)

    # Добавляем ссылки успешных публикаций
    successful_links = {}
    for plat, res in results.items():
        if res.success and res.post_url:
            successful_links[plat] = res.post_url

    metadata["published_at"] = datetime.now().isoformat()
    if successful_links:
        metadata["published_links"] = successful_links

    # Формируем обновленный документ
    updated_yaml = yaml.dump(metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)
    new_content = f"---\n{updated_yaml}---\n\n{body}\n"

    target_path = published_dir / original_path.name

    # Записываем обновленный файл в published
    target_path.write_text(new_content, encoding="utf-8")

    # Если исходный файл находился в папке draft, удаляем его
    if "draft" in original_path.parts:
        try:
            original_path.unlink()
        except Exception as e:
            print(f"⚠️ Не удалось удалить черновик: {e}")

    return target_path


async def main_async():
    parser = argparse.ArgumentParser(
        description="CLI-менеджер публикаций AcademAudit в Telegram, VK и VC.ru",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Пример: python cli_publish.py --file content/draft/antiplagiat_2026.md --targets tg,vk,vc",
    )
    parser.add_argument(
        "-f", "--file",
        required=True,
        help="Путь к Markdown-файлу статьи (например: content/draft/antiplagiat_2026.md)",
    )
    parser.add_argument(
        "-t", "--targets",
        default="",
        help="Список целевых платформ через запятую (например: tg,vk,vc). По умолчанию берется из frontmatter.",
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = (Path("d:/temka") / file_path).resolve()

    print("\n" + "═" * 70)
    print("🚀 ACADEMAUDIT CLI PUBLISHER: МУЛЬТИПЛАТФОРМЕННЫЙ АВТОПОСТИНГ")
    print("═" * 70)
    print(f"📂 Входящий файл: {file_path}")

    # 1. Парсинг Frontmatter и статьи
    try:
        metadata, body = parse_markdown_with_frontmatter(file_path)
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        sys.exit(1)

    title = metadata.get("title") or "Статья AcademAudit"
    raw_tags = metadata.get("tags") or []
    if isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        tags = list(raw_tags)

    excerpt = metadata.get("excerpt") or ""
    cta_link = metadata.get("cta_link") or "https://t.me/AcademAuditBot?start=cli_post"
    cover_raw = metadata.get("cover") or metadata.get("cover_image_path")
    cover_path = resolve_cover_path(cover_raw, file_path.parent)

    # 2. Определение целевых платформ
    if args.targets.strip():
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    elif metadata.get("platforms"):
        raw_pl = metadata.get("platforms")
        targets = [t.strip() for t in raw_pl.split(",")] if isinstance(raw_pl, str) else list(raw_pl)
    else:
        targets = ["tg", "vk", "vc"]

    print(f"📌 Заголовок: {title}")
    print(f"🏷 Теги: {', '.join(tags) if tags else '—'}")
    print(f"🎯 Целевые платформы: {', '.join(targets)}")
    if cover_path:
        print(f"🖼 Обложка: {cover_path}")
    print(f"📝 Объем текста: {len(body)} символов")
    print("─" * 70)

    article = ArticlePayload(
        title=title,
        text=body,
        excerpt=excerpt,
        tags=tags,
        cover_image_path=cover_path,
        cta_link=cta_link,
        source_platform="cli_publisher",
    )

    # 3. Асинхронная публикация через PublisherManager
    manager = PublisherManager()
    print("⏳ Выполняется параллельная публикация...")
    results = await manager.publish_all(article=article, targets=targets)

    # 4. Формирование сводной таблицы результатов
    headers = ["Платформа", "Статус", "Ссылка / Ошибка"]
    table_rows = []
    display_names = {
        "telegram": "Telegram",
        "vk": "VKontakte",
        "vc": "VC.ru",
    }

    has_any_success = False

    for plat_key in manager.normalize_targets(targets):
        res = results.get(plat_key)
        p_name = display_names.get(plat_key, plat_key.capitalize())
        if res:
            if res.success:
                has_any_success = True
                status_str = "✅ УСПЕХ"
                link_or_err = res.post_url or "Опубликовано"
                if res.error_message:
                    link_or_err += f" ({res.error_message})"
            else:
                status_str = "❌ ОШИБКА"
                link_or_err = res.error_message or "Неизвестная ошибка"
        else:
            status_str = "⚠️ ПРОПУСК"
            link_or_err = "Платформа не обработана"

        table_rows.append([p_name, status_str, link_or_err])

    print("\n" + format_table(table_rows, headers) + "\n")

    # 5. Перемещение файла в content/published/ при успехе
    if has_any_success:
        new_loc = update_and_move_article(file_path, metadata, body, results)
        print(f"📁 Статья успешно перемещена в архив:")
        print(f"   ➡️ {new_loc}")
        print("🎉 Процесс мультипостинга успешно завершен!")
    else:
        print("❌ Ни одна публикация не завершилась успехом. Файл оставлен в исходной директории.")
        sys.exit(2)


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n⛔ Прервано пользователем.")
        sys.exit(130)


if __name__ == "__main__":
    main()
