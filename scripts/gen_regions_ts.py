"""Переносит справочник субъектов в TypeScript.

Список федеральных субъектов меняется примерно раз в десятилетие и требует
поправки к Конституции — держать его рантайм-данными значило бы платить
состоянием загрузки за то, что не меняется. Поэтому он генерируется и
коммитится, а `tests/unit/test_regions.py` сверяет закоммиченное с исходником.

Приём в репозитории не новый: так же живёт `tests/fixtures/hpk_golden.json`
рядом с `scripts/build_golden_fixtures.py`.

    .venv/bin/python -m scripts.gen_regions_ts
"""

from __future__ import annotations

from pathlib import Path

from libs.shared.regions import RUSSIAN_REGIONS, UNKNOWN_REGION

TARGET = Path(__file__).resolve().parent.parent / "web" / "src" / "shared" / "lib" / "regions.ts"

HEADER = """\
// Сгенерировано scripts/gen_regions_ts.py — не править руками.
// Источник правды: libs/shared/regions.py
//
// Справочник субъектов держится статикой, а не запросом: он меняется раз в
// десятилетие, а пикер регионов обязан открываться мгновенно.
"""


def render() -> str:
    lines = [HEADER, "", "export const REGIONS: Readonly<Record<string, string>> = {"]
    lines.extend(f'  "{code}": "{name}",' for code, name in RUSSIAN_REGIONS.items())
    lines.append("};")
    lines.append("")
    lines.append("/** Чем подписывают закупку без региона. */")
    lines.append(f'export const UNKNOWN_REGION = "{UNKNOWN_REGION}";')
    lines.append("")
    lines.append("/** Название субъекта или сам код, если он незнаком. */")
    lines.append("export function regionName(code: string | null | undefined): string {")
    lines.append("  if (!code || code === UNKNOWN_REGION) return UNKNOWN_REGION;")
    lines.append("  const normalized = /^\\d+$/.test(code)")
    lines.append('    ? code.replace(/^0+/, "").padStart(2, "0")')
    lines.append("    : code;")
    lines.append("  return REGIONS[normalized] ?? `Регион ${code}`;")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    TARGET.write_text(render(), encoding="utf-8")
    print(f"{TARGET.relative_to(Path.cwd())}: {len(RUSSIAN_REGIONS)} субъектов")


if __name__ == "__main__":
    main()
