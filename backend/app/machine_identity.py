"""Verified physical identities; original catalog manifests remain immutable."""

FALCH_500_CORRECTIONS = {
    "G39300296": ("9", "8"),
    "G39300297": ("10", "9"),
    "G39300298": ("11", "10"),
    "G39300299": ("12", "11"),
}
FALCH_500_SERIALS = frozenset((*FALCH_500_CORRECTIONS, "G39300415", "G39300416",
                               "G39300417", "G39300418"))


def verified_family(machine):
    if (machine.category == "HPWJ" and machine.brand == "Falch"
            and machine.model == "Wheel Jet 15-e" and machine.pressure_bar == 500
            and machine.serial_number in FALCH_500_SERIALS):
        return "FALCH_500"
    return None


def legacy_catalog_number(machine):
    """Map a physical machine to its original catalog provenance, never its history."""
    if verified_family(machine) and machine.serial_number in FALCH_500_CORRECTIONS:
        return FALCH_500_CORRECTIONS[machine.serial_number][0]
    return str(machine.inventory_number)
