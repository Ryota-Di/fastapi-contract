"""Validate baseline transport before app loading; never migrate historical facts."""

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from fastapi_contract.codec.json import snapshot_schema_version
from fastapi_contract.codec.schema_v1 import CanonicalJsonSnapshotCodec, SnapshotCodecError
from fastapi_contract.codec.schema_v2 import SnapshotV2Codec, SnapshotV2Document
from fastapi_contract.compat.v1.model import ContractSnapshot


@dataclass(frozen=True)
class LegacyBaseline:
    document: ContractSnapshot
    kind: Literal["legacy"] = field(default="legacy", init=False)


@dataclass(frozen=True)
class CurrentBaseline:
    document: SnapshotV2Document
    kind: Literal["current"] = field(default="current", init=False)


Baseline: TypeAlias = LegacyBaseline | CurrentBaseline


def load_baseline(text: str) -> Baseline:
    """Decode only the selected schema, propagating its errors without fallback.

    This boundary takes text only: callers can fully validate it before importing
    an application. Tool versions do not select lanes. No extraction or I/O occurs.
    """
    version = snapshot_schema_version(text)
    if version == 1:
        return LegacyBaseline(CanonicalJsonSnapshotCodec().decode(text))
    if version == 2:
        return CurrentBaseline(SnapshotV2Codec().decode(text))
    # Fail closed even if the envelope inspector learns about another version.
    raise SnapshotCodecError("Unsupported snapshot schema version")
