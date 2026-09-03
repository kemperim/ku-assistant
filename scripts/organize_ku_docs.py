"""Build a compact thematic knowledge base from the KU site crawl.

The raw crawler output repeats the site menu and footer on every page. This
script removes lines shared by many pages, skips transient news listings and
groups the useful pages into stable files that are convenient to extend by
hand.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS = ROOT / "docs"
DEFAULT_SOURCE = ROOT / "data" / "raw_ku_site"

SECTION_HEADINGS = [
    "Название университета",
    "Миссия университета",
    "Основной адрес университета",
    "Контакты университета",
    "Приемная комиссия",
    "Специалисты департамента по приему",
    "Информация для абитуриентов",
    "Возможности для студентов",
    "Общежития",
    "Памятка абитуриента",
    "Заселение в общежитие",
    "Актуальные числовые показатели университета",
    "Факультеты и институты",
    "Образовательные программы и стоимость обучения 2026-2027",
    "Профильные предметы ЕНТ",
    "Стипендии",
    "Важное ограничение",
]

FILES = {
    "01_ku_ob_universitete.txt": {
        "title": "Kozybayev University: общая информация, история и качество",
        "sections": [
            "Название университета",
            "Миссия университета",
            "Актуальные числовые показатели университета",
        ],
        "pages": [17, 18, 20, 21, 22, 24, 40, 41, 42, 43, 44, 45],
    },
    "02_ku_kontakty_i_upravlenie.txt": {
        "title": "Kozybayev University: контакты, руководство и подразделения",
        "sections": [
            "Основной адрес университета",
            "Контакты университета",
            "Приемная комиссия",
            "Специалисты департамента по приему",
        ],
        "pages": [26],
    },
    "03_ku_fakultety_i_kampus.txt": {
        "title": "Kozybayev University: факультеты, институты, корпуса и структура",
        "sections": ["Факультеты и институты"],
        "pages": [23, 30, 32],
    },
    "04_ku_postuplenie.txt": {
        "title": "Kozybayev University: поступление, этапы и документы",
        "sections": ["Информация для абитуриентов", "Памятка абитуриента"],
        "pages": [2, 5, 6, 49, 50, 51, 57, 59, 63],
    },
    "05_ku_bakalavriat_programmy_i_ceny.txt": {
        "title": "Kozybayev University: бакалавриат, программы, ЕНТ и стоимость",
        "sections": [
            "Образовательные программы и стоимость обучения 2026-2027",
            "Профильные предметы ЕНТ",
        ],
        "pages": [3, 58],
    },
    "06_ku_magistratura_i_doktorantura.txt": {
        "title": "Kozybayev University: магистратура и докторантура PhD",
        "sections": [],
        "pages": [61, 62, 64, 65, 66, 67, 68],
    },
    "07_ku_studentam_stipendii_i_obshchezhitiya.txt": {
        "title": "Kozybayev University: студентам, стипендии, гранты и общежития",
        "sections": [
            "Возможности для студентов",
            "Общежития",
            "Заселение в общежитие",
            "Стипендии",
        ],
        "pages": [8, 52, 53, 54, 55, 71],
    },
    "08_ku_praktika_karera_i_vozmozhnosti.txt": {
        "title": "Kozybayev University: практика, карьера и дополнительные возможности",
        "sections": [],
        "pages": [69, 70, 72, 73, 74],
    },
    "09_ku_nauka_i_innovacii.txt": {
        "title": "Kozybayev University: наука, исследования и инновации",
        "sections": [],
        "pages": [76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 91, 92, 93],
    },
    "10_ku_mezhdunarodnye_programmy.txt": {
        "title": "Kozybayev University: международные программы и академическая мобильность",
        "sections": [],
        "pages": [108, 109, 110, 111, 112, 114, 115, 116, 117, 118, 119, 120],
    },
}

PAGE_RE = re.compile(r"(?m)^===== СТРАНИЦА (\d+): (.+?) =====\r?\n")
SPACE_RE = re.compile(r"\s+")
JUNK_LINES = {
    "KZ RU EN",
    "Қаз Рус Eng",
    "Крупнее Войти",
    "larger Login",
    "Войти",
    "Кіру",
    "Главная",
    "Басты бет",
    "Новости",
    "Жаңалықтар",
    "Галерея цитат",
    "Новости факультетов",
}
NEWS_START = {"Новости факультетов", "Факультет жаңалықтары"}
NEWS_END = {"Читать все", "Барлығын оқу"}
QUOTES_START = {"Галерея цитат", "Дәйексөздер галереясы"}


def normalize(line: str) -> str:
    return SPACE_RE.sub(" ", line.replace("\u00a0", " ")).strip()


def split_reference(text: str) -> dict[str, str]:
    positions = []
    for heading in SECTION_HEADINGS:
        match = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
        if match:
            positions.append((match.start(), heading))
    positions.sort()

    sections = {}
    for index, (start, heading) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        sections[heading] = text[start:end].strip()
    return sections


def split_pages(text: str) -> dict[int, tuple[str, list[str]]]:
    matches = list(PAGE_RE.finditer(text))
    pages = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        lines = [normalize(line) for line in text[match.end():end].splitlines()]
        pages[int(match.group(1))] = (match.group(2), [line for line in lines if line])
    return pages


def document_frequency(pages: dict[int, tuple[str, list[str]]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for _, lines in pages.values():
        counts.update(set(lines))
    return counts


def clean_page(lines: list[str], frequency: Counter[str]) -> list[str]:
    result = []
    seen = set()
    skip_quotes = False
    skip_news = False
    for line in lines:
        if line in QUOTES_START:
            skip_quotes = True
            continue
        if line in NEWS_START:
            skip_quotes = False
            skip_news = True
            continue
        if skip_quotes or skip_news:
            if any(marker in line for marker in NEWS_END):
                skip_news = False
            continue
        if line in seen or line in JUNK_LINES:
            continue
        seen.add(line)
        if frequency[line] >= 4:
            continue
        if len(line) < 3 or re.fullmatch(r"[\d\s.,:;/\-]+", line):
            continue
        if line.startswith(("Copyright ", "Разработка сайта", "Сайтты әзірлеу")):
            continue
        result.append(line)
    return result


def build_file(
    title: str,
    section_names: list[str],
    page_numbers: list[int],
    sections: dict[str, str],
    pages: dict[int, tuple[str, list[str]]],
    frequency: Counter[str],
) -> str:
    blocks = [
        title,
        "",
        "Назначение: тематическая база знаний проекта KU Assistant.",
        "Официальные источники: https://ku.edu.kz/ и https://apply.ku.edu.kz/ru",
        "Сведения о датах, стоимости и правилах следует сверять перед каждым новым набором.",
    ]

    for name in section_names:
        content = sections.get(name)
        if content:
            blocks.extend(["", content])

    for number in page_numbers:
        page = pages.get(number)
        if not page:
            continue
        url, lines = page
        cleaned = clean_page(lines, frequency)
        if not cleaned:
            continue
        blocks.extend([
            "",
            f"Раздел официального сайта (страница {number})",
            f"Источник: {url}",
            "\n".join(cleaned),
        ])

    return "\n".join(blocks).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "curated_docs")
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_DOCS)
    args = parser.parse_args()

    source_dir = args.source.resolve()
    reference_path = source_dir / "00_ku_official_reference.txt"
    crawl_path = source_dir / "ku_site_crawl.txt"
    if not crawl_path.exists():
        raise SystemExit(f"Raw KU crawl was not found in {source_dir}")

    if reference_path.exists():
        reference_text = reference_path.read_text(encoding="utf-8")
    else:
        reference_files = sorted(args.reference_dir.resolve().glob("*.txt"))
        reference_text = "\n\n".join(
            path.read_text(encoding="utf-8") for path in reference_files
        )

    output_dir = args.output.resolve()
    if output_dir == source_dir:
        raise SystemExit("Source and output directories must be different")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in output_dir.glob("*.txt"):
        old_file.unlink()

    sections = split_reference(reference_text)
    pages = split_pages(crawl_path.read_text(encoding="utf-8"))
    frequency = document_frequency(pages)

    for filename, spec in FILES.items():
        content = build_file(
            spec["title"],
            spec["sections"],
            spec["pages"],
            sections,
            pages,
            frequency,
        )
        (output_dir / filename).write_text(content, encoding="utf-8")

    total_bytes = sum(path.stat().st_size for path in output_dir.glob("*.txt"))
    print(f"Created {len(FILES)} files in {output_dir}")
    print(f"Total size: {total_bytes / 1024:.1f} KiB")


if __name__ == "__main__":
    main()
