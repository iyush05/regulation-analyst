# Connecting the research service

Endpoint: `https://regulation-analyst-api.onrender.com/mcp/`

This is a Streamable HTTP MCP endpoint. The client must support a configured
`Authorization: Bearer <research-access-token>` header. Obtain a research credential from
the service operator and store it in the client's credential settings. Do not paste it into
chat, reports or shared configuration. The web application's administrative token is not
a research credential.

Connect Agensi separately to load the skill. Buying or loading the skill does not create a
research account or configure this endpoint. Confirm access with the operator before
buying a listing that depends on this service. The initial service provisions credentials
manually; it does not implement OAuth login or automatic Agensi purchase verification.

Once connected, call `list_companies` and `list_metrics` to verify access and supported
coverage. The initial limit is 120 HTTP requests per minute per credential, subject to
operator configuration. A 429 response supplies a `Retry-After` value; wait that long before
retrying. A 401 means the credential is missing, invalid or revoked. A 404 may mean the
operator has not enabled the endpoint. Do not retry failed authentication repeatedly.

An agent without configurable bearer-header support is not supported by this release.
Browser origins may need explicit operator approval in the server configuration.

Queries are sent to the independently hosted Regulation Analyst service. The initial
endpoint provides a shared corpus and no private uploads or user-specific storage.
