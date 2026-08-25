"""Script for running the reference implemntation of the S2 pairing client.
"""
import argparse
import asyncio
import logging
from uuid import UUID, uuid4

from s2auth.client.dao import Dao
from s2auth.client.pairing import PairingClient, build_pairing_settings
from s2auth.client.settings import ClientSettings

LOGGER = logging.getLogger(__name__)


def _format_default(value: object) -> str:
    return "None" if value is None else str(value)


async def _run_connect_mode(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    settings: ClientSettings,
    dao: Dao,
    pairing_s2_node_id: str | None,
    storage_key: str,
) -> None:
    allowed_connect_args = {"connect", "verbose", "pairing_s2_node_id", "pairing_S2_nodeId"}
    unexpected_args = [name for name, value in vars(args).items() if name not in allowed_connect_args and value != parser.get_default(name)]
    if unexpected_args:
        parser.error("--connect only allows --verbose plus --pairing_s2_node_id " "(or --pairing_S2_nodeId).")

    if not pairing_s2_node_id:
        parser.error("--connect expects --pairing_s2_node_id (or --pairing_S2_nodeId)")

    client = PairingClient.from_settings(settings, storage=dao)
    assert await client.connect(pairing_s2_node_id=pairing_s2_node_id)
    connection_details = dao.load_connection_details(storage_key)
    assert connection_details is not None, f"Connection details for pairing_s2_node_id '{storage_key}' not found after connect."

    LOGGER.info("--- Connecteion info: ---")
    LOGGER.info(f"selected_communication_protocol: {connection_details.get('selected_communication_protocol', None)}")
    LOGGER.info(f"selected_s2_message_version: {connection_details.get('selected_s2_message_version', None)}")
    LOGGER.info(f"server_node_description: {connection_details.get('server_node_description', None)}")
    LOGGER.info(f"server_endpoint_description: {connection_details.get('server_endpoint_description', None)}")
    LOGGER.info(f"access_token: {connection_details.get('access_token', None)}")

async def _run_unpair_mode(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    settings: ClientSettings,
    dao: Dao,
    pairing_s2_node_id: str | None,
) -> None:
    allowed_unpair_args = {"unpair", "verbose", "pairing_s2_node_id", "pairing_S2_nodeId"}
    unexpected_args = [name for name, value in vars(args).items() if name not in allowed_unpair_args and value != parser.get_default(name)]
    if unexpected_args:
        parser.error("--unpair only allows --verbose plus --pairing_s2_node_id " "(or --pairing_S2_nodeId).")

    if not pairing_s2_node_id:
        parser.error("--unpair expects --pairing_s2_node_id (or --pairing_S2_nodeId)")

    client = PairingClient.from_settings(settings, storage=dao)
    assert await client.unpair(pairing_s2_node_id=pairing_s2_node_id)

async def _run_pairing_mode(
    args: argparse.Namespace,
    settings: ClientSettings,
    dao: Dao,
    pairing_s2_node_id: str | None,
    clientS2NodeId: UUID,
    storage_key: str,
) -> None:
    LOGGER.info(f"Starting pairing client with clientS2NodeId: {clientS2NodeId}")

    runtime_settings, warnings = build_pairing_settings(
        settings,
        server_url=args.server_url,
        pairing_token=args.pairing_token,
        pairing_s2_node_id=pairing_s2_node_id,
        client_s2_node_id=str(clientS2NodeId),
        role=args.s2_role,
        deployment=args.deployment,
        domain_name=args.domain,
        verify_tls=not args.skip_cert_verify,
        ssl_certfile=args.certificate_file,
        supported_s2_message_versions=args.supported_s2_message_versions,
        communication_protocols=args.communication_protocols,
        supported_hmac_hashing_algorithms=args.supported_hmac_hashing_algorithms,
        brand=args.brand,
        client_device_type=args.type,
        client_model_name=args.model_name,
    )
    for warning in warnings:
        LOGGER.warning(warning)

    client = PairingClient.from_settings(runtime_settings, storage=dao)
    result = await client.pair()

    connection_details = result.connection_details
    if connection_details is None:
        connection_details = dao.load_connection_details(storage_key)
    assert connection_details is not None, f"Connection details for pairing_s2_node_id '{storage_key}' not found after pairing."
    LOGGER.info("--- Pairing info: ---")
    LOGGER.info(f"pairing_s2_node_id: {result.pairing_s2_node_id}")
    LOGGER.info(f"client_s2_node_id: {connection_details.get('client_s2_node_id', None)}")
    LOGGER.info(f"initiate_session_url: {connection_details.get('initiate_session_url', None)}")
    LOGGER.info(f"access_token: {connection_details.get('access_token', None)}")

