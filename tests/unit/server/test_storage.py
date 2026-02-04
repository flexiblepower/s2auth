from pydantic import AnyUrl
from s2auth.server.storage import store_object
from s2auth.common.models import AccessToken, ConnectionDetails


async def test_store_object():
    await store_object(
        ConnectionDetails(
            initiateConnectionUrl=AnyUrl("http://test.com/1234"),
            accessToken=AccessToken(root="sometoken"),
        )
    )
