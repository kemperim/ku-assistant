#!/usr/bin/env python3
"""
cli.py — управление документами и индексом из командной строки.

Использование:
  python cli.py sync              # Скачать с Google Drive и переиндексировать новые
  python cli.py sync --force      # Полная переиндексация всех файлов
  python cli.py status            # Показать состояние индекса
  python cli.py add /path/to.pdf  # Добавить локальный файл
  python cli.py clear             # Очистить весь индекс
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.rag_engine import RAGEngine


async def cmd_sync(force: bool):
    engine = RAGEngine()
    print(f"{'Принудительная переиндексация' if force else 'Синхронизация'} документов...")
    result = await engine.sync_documents(force=force)
    print(f"\n  Скачано с Drive : {result['downloaded']}")
    print(f"  Проиндексировано: {result['indexed']}")
    print(f"  Пропущено       : {result['skipped']}")
    if result['errors']:
        print(f"  Ошибки:")
        for e in result['errors']:
            print(f"    - {e}")
    status = await engine.get_status()
    print(f"\n  Итого чанков в индексе: {status['chunks_count']}")


async def cmd_status():
    engine = RAGEngine()
    engine.vectorstore.load()
    status = await engine.get_status()
    print("\n  ── Состояние RAG-агента ──")
    print(f"  Статус         : {status['status']}")
    print(f"  Документов     : {status['docs_count']}")
    print(f"  Чанков         : {status['chunks_count']}")
    print(f"  LLM модель     : {status['llm_model']}")
    print(f"  Embed модель   : {status['embed_model']}")
    print(f"  Google Drive   : {'настроен ✓' if status['gdrive_configured'] else 'не настроен'}")
    if status['indexed_files']:
        print("\n  Файлы в индексе:")
        for f in status['indexed_files']:
            print(f"    - {f}")


async def cmd_add(file_path: str):
    path = Path(file_path)
    if not path.exists():
        print(f"Ошибка: файл не найден: {file_path}")
        sys.exit(1)
    import shutil
    dest = Path(settings.DOCS_PATH) / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    print(f"Файл скопирован: {dest}")

    engine = RAGEngine()
    engine.vectorstore.load()
    result = await engine.sync_documents(force=False)
    print(f"Проиндексировано: {result['indexed']} файл(ов)")


async def cmd_clear():
    engine = RAGEngine()
    engine.vectorstore.clear()
    print("Индекс очищен.")


async def cmd_ask(question: str):
    engine = RAGEngine()
    if not engine.vectorstore.load():
        print("Индекс пуст. Сначала выполните: python cli.py sync")
        return
    for c in engine.vectorstore.chunks:
        engine._docs_indexed[c.source] = engine._docs_indexed.get(c.source, 0) + 1
    engine._initialized = True
    print(f"\n  Вопрос: {question}\n")
    result = await engine.answer(question)
    print(f"  Ответ:\n{result['answer']}\n")
    if result['sources']:
        print("  Источники:")
        for s in result['sources']:
            print(f"    [{s['file']}, стр.{s['page']}] score={s['score']:.3f}")


def main():
    parser = argparse.ArgumentParser(description="RAG Abitur CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_sync = sub.add_parser("sync", help="Синхронизировать и индексировать документы")
    p_sync.add_argument("--force", action="store_true", help="Полная переиндексация")

    sub.add_parser("status", help="Показать состояние индекса")

    p_add = sub.add_parser("add", help="Добавить локальный файл")
    p_add.add_argument("file", help="Путь к PDF или DOCX")

    sub.add_parser("clear", help="Очистить индекс")

    p_ask = sub.add_parser("ask", help="Задать вопрос (тест)")
    p_ask.add_argument("question", help="Вопрос")

    args = parser.parse_args()

    if args.cmd == "sync":
        asyncio.run(cmd_sync(args.force))
    elif args.cmd == "status":
        asyncio.run(cmd_status())
    elif args.cmd == "add":
        asyncio.run(cmd_add(args.file))
    elif args.cmd == "clear":
        asyncio.run(cmd_clear())
    elif args.cmd == "ask":
        asyncio.run(cmd_ask(args.question))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
