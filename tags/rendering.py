from tags import services


def unit_tags_context(user, unit, *, panel_open=False):
    """Context for the shared unit tag panel partial."""
    on_unit = services.tags_for_unit(user, unit)
    on_ids = {t.pk for t in on_unit}
    addable = [t for t in services.list_tags(user) if t.pk not in on_ids]
    return {
        "unit_tags": on_unit,
        "addable_tags": addable,
        "tags_panel_open": panel_open,
    }
