"""Label-independent synthetic entity IDs; these do not represent real farms."""
import uuid


def neutral_zone(index: int) -> str:
    # Same entity schedule in every bucket: neither lexical tokens nor unique
    # bucket hashes can act as a label shortcut. IDs remain outside evidence.
    return "zone-" + uuid.uuid5(uuid.NAMESPACE_URL, f"pomona-neutral-entity-v2/{index}").hex[:16]
