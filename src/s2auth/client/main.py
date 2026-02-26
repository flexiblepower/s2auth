"""Script for running the reference implemntation of the S2 pairing client.
"""
import argparse
import asyncio
import logging
from uuid import UUID, uuid4

from s2auth.client.dao import Dao
from s2auth.client.pairing import connect, pair, strip_pairing_url
from s2auth.common.model.s2_over_ip_common import S2NodeDescription, S2NodeId
from s2auth.common.model.s2_over_ip_pairing import HmacHashingAlgorithm


async def _run_client():
    logger = logging.getLogger("pairing client script")

    parser = argparse.ArgumentParser(description="S2 pairing client example implementation.")

    parser.add_argument("--server_url", default="http://localhost", help="The pairing URL of the pairing server (default: http://localhost)")
    parser.add_argument("--client_S2_nodeId", default=None, help="The id of the client S2 node, (default: auto generated)")
    parser.add_argument("--server_S2_nodeId", default=None, help="The id of the server S2 node, (default: auto generated)")
    parser.add_argument("--access_token", help="Access token for pairing, (default: auto generated, but auto generated is only valid if we are pairing server)")
    parser.add_argument("--s2_role", default="RM", help="The S2 role we are fulfilling, Either RM or CEM (Default: RM)")
    parser.add_argument("--deployment", default="LAN", help="The deployment of this client (WAM or LAN)")
    parser.add_argument("--supported_s2_message_versions", default=["NEN-EN 50491-12-2"], help="The supported S2 message versions (one per use of the parameter, default: NEN-EN 50491-12-2)")
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

    # generate client id if not given
    clientS2NodeId: UUID = UUID(args.client_S2_nodeId) if args.client_S2_nodeId else uuid4()
    logger.warning(f"Starting pairing client with clientS2NodeId: {clientS2NodeId}")

    s2_client_description: S2NodeDescription = S2NodeDescription(id=S2NodeId(clientS2NodeId),
                                                                 brand=args.brand,
                                                                 type=args.type,
                                                                 modelName=args.model_name,
                                                                 role=args.s2_role)

    dao = Dao()
    server_url: str = strip_pairing_url(args.server_url)
    assert await pair(pairing_uri=server_url,
                      pairing_token=args.access_token,
                      storage=dao,
                      role=args.s2_role,
                      deployment=args.deployment,
                      supported_s2_message_versions=args.supported_s2_message_versions,
                      supported_communication_protocols=args.communication_protocols,
                      supportedHmacHashingAlgorithms=list(map(HmacHashingAlgorithm, args.supported_hmac_hashingAlgorithms)),
                      s2_client_description=s2_client_description,
                      verify=not args.skip_cert_verify)

    if args.s2_role == "RM":
        assert connect(client_uri=server_url,
                       storage=dao,
                       supported_s2_message_versions=args.supported_s2_message_versions,
                       supported_communication_protocols=args.communication_protocols,
                       s2_client_description=s2_client_description,
                       serverS2NodeId=str(clientS2NodeId),
                       clientS2NodeId=str(clientS2NodeId),
                       verify=not args.skip_cert_verify)

        logger.warning(f"Initiated connection with token : {dao.load_connection_details(str(clientS2NodeId))}")


def main():
    asyncio.run(_run_client())


if __name__ == "__main__":
    main()
