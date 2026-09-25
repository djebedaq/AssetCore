"""Platform workflow applicability comes from the current category."""

from ..models import Machine


def supports(machine: Machine, capability: str) -> bool:
    category = machine.category_definition
    return category is not None and capability in (category.capabilities or [])
