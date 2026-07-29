"""Script for running the reference implemntation of the S2 pairing client.
"""
import argparse
import asyncio
import ipaddress
import logging
from urllib.parse import urlparse
from uuid import UUID, uuid4

from s2auth.client.dao import Dao
from s2auth.client.pairing import pair, strip_pairing_url
from s2auth.common.model.s2_connect_common import NodeDescription, NodeId
from s2auth.common.model.s2_connect_pairing import HmacHashingAlgorithm

LOGGER = logging.getLogger(__name__)

def detect_deployment(
    pairing_url: str,
    domain_name: str | None,
    certificate_file: str | None,
) -> tuple[str, str]:
    if domain_name:
        return "WAN", "domain provided"
    if certificate_file:
        return "LAN", "certificate_file provided"

    hostname = (urlparse(pairing_url).hostname or "").lower()
    if hostname in {"", "localhost"} or hostname.endswith(".local"):
        return "LAN", f"host '{hostname or '<empty>'}' looked local"

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return "LAN", f"host '{hostname}' is private/local IP"
        return "WAN", f"host '{hostname}' is public IP"
    except ValueError:
        # Non-IP hostname: treat as WAN by default.
        return "WAN", f"host '{hostname}' looked public"


async def _run_client():
    parser = argparse.ArgumentParser(description="S2 pairing client example implementation.")

    parser.add_argument("--server_url", default="http://localhost", help="The pairing URL of the pairing server (default: http://localhost)")

    parser.add_argument("--domain", default=None, help="The domain name to use in a WAN deployment (default: None, example: example.com)")
    parser.add_argument("--certificate_file", default=None, help="Path to the PEM certificate file to use as fingerprint in a LAN deployment (default: auto-detect)")

    parser.add_argument("--pairing_S2_nodeId", default=None, help="The id of the client S2 node, (default: None, examle ninechars)")
    parser.add_argument("--client_S2_nodeId", default=None, help="The id of the client S2 node, (default: auto generated)")
    parser.add_argument("--server_S2_nodeId", default=None, help="The id of the server S2 node, (default: auto generated)")
    parser.add_argument("--pairing_token", help="Pairing token for pairing, (default: auto generated, but auto generated is only valid if we are pairing server)")
    parser.add_argument("--s2_role", default="RM", help="The S2 role we are fulfilling, Either RM or CEM (Default: RM)")
    parser.add_argument("--deployment", default=None, help="The deployment of this client (WAM or LAN) if not specified this script will try to auto detect based on the server_url, domain and certificate_file parameters")
    parser.add_argument("--supported_s2_message_versions", default=["v1"], help="The supported S2 message versions (one per use of the parameter, default: v1)")
    parser.add_argument("--communication_protocols", default=["WebSocket"], action="append", help="The communication protocols supported (one per use of the parameter, default: Websocket)")
    parser.add_argument("--supported_hmac_hashingAlgorithms", default=["SHA256"], action="append", help="The Hmac Hashing Algorithms supported (one per use of the parameter, default: \"SHA256\")")

    parser.add_argument("--brand", default="ExampleHeatCo", help="The brand of this S2 node (default: ExampleHeatCo)")
    parser.add_argument("--type", default="Heatpump", help="The type of this S2 node (default: auto Heatpump)")
    parser.add_argument("--model_name", default="SmartHeatPump X200", help="The model name of this S2 node (default: SmartHeatPump X200)")
    parser.add_argument("--pairing_s2_node_id", default=None, help="The s2 node id of the S2 node to pair (default None, indicating id same as client, assuming only 1 device per client)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--skip_cert_verify", action="store_true", help="Skip certificate verification")

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    server_url: str = strip_pairing_url(args.server_url)
    if args.deployment is None:
        args.deployment, reason = detect_deployment(server_url, args.domain, args.certificate_file)
        LOGGER.warning(f"Auto-detected deployment={args.deployment} ({reason})")

    if args.deployment.upper() == "WAN" and args.domain is None:
        server_url_str: str = args.server_url
        args.domain = urlparse(server_url_str).hostname or ""
        LOGGER.warning(f"Auto-detected domain='{args.domain}' from server_url")

    # generate client id if not given
    clientS2NodeId: UUID = UUID(args.client_S2_nodeId) if args.client_S2_nodeId else uuid4()
    pairing_s2_node_id: str | None = args.pairing_s2_node_id if args.pairing_s2_node_id else args.pairing_S2_nodeId

    LOGGER.info(f"Starting pairing client with clientS2NodeId: {clientS2NodeId}")

    s2_client_description: NodeDescription = NodeDescription(id=NodeId(clientS2NodeId),
                                                             brand=args.brand,
                                                             type=args.type,
                                                             modelName=args.model_name,
                                                             role=args.s2_role)

    dao = Dao()

    pairing_code: str = f"{args.pairing_s2_node_id}-{args.pairing_token}" if args.pairing_s2_node_id else args.pairing_token
    assert await pair(pairing_uri=server_url,
                      pairing_code=pairing_code,
                      storage=dao,
                      role=args.s2_role,
                      deployment=args.deployment.upper(),
                      supported_s2_message_versions=args.supported_s2_message_versions,
                      supported_communication_protocols=args.communication_protocols,
                      supportedHmacHashingAlgorithms=list(map(HmacHashingAlgorithm, args.supported_hmac_hashingAlgorithms)),
                      s2_client_description=s2_client_description,
                      domain_name = args.domain,
                      pairingS2NodeId=pairing_s2_node_id,
                      verify_tls=not args.skip_cert_verify,
                      ca_cert_file=args.certificate_file)

    storage_key = pairing_s2_node_id if pairing_s2_node_id else str(clientS2NodeId)
    LOGGER.warning("--- Pairing info: ---")
    LOGGER.warning(f"pairing_s2_node_id: {pairing_s2_node_id}")
    LOGGER.warning(f"Connection details rereived: {dao.load_connection_details(storage_key)}")

#    assert await connect(pairing_uri=server_url,
#                         storage=dao,
#                         supported_s2_message_versions=args.supported_s2_message_versions,
#                         supported_communication_protocols=args.communication_protocols,
#                         s2_client_description=s2_client_description,
#                         serverS2NodeId=storage_key,
#                         clientS2NodeId=str(clientS2NodeId),
#                         verify_tls=not args.skip_cert_verify,
#                         ca_cert_file=args.certificate_file)
#
#    LOGGER.warning(f"Initiated connection with token: {dao.load_token(str(clientS2NodeId))}")
#    LOGGER.warning(f"Retreived communication defauls: {dao.load_ws_connection_details(str(pairing_s2_node_id))}")


def main():
    asyncio.run(_run_client())


if __name__ == "__main__":
    main()
