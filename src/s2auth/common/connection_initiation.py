from typing import TypeVar

from s2auth.common.model.s2_connect_common import CommunicationProtocol


_TItemType = TypeVar("_TItemType")


def select_compatible_item(
    remote_items: list[_TItemType], local_items: list[_TItemType]
) -> _TItemType | None:
    overlapping_items = set(remote_items).intersection(set(local_items))
    if not overlapping_items:
        return None
    return next(x for x in local_items if x in overlapping_items)


def select_version(remote_versions: list[str], local_versions: list[str]) -> str | None:
    return select_compatible_item(remote_versions, local_versions)


def select_protocol(
    remote_protocols: list[CommunicationProtocol],
    local_protocols: list[CommunicationProtocol],
) -> CommunicationProtocol | None:
    return select_compatible_item(remote_protocols, local_protocols)
