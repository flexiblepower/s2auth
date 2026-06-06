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
    AuthenticationContext,
    ClientNodeId,
    ClientState,
    PairingAttemptContext,
    PairingAttemptId,
    PairingState,
    authentication_context,
    client_node_id as client_node_id_provider,
    pairing_attempt_context,
    pairing_attempt_context_by_client_node_id,
    pairing_attempt_id,
    pairing_attempt_id_var,
    pairing_token,
    pairing_token_var,
    S2InMemoryContextStorage,
    authentication_context_by_pairing_attempt_context,
    s2_client_node_id_var,
    store_authentication_context,
    store_pairing_attempt_context,
)


@pytest.mark.skip_wire
async def test_client_node_id_provider_with_contextvar_set() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000042")

    @inject
    def get_client_node_id(
        node_id: ClientNodeId = Depends[client_node_id_provider],
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
        node_id: ClientNodeId = Depends[client_node_id_provider],
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
async def test_authentication_context_provider_returns_stored_context() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    storage = InMemoryContextStorage()
    await storage.store_context(
        AuthenticationContext,
        test_uuid,
        AuthenticationContext(client_node_id=test_uuid, state=ClientState.CONNECTED),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    def test_client_node_id() -> UUID:
        return test_uuid

    @inject
    async def get_context(
        ctx: AuthenticationContext = Depends[authentication_context],
    ) -> AuthenticationContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id_provider: test_client_node_id,
        }
    ):
        result = await get_context()

    assert result.client_node_id == test_uuid
    assert result.state == ClientState.CONNECTED


@pytest.mark.skip_wire
async def test_authentication_context_provider_raises_keyerror_for_unknown_id() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    def test_client_node_id() -> UUID:
        return test_uuid

    @inject
    async def get_context(
        ctx: AuthenticationContext = Depends[authentication_context],
    ) -> AuthenticationContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id_provider: test_client_node_id,
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
async def test_pairing_attempt_context_provider_raises_keyerror_for_unknown_id() -> (
    None
):
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
            with pytest.raises(
                KeyError, match=f"No context known for {test_pairing_id}"
            ):
                await get_pairing_context()
    finally:
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_store_authentication_context_provider_stores_by_client_node_id() -> None:
    test_uuid = UUID("00000000-0000-0000-0000-000000000001")
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def store_context(
        store_ctx: Callable[[AuthenticationContext], Awaitable[None]] = Depends[
            store_authentication_context
        ],
    ) -> None:
        await store_ctx(
            AuthenticationContext(client_node_id=test_uuid, state=ClientState.CONNECTED)
        )

    setup()

    with provider_overrides({context_storage_singleton: test_context_storage}):
        await store_context()

    stored = await storage.get_context_snapshot(AuthenticationContext, test_uuid)
    assert stored.state == ClientState.CONNECTED


@pytest.mark.skip_wire
async def test_store_authentication_context_provider_requires_client_node_id() -> None:
    storage = InMemoryContextStorage()

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def store_context(
        store_ctx: Callable[[AuthenticationContext], Awaitable[None]] = Depends[
            store_authentication_context
        ],
    ) -> None:
        await store_ctx(AuthenticationContext(state=ClientState.CONNECTED))

    setup()

    with provider_overrides({context_storage_singleton: test_context_storage}):
        with pytest.raises(
            ValueError, match="AuthenticationContext must have client_node_id set"
        ):
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


async def test_s2_in_memory_context_storage_lists_contexts_by_type() -> None:
    storage = S2InMemoryContextStorage()
    first_pairing_id = uuid4()
    second_pairing_id = uuid4()

    await storage.store_context(
        PairingAttemptContext,
        first_pairing_id,
        PairingAttemptContext(
            pairing_attempt_id=first_pairing_id,
            pairing_node_id=NodeIdAlias(root="first"),
            pairing_token=create_pairing_code(),
        ),
    )
    await storage.store_context(
        PairingAttemptContext,
        second_pairing_id,
        PairingAttemptContext(
            pairing_attempt_id=second_pairing_id,
            pairing_node_id=NodeIdAlias(root="second"),
            pairing_token=create_pairing_code(),
        ),
    )

    contexts = await storage.list_contexts(PairingAttemptContext)

    assert {ctx.pairing_attempt_id for ctx in contexts} == {
        first_pairing_id,
        second_pairing_id,
    }


@pytest.mark.skip_wire
async def test_pairing_token_provider_with_contextvar_set() -> None:
    token_value = "pairingToken123"

    @inject
    def get_pairing_token(
        token: str = Depends[pairing_token],
    ) -> str:
        return token

    setup()

    token = pairing_token_var.set(token_value)
    try:
        assert get_pairing_token() == token_value
    finally:
        pairing_token_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_token_provider_without_contextvar() -> None:
    @inject
    def get_pairing_token(
        token: str = Depends[pairing_token],
    ) -> str:
        return token

    setup()

    token = pairing_token_var.set(None)
    try:
        with pytest.raises(ValueError, match="pairing_token not set in context"):
            get_pairing_token()
    finally:
        pairing_token_var.reset(token)


