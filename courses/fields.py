from django.core.exceptions import ObjectDoesNotExist
from django.db import models


class OrderField(models.PositiveIntegerField):
    """Auto-assigns the next order within a sibling scope (`for_fields`) when blank.

    Not DB-unique: transient duplicates within a scope are tolerated (ties broken by
    pk at query time). Filtering on a null `for_fields` value (e.g. parent=None) works,
    so course-level siblings share one order space. Re-parent/compaction is a Phase-1b
    concern; 1a only needs stable per-scope ordering.
    """

    def __init__(self, for_fields=None, *args, **kwargs):
        self.for_fields = for_fields
        super().__init__(*args, **kwargs)

    def pre_save(self, model_instance, add):
        if getattr(model_instance, self.attname) is None:
            try:
                qs = self.model.objects.all()
                if self.for_fields:
                    query = {
                        field: getattr(model_instance, field)
                        for field in self.for_fields
                    }
                    qs = qs.filter(**query)
                last_item = qs.latest(self.attname)
                value = getattr(last_item, self.attname) + 1
            except ObjectDoesNotExist:
                value = 0
            setattr(model_instance, self.attname, value)
            return value
        return super().pre_save(model_instance, add)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.for_fields is not None:
            kwargs["for_fields"] = self.for_fields
        return name, path, args, kwargs
