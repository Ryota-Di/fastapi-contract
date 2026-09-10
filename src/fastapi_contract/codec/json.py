"""Published v1 codec API. Explicit v2 transport lives in schema_v2.py."""

from fastapi_contract.codec.schema_v1 import CanonicalJsonSnapshotCodec, SnapshotCodecError

__all__ = ["CanonicalJsonSnapshotCodec", "SnapshotCodecError"]


def snapshot_schema_version(text: str) -> int:
    """Dispatch only at the transport boundary; each decoder validates its complete schema."""
    import json

    from fastapi_contract.codec.schema_v1 import _invalid_constant, _unique_object

    try:
        payload = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        value = payload["metadata"]["schema_version"]
        if type(value) is not int or value not in (1, 2):
            raise SnapshotCodecError("Unsupported snapshot schema version")
        return int(value)
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise SnapshotCodecError(str(exc)) from exc