async def _run_client():
    settings = ClientSettings()
    dao = Dao(settings.storage_db_url)

    parser = argparse.ArgumentParser(description="S2 pairing client example implementation.")

    parser.add_argument(
        "--server_url",
        default=settings.server_url,
        help=f"The pairing URL of the pairing server (default: {_format_default(settings.server_url)})",
    )

    parser.add_argument(
        "--domain",
        default=settings.domain_name,
        help=f"The domain name to use in a WAN deployment (default: {_format_default(settings.domain_name)})",
    )
    parser.add_argument(
        "--certificate_file",
        default=settings.ssl_certfile,
        help=f"Path to the PEM certificate file to use as fingerprint in a LAN deployment (default: {_format_default(settings.ssl_certfile)})",
    )

    parser.add_argument(
        "--pairing_S2_nodeId",
        default=settings.pairing_s2_node_id,
        help=(
            "Target identifier for the node to pair: UUID (sent as nodeId) or short alphanumeric alias "
            f"(sent as nodeIdAlias). Default: {_format_default(settings.pairing_s2_node_id)}"
        ),
    )
    parser.add_argument(
        "--client_S2_nodeId",
        default=settings.client_s2_node_id,
        help=f"The id of the client S2 node (default: {_format_default(settings.client_s2_node_id)})",
    )
    parser.add_argument("--server_S2_nodeId", default=None, help="The id of the server S2 node (default: auto generated)")
    parser.add_argument(
        "--pairing_token",
        default=settings.pairing_token,
        help=f"Pairing token for pairing (default: {_format_default(settings.pairing_token)})",
    )
    parser.add_argument(
        "--s2_role",
        default=settings.client_role.value,
        help=f"The S2 role we are fulfilling, either RM or CEM (default: {_format_default(settings.client_role.value)})",
    )
    parser.add_argument(
        "--deployment",
        default=settings.client_deployment.value if settings.client_deployment else None,
        help=(
            "The deployment of this client (WAN or LAN); if not specified this script will try to auto detect "
            f"based on server_url, domain and certificate_file (default: {_format_default(settings.client_deployment.value if settings.client_deployment else None)})"
        ),
    )
    parser.add_argument(
        "--supported_s2_message_versions",
        default=None,
        action="append",
        help=(
            "The supported S2 message versions (one per use of the parameter, "
            f"default from settings: {settings.supported_s2_versions})"
        ),
    )
    parser.add_argument(
        "--communication_protocols",
        default=None,
        action="append",
        help=(
            "The communication protocols supported (one per use of the parameter, "
            f"default from settings: {[protocol.value for protocol in settings.supported_communication_protocols]})"
        ),
    )
    parser.add_argument(
        "--supported_hmac_hashing_algorithms",
        default=None,
        action="append",
        help=(
            "The HMAC hashing algorithms supported (one per use of the parameter, "
            f"default from settings: {[algorithm.value for algorithm in settings.supported_hmac_hashing_algorithms]})"
        ),
    )

    parser.add_argument(
        "--brand",
        default=settings.cleint_brand,
        help=f"The brand of this S2 node (default: {_format_default(settings.cleint_brand)})",
    )
    parser.add_argument(
        "--type",
        default=settings.client_device_type,
        help=f"The type of this S2 node (default: {_format_default(settings.client_device_type)})",
    )
    parser.add_argument(
        "--model_name",
        default=settings.client_model_name,
        help=f"The model name of this S2 node (default: {_format_default(settings.client_model_name)})",
    )
    parser.add_argument(
        "--pairing_s2_node_id",
        default=settings.pairing_s2_node_id,
        help=(
            "Target identifier for the node to pair: UUID (sent as nodeId) or short alphanumeric alias "
            f"(sent as nodeIdAlias). Default: {_format_default(settings.pairing_s2_node_id)}"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--skip_cert_verify",
        action="store_true",
        default=not settings.verify_tls,
        help=f"Skip certificate verification (default: {_format_default(not settings.verify_tls)})",
    )
    parser.add_argument("--connect", action="store_true", help="Connect mode. Must be used together with --pairing_s2_node_id (or --pairing_S2_nodeId) and --verbose if desired.")
    parser.add_argument("--unpair", action="store_true", help="Unpair mode. Must be used together with --pairing_s2_node_id (or --pairing_S2_nodeId) and --verbose if desired.")

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    # generate client id if not given
    clientS2NodeId: UUID = UUID(args.client_S2_nodeId) if args.client_S2_nodeId else uuid4()
    pairing_s2_node_id: str | None = args.pairing_s2_node_id if args.pairing_s2_node_id else args.pairing_S2_nodeId
    storage_key = pairing_s2_node_id if pairing_s2_node_id else str(clientS2NodeId)

    if args.connect:
        await _run_connect_mode(parser, args, settings, dao, pairing_s2_node_id, storage_key)
        return

    if args.unpair:
        await _run_unpair_mode(parser, args, settings, dao, pairing_s2_node_id)
        return

    await _run_pairing_mode(args, settings, dao, pairing_s2_node_id, clientS2NodeId, storage_key)


def main() -> None:
    asyncio.run(_run_client())

if __name__ == "__main__":
    main()
