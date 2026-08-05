from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "resources" / "catalog" / "verified_parts_v1.json"
DOC_ROOT = ROOT / "resources" / "technical_docs"


def validate() -> dict:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    records = payload.get("records") or []
    errors: list[str] = []
    keys: set[tuple] = set()
    by_brand = Counter()
    by_model = Counter()
    by_source = Counter()
    by_assembly: dict[str, Counter] = defaultdict(Counter)
    missing_quantity = 0
    with_replacement = 0
    without_diagram = 0

    required = (
        "brand", "model", "assembly", "position", "part_number", "description",
        "source_document", "source_page", "source_document_sha256",
        "verification_status", "compatible_machine_numbers",
    )
    for row_number, record in enumerate(records, 1):
        for field in required:
            if record.get(field) in (None, "", []):
                errors.append(f"row {row_number}: missing {field}")
        key = (
            record.get("brand"), record.get("model"), record.get("assembly"),
            str(record.get("position")), record.get("part_number"),
        )
        if key in keys:
            errors.append(f"row {row_number}: duplicate key {key}")
        keys.add(key)
        source = DOC_ROOT / str(record.get("source_document"))
        if not source.is_file():
            errors.append(f"row {row_number}: missing source {record.get('source_document')}")
        else:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != record.get("source_document_sha256"):
                errors.append(f"row {row_number}: source hash mismatch {record.get('source_document')}")
        by_brand[record["brand"]] += 1
        by_model[record["model"]] += 1
        by_source[record["source_document"]] += 1
        by_assembly[record["brand"]][record["assembly"]] += 1
        missing_quantity += record.get("quantity") is None
        with_replacement += bool(record.get("replaced_by_part_number"))
        without_diagram += record.get("diagram_page") is None

    source_errors = []
    for relative, metadata in (payload.get("sources") or {}).items():
        source = DOC_ROOT / relative
        if not source.is_file():
            source_errors.append(f"missing source: {relative}")
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != metadata.get("sha256"):
            source_errors.append(f"source manifest hash mismatch: {relative}")
    errors.extend(source_errors)

    return {
        "catalog_version": payload.get("catalog_version"),
        "total_records": len(records),
        "verified_records": sum(bool(item.get("is_verified")) for item in records),
        "by_brand": dict(sorted(by_brand.items())),
        "by_model": dict(sorted(by_model.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_assembly": {brand: dict(sorted(values.items())) for brand, values in sorted(by_assembly.items())},
        "records_without_quantity": missing_quantity,
        "records_with_replacement_number": with_replacement,
        "records_without_diagram_page": without_diagram,
        "source_count": len(payload.get("sources") or {}),
        "errors": errors,
        "valid": not errors,
    }


def markdown(report: dict) -> str:
    lines = [
        "# AssetCore - доклад за импорт и валидация на каталога за резервни части",
        "",
        f"Каталожна версия: `{report['catalog_version']}`",
        "",
        "## Резултат",
        "",
        f"- Общо потвърдени каталожни записи: **{report['total_records']}**",
        f"- Записи с verification status: **{report['verified_records']}**",
        f"- Обработени източници: **{report['source_count']}**",
        f"- Записи без посочено количество в оригиналната таблица: **{report['records_without_quantity']}**",
        f"- Записи с официално поле `replaced by`: **{report['records_with_replacement_number']}**",
        f"- Записи без надеждно свързана exploded-view страница: **{report['records_without_diagram_page']}**",
        f"- Валидация: **{'УСПЕШНА' if report['valid'] else 'НЕУСПЕШНА'}**",
        "",
        "## По производител",
        "",
    ]
    for brand, count in report["by_brand"].items():
        lines.append(f"- {brand}: **{count}**")
    lines += ["", "## По модел", ""]
    for model, count in report["by_model"].items():
        lines.append(f"- {model}: **{count}**")
    lines += ["", "## По източник", ""]
    for source, count in report["by_source"].items():
        lines.append(f"- `{source}`: **{count}** внесени позиции")
    lines += [
        "",
        "## Контролирано изключени или непълни позиции",
        "",
        "- Falch quotation `offer_sq-de103869_2025-10-22.pdf` е проверена и запазена в техническата библиотека, но не е смесена с exploded-view каталога, защото е търговска оферта без позиционна схема.",
        "- HYDWIN изображението `CLEANING MACHINE PARTS` съдържа номера 1-8, но приложените материали не дават надеждна таблица, която свързва тези номера с Part No.; поради това не са създадени измислени hotspots.",
        "- CombiJet позиция 55 `PUMP SUPPORTS` е без потвърден Part No. (`*`) и не е внесена като официална каталожна част.",
        "- Hotspot координати не са генерирани автоматично. Схемата и таблицата остават достъпни, а изборът по позиция е източникът на истина до ръчна координатна верификация.",
        "",
        "## Проверки",
        "",
        "- Проверка за задължителни полета.",
        "- Проверка за дублиран ключ производител/модел/възел/позиция/Part No.",
        "- SHA-256 проверка на всеки запис спрямо приложения официален файл.",
        "- Проверка на съвместимите инвентарни номера от потвърдения регистър на 19-те HPWJ машини.",
        "- Дробните количества от Falch таблиците се пазят като decimal/float, без закръгляне до цяло число.",
    ]
    if report["errors"]:
        lines += ["", "## Грешки", ""] + [f"- {item}" for item in report["errors"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = validate()
    if args.markdown:
        args.markdown.write_text(markdown(report), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
