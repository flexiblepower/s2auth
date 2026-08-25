Feature: Reference server pairing

  Scenario: Pairing and connection initiation complete against the reference server
    Given the reference server is running
    When the client requests pairing
    And the client requests connection details
    And the client finalizes pairing successfully
    And the client initiates a connection
    Then the connection initiation endpoint is the reference connection router URL
    And the connection initiation response contains the negotiated connection details
