import base64, datetime, os
from typing import Optional, List
import httpx

def main() -> None:
    print('Hello world!')

if __name__ == '__main__':
    main()


class PairingClient:

    """
    PairingClient of the S2 pairing process.
    Attributes:
        storage (Dao): The storage backend for persisting pairing information.
        role: The S2 role (CEM/RM) of the client.
        deployment: The deployment (WAN/LAN) of this client
        supported_s2_message_versions: List of versions of the S2 messages that the client supports
        supported_communication_protocols: List of communication protocols (e.g. WebSockets) that the client supports
    Methods:
        pair():
            Initiates the pairing process.
    """
    def __init__(self, storage: Dao, role, deployment, supported_s2_message_versions, supported_communication_protocols) -> None:
        self.storage = storage
        self.role = role
        self.deployment = deployment
        self.supported_s2_message_versions = supported_s2_message_versions
        self.supported_communication_protocols = supported_communication_protocols
        pass

    """
    Attributes:
        s2_client_description: Information about this client that will be send to the server, such as brand, model, logo URL etc. Also contains a globally unique identifier of the S2 node this client wants to pair to a node on the server
        pairing_s2_node_id: optional identifier of the S2 node at the server (that has been communicated to the client via the end user) this client node will be paired with.
    """
    async def pair(self, s2_client_description, pairing_s2_node_id=None):
        # Create client HMAC challenge that the server needs to solve
        # Create /requestPairing request body object
        # Do the HTTP request
        # Check the client HMAC challenge response
        # Solve the server HMAC challenge
        # Depending on the client/server role in the connection initiation of other S2 node either requestConnectionDetails or postConnectionDetails
        # In any case, store the connection details in the database.
        client_hmac_challenge = make_client_hmac_challenge()
        body = {
        "s2ClientNodeDescription": {
            "id": f"{s2_client_description.id}",
            "brand": f"{s2_client_description.brand}",
            "logoUri": f"{s2_client_description.logoUri}",
            "type": f"{s2_client_description.type}",
            "modelName": f"{s2_client_description.modelName}",
            "userDefinedName": f"{s2_client_description.userDefinedName}",
            "role": f"{self.role}"
        },
        "s2ClientEndpointDescription": {
            "name": "string",
            "logoUri": "string",
            "deployment": "WAN"
        },
        "pairingS2NodeId": f"{pairing_s2_node_id}",
        "supportedCommunicationProtocols": [
            self.supported_communication_protocols
        ],
        "supportedS2MessageVersions": [
            self.supported_communication_protocols
        ],
        "supportedHmacHashingAlgorithms": [
            "SHA256"
        ],
        "clientHmacChallenge": client_hmac_challenge,
        "forcePairing": False
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post("https://s2server.example.com/requestPairing", json=body)
                response_data = response.json()
                if response.status_code == 200:
                    # Process successful response
                    attempt_id=response_data.get("attemptId")
                    if(check_client_hmac_challenge_response(client_hmac_challenge,response.get("clientHmacChallengeResponse"))):
                        if self.role=="CEM":
                            connection_details=await request_connection_details(attempt_id,response_data.get("serverHmacChallenge"))
                            # Store connection details in the database
                            self.storage.store_connection_details(s2_client_description.id,connection_details)
                        else:
                            await post_connection_details(attempt_id, {}, response_data.get("serverHmacChallenge"))
                            # Post connection details logic for RM role
                        
                    final_response = await finalize_pairing(attempt_id, success=True)
                    return (final_response.status_code == 204)
        except httpx.HTTPError as e:
            # Handle HTTP error
            return False

    def make_client_hmac_challenge():
        # 32 random bytes typical → base64 encoded
        challenge = base64.b64encode(os.urandom(32)).decode()

        expiration = (datetime.datetime.utcnow()
                    + datetime.timedelta(minutes=5)).isoformat() + "Z"

        return {
            "hmacChallenge": challenge,
            "expirationTime": expiration
        }

    def check_client_hmac_challenge_response(challenge, response):
        # Implement HMAC challenge response verification logic here
        return True,

    async def request_connection_details(attempt_id: str,serverHmacChallangeResponse) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://s2server.example.com/requestConnectionDetails", json={attempt_id,serverHmacChallangeResponse})
            return response.json()
        
    async def post_connection_details(attempt_id: str, connection_details: dict, server_hmac_challenge: dict) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post("https://s2server.example.com/postConnectionDetails", json={attempt_id,connection_details,server_hmac_challenge})
            return response.json()

    async def finalize_pairing(attempt_id: str, success: Optional[bool] = None) -> None:
        async with httpx.AsyncClient() as client:
            body = {"attemptId": attempt_id, "success": success}
            response = await client.post("https://s2server.example.com/finalizePairing", json=body)
            return response.json()
        

class ConnectionClient:
    def __init__(self, storage: Dao, role, deployment, supported_s2_message_versions, supported_communication_protocols) -> None:
        self.storage = storage
        self.role = role
        self.deployment = deployment
        self.supported_s2_message_versions = supported_s2_message_versions
        self.supported_communication_protocols = supported_communication_protocols
        

    async def connect(self, s2_client_description, pairing_s2_node_id=None):
        async with httpx.AsyncClient() as client:
            response = await httpx.post("https://s2server.example.com/initiateConnection", json={"s2ClientNodeId": pairing_s2_node_id, "supportedS2MessageVersions": self.supported_s2_message_versions,"supportedCommunicationProtocols": self.supported_communication_protocols})
            if response.status_code == 200:
                confirmation = await self.confirmToken(response.json().get("pendingToken"))
                if confirmation.status_code == 200:
                    # Store connection details in the database
                    token = confirmation.json().get("websocketToken")
                    self.storage.store_connection_details(token)
                    return True
        

    def get_access_token(self):
        pass
    
    async def confirmToken(pendingToken: str):
        async with httpx.AsyncClient() as client:
            body = {"pendingToken": pendingToken}
            response = await client.post("https://s2server.example.com/confirmToken", json=body)
            return response.json()

    async def unpair( pairing_s2_node_id=None):
        async with httpx.AsyncClient() as client:
            response = await client.post("https://s2server.example.com/unpair", json={pairing_s2_node_id})
            return response.json()
