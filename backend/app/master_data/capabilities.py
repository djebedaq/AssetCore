"""Implemented native asset capabilities, shared by validation and admin discovery."""

CAPABILITIES = (
    {
        "code": "HAS_PRESSURE",
        "name_bg": "Работно налягане", "name_en": "Working pressure", "name_ru": "Рабочее давление",
        "description_bg": "Показва и проверява собственото налягане на актива.",
        "description_en": "Shows and validates the asset's native pressure.",
        "description_ru": "Показывает и проверяет давление самого актива.",
    },
    {
        "code": "HAS_PARTS_CATALOG",
        "name_bg": "Каталог на части", "name_en": "Parts catalog", "name_ru": "Каталог деталей",
        "description_bg": "Разрешава структурирания каталог за тази категория.",
        "description_en": "Enables the structured catalog for this category.",
        "description_ru": "Разрешает структурированный каталог для этой категории.",
    },
    {
        "code": "HAS_REPAIR_WORKFLOW",
        "name_bg": "Ремонти", "name_en": "Repair workflow", "name_ru": "Ремонт",
        "description_bg": "Разрешава започване на нов ремонт.",
        "description_en": "Allows new repairs to be started.",
        "description_ru": "Разрешает начинать новые ремонты.",
    },
    {
        "code": "HAS_TRANSFER_WORKFLOW",
        "name_bg": "Предаване", "name_en": "Transfer workflow", "name_ru": "Передача",
        "description_bg": "Разрешава ново предаване на актив.",
        "description_en": "Allows new asset transfers.",
        "description_ru": "Разрешает новые передачи актива.",
    },
)

CAPABILITY_CODES = frozenset(item["code"] for item in CAPABILITIES)
