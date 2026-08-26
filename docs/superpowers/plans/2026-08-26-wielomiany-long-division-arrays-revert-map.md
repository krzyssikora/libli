# Wielomiany long-division: revert map

Reconstructed by `scripts/longdivision_revert_map.py` AFTER the conversion ran,
because the applying run never printed the pks it overwrote. Read-only: nothing
in the database was changed to produce this.

Each row names one converted element. `orphan_table_pk` is the `TableElement`
row the join pointed at BEFORE the conversion -- the `<original table pk>` the
plan's `## Rollback` snippet asks for:

```python
from django.contrib.contenttypes.models import ContentType
from courses.models import Element, TableElement
join = Element.objects.get(pk=<element_pk>)
join.content_type = ContentType.objects.get_for_model(TableElement)
join.object_id = <orphan_table_pk>
join.save(update_fields=["content_type", "object_id"])
```

The `MathElement` row named by `math_pk` is left behind by that repoint, exactly
as the `TableElement` rows are left behind by the conversion. Delete it only if
you are sure no other join points at it.

Rows flagged `ambiguous` share a candidate set with other rows: their stored
tables have identical cell text, so content alone cannot say which orphan came
from which join. The group listing below reports whether the group's orphans are
byte-identical; where it says YES, restoring any candidate into any of the
group's joins gives the same content and the choice does not matter. The flag is
there so nobody mistakes the assignment for a measurement.


Converted elements: 71.  Orphaned `TableElement` rows: 71.  Undecided groups: 2.

Undecided candidate groups (interchangeable orphans):

* elements 4318, 4402, 4434 <- orphans 73, 84, 86 -- stored `data` byte-identical across the group: YES
* elements 4388, 4403, 4435 <- orphans 83, 85, 87 -- stored `data` byte-identical across the group: YES

| element_pk | unit_pk | orphan_table_pk | math_pk | ambiguous |
| ---: | ---: | ---: | ---: | :--- |
| 4287 | 423 | 64 | 957 |  |
| 4291 | 423 | 65 | 958 |  |
| 4294 | 423 | 66 | 959 |  |
| 4298 | 423 | 67 | 960 |  |
| 4303 | 423 | 68 | 961 |  |
| 4306 | 423 | 69 | 962 |  |
| 4309 | 423 | 70 | 963 |  |
| 4312 | 423 | 71 | 964 |  |
| 4315 | 423 | 72 | 965 |  |
| 4318 | 423 | 73 | 966 | yes (73, 84, 86) |
| 4348 | 424 | 74 | 967 |  |
| 4354 | 424 | 75 | 968 |  |
| 4357 | 424 | 76 | 969 |  |
| 4364 | 424 | 77 | 970 |  |
| 4369 | 424 | 78 | 971 |  |
| 4372 | 424 | 79 | 972 |  |
| 4376 | 424 | 80 | 973 |  |
| 4380 | 424 | 81 | 974 |  |
| 4384 | 424 | 82 | 975 |  |
| 4388 | 424 | 83 | 976 | yes (83, 85, 87) |
| 4402 | 425 | 84 | 977 | yes (73, 84, 86) |
| 4403 | 425 | 85 | 978 | yes (83, 85, 87) |
| 4434 | 426 | 86 | 979 | yes (73, 84, 86) |
| 4435 | 426 | 87 | 980 | yes (83, 85, 87) |
| 4458 | 427 | 88 | 981 |  |
| 4461 | 427 | 89 | 982 |  |
| 4464 | 427 | 90 | 983 |  |
| 4467 | 427 | 91 | 984 |  |
| 4470 | 427 | 92 | 985 |  |
| 4473 | 427 | 93 | 986 |  |
| 4476 | 427 | 94 | 987 |  |
| 4479 | 427 | 95 | 988 |  |
| 4482 | 427 | 96 | 989 |  |
| 4485 | 427 | 97 | 990 |  |
| 4488 | 427 | 98 | 991 |  |
| 4491 | 427 | 99 | 992 |  |
| 4494 | 427 | 100 | 993 |  |
| 4497 | 427 | 101 | 994 |  |
| 4500 | 427 | 102 | 995 |  |
| 4503 | 427 | 103 | 996 |  |
| 4506 | 427 | 104 | 997 |  |
| 4509 | 427 | 105 | 998 |  |
| 4512 | 427 | 106 | 999 |  |
| 4515 | 427 | 107 | 1000 |  |
| 4520 | 427 | 108 | 1001 |  |
| 4523 | 427 | 109 | 1002 |  |
| 4526 | 427 | 110 | 1003 |  |
| 4529 | 427 | 111 | 1004 |  |
| 4532 | 427 | 112 | 1005 |  |
| 4535 | 427 | 113 | 1006 |  |
| 4538 | 427 | 114 | 1007 |  |
| 4541 | 427 | 115 | 1008 |  |
| 4544 | 427 | 116 | 1009 |  |
| 4547 | 427 | 117 | 1010 |  |
| 4550 | 427 | 118 | 1011 |  |
| 4553 | 427 | 119 | 1012 |  |
| 4556 | 427 | 120 | 1013 |  |
| 4559 | 427 | 121 | 1014 |  |
| 4562 | 427 | 122 | 1015 |  |
| 4565 | 427 | 123 | 1016 |  |
| 4568 | 427 | 124 | 1017 |  |
| 4571 | 427 | 125 | 1018 |  |
| 4574 | 427 | 126 | 1019 |  |
| 4577 | 427 | 127 | 1020 |  |
| 4925 | 436 | 137 | 1021 |  |
| 5003 | 438 | 138 | 1022 |  |
| 5184 | 441 | 140 | 1023 |  |
| 5262 | 442 | 142 | 1024 |  |
| 5286 | 442 | 144 | 1025 |  |
| 5311 | 442 | 146 | 1026 |  |
| 23679 | 1144 | 369 | 1027 |  |