@pytest.mark.skip_wire
async def test_pairing_attempt_context_by_client_node_id_returns_matching_context() -> (
    None
):
    storage = S2InMemoryContextStorage()
    pairing_id = uuid4()
    matching_client_node_id = uuid4()
    await storage.store_context(
        PairingAttemptContext,
        pairing_id,
        PairingAttemptContext(
            pairing_attempt_id=pairing_id,
            client_node_id=matching_client_node_id,
            pairing_node_id=NodeIdAlias(root="matching"),
            pairing_token="matchingToken123",
            state=PairingState.INITIATED,
        ),
    )
    other_pairing_id = uuid4()
    await storage.store_context(
        PairingAttemptContext,
        other_pairing_id,
        PairingAttemptContext(
            pairing_attempt_id=other_pairing_id,
            client_node_id=uuid4(),
            pairing_node_id=NodeIdAlias(root="other"),
            pairing_token="otherToken123",
            state=PairingState.FAILED,
        ),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    def test_client_node_id() -> ClientNodeId:
        return matching_client_node_id

    @inject
    async def get_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context_by_client_node_id],
    ) -> PairingAttemptContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id_provider: test_client_node_id,
        }
    ):
        ctx = await get_context()

    assert ctx.pairing_attempt_id == pairing_id
    assert ctx.client_node_id == matching_client_node_id


@pytest.mark.skip_wire
async def test_pairing_attempt_context_by_client_node_id_raises_for_missing_context() -> (
    None
):
    storage = S2InMemoryContextStorage()
    client_node_id = uuid4()

    def test_context_storage() -> ContextStorage:
        return storage

    def test_client_node_id() -> ClientNodeId:
        return client_node_id

    @inject
    async def get_context(
        ctx: PairingAttemptContext = Depends[pairing_attempt_context_by_client_node_id],
    ) -> PairingAttemptContext:
        return ctx

    setup()

    with provider_overrides(
        {
            context_storage_singleton: test_context_storage,
            client_node_id_provider: test_client_node_id,
        }
    ):
        with pytest.raises(
            KeyError,
            match=f"No context known for client_node_id {client_node_id}",
        ):
            await get_context()


@pytest.mark.skip_wire
async def test_authentication_context_by_pairing_attempt_context_returns_context() -> None:
    storage = InMemoryContextStorage()
    pairing_id = uuid4()
    client_node_id = uuid4()
    await storage.store_context(
        PairingAttemptContext,
        pairing_id,
        PairingAttemptContext(
        pairing_attempt_id=pairing_id,
        client_node_id=client_node_id,
        pairing_node_id=NodeIdAlias(root="pairing"),
        pairing_token="pairingToken123",
        state=PairingState.INITIATED,
        ),
    )
    await storage.store_context(
        AuthenticationContext,
        client_node_id,
        AuthenticationContext(
        client_node_id=client_node_id,
        state=ClientState.PAIRING,
        ),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def get_context(
        ctx: AuthenticationContext = Depends[
            authentication_context_by_pairing_attempt_context
        ],
    ) -> AuthenticationContext:
        return ctx

    setup()

    token = pairing_attempt_id_var.set(
        S2PairingAttemptId(root=b64encode(str(pairing_id).encode("utf-8")))
    )
    try:
        with provider_overrides({context_storage_singleton: test_context_storage}):
            ctx = await get_context()
    finally:
        pairing_attempt_id_var.reset(token)

    assert ctx.client_node_id == client_node_id
    assert ctx.state == ClientState.PAIRING


@pytest.mark.skip_wire
async def test_authentication_context_by_pairing_attempt_context_requires_client_node_id() -> (
    None
):
    storage = InMemoryContextStorage()
    pairing_id = uuid4()
    await storage.store_context(
        PairingAttemptContext,
        pairing_id,
        PairingAttemptContext(
            pairing_attempt_id=pairing_id,
            pairing_node_id=NodeIdAlias(root="pairing"),
            pairing_token="pairingToken123",
            state=PairingState.INITIATED,
        ),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def get_context(
        ctx: AuthenticationContext = Depends[
            authentication_context_by_pairing_attempt_context
        ],
    ) -> AuthenticationContext:
        return ctx

    setup()

    token = pairing_attempt_id_var.set(
        S2PairingAttemptId(root=b64encode(str(pairing_id).encode("utf-8")))
    )
    try:
        with provider_overrides({context_storage_singleton: test_context_storage}):
            with pytest.raises(
                ValueError, match="PairingAttemptContext must have client_node_id set"
            ):
                await get_context()
    finally:
        pairing_attempt_id_var.reset(token)


@pytest.mark.skip_wire
async def test_authentication_context_by_pairing_attempt_context_raises_for_missing_auth_context() -> (
    None
):
    storage = InMemoryContextStorage()
    pairing_id = uuid4()
    client_node_id = uuid4()
    await storage.store_context(
        PairingAttemptContext,
        pairing_id,
        PairingAttemptContext(
            pairing_attempt_id=pairing_id,
            client_node_id=client_node_id,
            pairing_node_id=NodeIdAlias(root="pairing"),
            pairing_token="pairingToken123",
            state=PairingState.INITIATED,
        ),
    )

    def test_context_storage() -> ContextStorage:
        return storage

    @inject
    async def get_context(
        ctx: AuthenticationContext = Depends[
            authentication_context_by_pairing_attempt_context
        ],
    ) -> AuthenticationContext:
        return ctx

    setup()

    token = pairing_attempt_id_var.set(
        S2PairingAttemptId(root=b64encode(str(pairing_id).encode("utf-8")))
    )
    try:
        with provider_overrides({context_storage_singleton: test_context_storage}):
            with pytest.raises(KeyError, match=f"No context known for {client_node_id}"):
                await get_context()
    finally:
        pairing_attempt_id_var.reset(token)
