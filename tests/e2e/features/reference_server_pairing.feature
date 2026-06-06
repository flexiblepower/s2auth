Feature: Reference server pairing

  Scenario: Pairing returns the reference connection router URL
    Given the reference server is running
    When user alice begins pairing with a pairing token
    And the client requests pairing
    And the client requests connection details
    Then the connection initiation endpoint is the reference connection router URL
