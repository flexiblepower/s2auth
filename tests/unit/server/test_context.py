from base64 import b64encode
from typing import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from wepositive_di import Depends, inject, provider_overrides, setup
from wepositive_di.context import (
    ContextStorage,
    InMemoryContextStorage,
    context_storage_singleton,
)

from s2auth.common.hmac import create_pairing_code
from s2auth.common.model.s2_connect_common import NodeId
from s2auth.common.model.s2_connect_pairing import (
    NodeIdAlias,
    PairingAttemptId as S2PairingAttemptId,
)
from s2auth.server.context import (
    ClientContext,
    ClientNodeId,
    ClientState,
    PairingAttemptContext,
    PairingAttemptId,
    PairingState,
    client_context,
    client_node_id,
    pairing_attempt_context,
    pairing_attempt_id,
    pairing_attempt_id_var,
    s2_client_node_id_var,
    store_client_context,
    store_pairing_attempt_context,
)


@pytest.mark.skip_wire
async def test_client_node_id_provider_with_contextvar_set() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000042")

    @inject
    def get_client_node_id(
        node_id: ClientNodeId = Depends[client_node_id],
    ) -> ClientNodeId:
        return node_id

    setup()

    token = s2_client_node_id_var.set(NodeId(root=test_uuid))
    try:
        assert get_client_node_id() == test_uuid
    finally:
        s2_client_node_id_var.reset(token)


@pytest.mark.skip_wire
async def test_client_node_id_provider_without_contextvar() -> None:
    @inject
    def get_client_node_id(
        node_id: ClientNodeId = Depends[client_node_id],
    ) -> ClientNodeId:
        return node_id

    setup()

    token = s2_client_node_id_var.set(None)
    try:
        with pytest.raises(ValueError, match="s2_client_node_id not set in context"):
            get_client_node_id()
    finally:
        s2_client_node_id_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_attempt_id_provider_with_contextvar_set() -> None:
    test_pairing_id = uuid4()

    @inject
    def get_pairing_attempt_id(
        p_id: PairingAttemptId = Depends[pairing_attempt_id],
    ) -> PairingAttemptId:
        return p_id

    setup()

    token = pairing_attempt_id_var.set(
        S2PairingAttemptId(root=b64encode(str(test_pairing_id).encode("utf-8")))
    )
    try:
        assert get_pairing_attempt_id() == test_pairing_id
    finally:
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_attempt_id_provider_without_contextvar() -> None:
    @inject
    def get_pairing_attempt_id(
        p_id: PairingAttemptId = Depends[pairing_attempt_id],
    ) -> PairingAttemptId:
        return p_id

    setup()

    token = pairing_attempt_id_var.set(None)
    try:
        with pytest.raises(ValueError, match="pairing_attempt_id not set in context"):
            get_pairing_attempt_id()
    finally:
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_client_context_provider_returns_stored_context() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    storage = InMemoryContextStorage()
    await storage.store_context(
        ClientContext,
        test_uuid,
        ClientContext(client_node_id=test_uuid, state=ClientState.CONNECTED),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    def test_client_node_id() -> UUID:
        return test_uuid

    @inject
    async def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id,
        }
    ):
        result = await get_context()

    assert result.client_node_id == test_uuid
    assert result.state == ClientState.CONNECTED


@pytest.mark.skip_wire
async def test_client_context_provider_raises_keyerror_for_unknown_id() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    def test_client_node_id() -> UUID:
        return test_uuid

    @inject
    async def get_context(ctx: ClientContext = Depends[client_context]) -> ClientContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id: test_client_node_id,
        }
    ):
        with pytest.raises(KeyError, match=f"No context known for {test_uuid}"):
            await get_context()


@pytest.mark.skip_wire
async def test_pairing_attempt_context_provider_returns_stored_context() -> None:
    test_pairing_id = uuid4()
    test_uuid = UUID("00000000-0000-0000-0000-000000000099")
    storage = InMemoryContextStorage()
    await storage.store_context(
        PairingAttemptContext,
        test_pairing_id,
        PairingAttemptContext(
            state=PairingState.INITIATED,
            client_node_id=test_uuid,
            pairing_attempt_id=test_pairing_id,
            pairing_node_id=NodeIdAlias(root="testnodeid123"),
            pairing_token=create_pairing_code(),
        ),
    )

    def get_test_storage() -> ContextStorage:
        return storage

    @inject
    async def get_pairing_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context],
    ) -> PairingAttemptContext:
        return ctx

    setup()

    token = pairing_attempt_id_var.set(
        S2PairingAttemptId(root=b64encode(str(test_pairing_id).encode("utf-8")))
    )
    try:
        with provider_overrides({context_storage_singleton: get_test_storage}):
            result = await get_pairing_context()
    finally:
        pairing_attempt_id_var.reset(token)

    assert result.state == PairingState.INITIATED
    assert result.client_node_id == test_uuid


@pytest.mark.skip_wire
async def test_pairing_attempt_context_provider_raises_keyerror_for_unknown_id() -> None:
    test_pairing_id = uuid4()
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def get_pairing_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context],
    ) -> PairingAttemptContext:
        return ctx

    setup()

    token = pairing_attempt_id_var.set(
        S2PairingAttemptId(root=b64encode(str(test_pairing_id).encode("utf-8")))
    )
    try:
        with provider_overrides({context_storage_singleton: test_context_storage}):
            with pytest.raises(KeyError, match=f"No context known for {test_pairing_id}"):
                await get_pairing_context()
    finally:
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_store_client_context_provider_stores_by_client_node_id() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def store_context(
        store_ctx: Callable[[ClientContext], Awaitable[None]] = Depends[
            store_client_context
        ],
    ) -> None:
        await store_ctx(
            ClientContext(client_node_id=test_uuid, state=ClientState.CONNECTED)
        )

    setup()

    with provider_overrides({context_storage_singleton: test_context_storage}):
        await store_context()

    stored = await storage.get_context_snapshot(ClientContext, test_uuid)
    assert stored.state == ClientState.CONNECTED


@pytest.mark.skip_wire
async def test_store_client_context_provider_requires_client_node_id() -> None:
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def store_context(
        store_ctx: Callable[[ClientContext], Awaitable[None]] = Depends[
            store_client_context
        ],
    ) -> None:
        await store_ctx(ClientContext(state=ClientState.CONNECTED))

    setup()

    with provider_overrides({context_storage_singleton: test_context_storage}):
        with pytest.raises(ValueError, match="ClientContext must have client_node_id set"):
            await store_context()


@pytest.mark.skip_wire
async def test_store_pairing_attempt_context_provider_stores_by_pairing_id() -> None:
    test_pairing_id = uuid4()
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def store_context(
        store_ctx: Callable[[PairingAttemptContext], Awaitable[None]] = Depends[
            store_pairing_attempt_context
        ],
    ) -> None:
        await store_ctx(
            PairingAttemptContext(
                pairing_attempt_id=test_pairing_id,
                pairing_node_id=NodeIdAlias(root="testnodeid123"),
                pairing_token=create_pairing_code(),
                state=PairingState.INITIATED,
            )
        )

    setup()

    with provider_overrides({context_storage_singleton: test_context_storage}):
        await store_context()

    stored = await storage.get_context_snapshot(PairingAttemptContext, test_pairing_id)
    assert stored.state == PairingState.INITIATED
