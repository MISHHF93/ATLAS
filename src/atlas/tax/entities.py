from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["individual", "corporation", "fund", "tfsa", "rrsp", "rrif", "fhsa"]
REGISTERED = {"tfsa", "rrsp", "rrif", "fhsa"}


@dataclass(frozen=True)
class Entity:
    """An account holder/ledger. `taxpayer` groups entities whose identical property
    shares ONE ACB pool (e.g. one individual's cash + margin accounts across venues).
    Registered plans keep their own ledger and have no ACB/gains reporting."""
    id: str
    kind: Kind
    taxpayer: str
    w8ben_on_file: bool = True
    name: str = ""

    @property
    def registered(self) -> bool:
        return self.kind in REGISTERED


@dataclass
class Affiliations:
    """Groups of mutually affiliated entities for superficial-loss purposes
    (you, spouse, controlled corp, your/spouse's RRSP/TFSA...)."""
    groups: list[set[str]] = field(default_factory=list)

    def affiliated(self, entity_id: str) -> set[str]:
        out = {entity_id}
        for g in self.groups:
            if entity_id in g:
                out |= g
        return out
