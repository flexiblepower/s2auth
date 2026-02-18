import argparse
import asyncio
import logging
from uuid import UUID, uuid4

from s2auth.client.dao import Dao
from s2auth.client.pairing import ConnectionClient, PairingClient
from s2auth.common.model.s2_over_ip_common import S2NodeDescription, S2NodeId
from s2auth.common.model.s2_over_ip_pairing import HmacHashingAlgorithm

logging.basicConfig(level=logging.WARNING)




async def run_client():
    logger = logging.getLogger("PairingClient")

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

    args = parser.parse_args()

    # generate client id if not given
    clientS2NodeId: UUID = UUID(args.client_S2_nodeId) if args.client_S2_nodeId else uuid4()
    logger.warning(f"Starting pairing client with clientS2NodeId: {clientS2NodeId}")

    s2_client_description: S2NodeDescription = S2NodeDescription(id = S2NodeId(clientS2NodeId),
                                                                 brand = args.brand,
                                                                 type = args.type,
                                                                 modelName = args.model_name,
                                                                 role = args.s2_role)

    dao = Dao()
    pairing_client: PairingClient = PairingClient(
        pairing_uri = args.server_url,
        pairing_token = args.access_token,
        storage = dao,
        role = args.s2_role,
        deployment = args.deployment,
        supported_s2_message_versions = args.supported_s2_message_versions,
        supported_communication_protocols = args.communication_protocols,
        supportedHmacHashingAlgorithms = list(map(HmacHashingAlgorithm, args.supported_hmac_hashingAlgorithms))
    )

    logger.warning(f"Using access token: {pairing_client.pairing_token_str}")

    if args.s2_role == "RM":
        connection_client = ConnectionClient(args.server_url,
                                             storage = dao,
                                             role = args.s2_role,
                                             deployment = args.deployment,
                                             supported_s2_message_versions = args.supported_s2_message_versions,
                                             supported_communication_protocols = args.communication_protocols)

        assert connection_client.connect(s2_client_description = s2_client_description, serverS2NodeId = str(clientS2NodeId), clientS2NodeId = str(clientS2NodeId))
        logger.warning(f"Initiated connection with token : {connection_client.get_pairing_token_str(str(clientS2NodeId))}")

def main():
    asyncio.run(run_client())

if __name__ == "__main__":
    main()
