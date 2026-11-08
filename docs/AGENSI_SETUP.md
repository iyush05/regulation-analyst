# Enable the Agensi integration on the existing Render service

The existing service at `https://regulation-analyst-api.onrender.com` can serve both the web
API and the new read-only MCP endpoint. A separate server or frontend deployment is not
required. The public health endpoint returned HTTP 200 during implementation on 2026-11-08;
that confirms reachability, not deployment of these changes or persistent storage.

## Deploy and enable

1. Deploy this revision through the service's existing Git/Render workflow. The Docker start
   command stays the same. No additional Python dependencies are required.
2. In Render's environment settings, add `REGULATION_MCP_TOKENS` as a JSON object mapping
   a distinct buyer/pilot label to a unique random credential of at least 32 characters.
   Generate credentials locally with a password manager or `python -c
   'import secrets; print(secrets.token_urlsafe(32))'`. Do not commit or publish the output.
   The structure is `{"pilot-user":"<generated research token>"}`; replace the illustrative
   value before saving. It must differ from `REGULATION_API_TOKEN`.
3. Keep `REGULATION_API_TOKEN` for the existing web app and administrative workflows.
   Research credentials authorize only `/mcp/`. With an absent or empty token mapping,
   `/mcp/` is disabled and returns 404. Invalid credential configuration fails startup.
4. The allowed host defaults to Render's `RENDER_EXTERNAL_HOSTNAME`. If using a custom
   domain or if that variable is unavailable, set `REGULATION_MCP_ALLOWED_HOSTS` to exact,
   comma-separated hostnames, for example `regulation-analyst-api.onrender.com`.
   Do not use wildcard domains. Native clients do not need browser origins. For a browser
   client, configure its exact origin in both `REGULATION_MCP_ALLOWED_ORIGINS` and the
   existing `REGULATION_CORS_ORIGINS` setting, then test that client explicitly.
5. Save the environment changes and redeploy. Removing a buyer's entry and restarting
   revokes their credential. Replace an entry with a new random value to rotate it.

Endpoint: **`https://regulation-analyst-api.onrender.com/mcp/`** (include the trailing slash).
Transport: Streamable HTTP. Authentication: `Authorization: Bearer <research token>`.
Configure the header through the client's secure credential settings.

This release supports clients that accept custom bearer headers. It does not implement
OAuth discovery/login, automatic Agensi purchase validation, private uploads or separate
buyer corpora. Do not advertise compatibility with OAuth-only connectors. Access is
provisioned by the operator and must be communicated to buyers before purchase.

## Storage and operating costs

The checked-in Blueprint still uses the free plan; this change does not purchase hosting.
It can demonstrate the bundled, read-only seed corpus, but filesystem changes are ephemeral.
If you need new ingestions to survive restarts, attach persistent storage at `/data` on a
suitable paid service and verify the database and archives survive a restart. Render's
[disk documentation](https://render.com/docs/disks) explains persistence and paid-service
requirements. Back up current data before changing storage or redeploying an ephemeral service.

`deploy/seed.sqlite3` is copied on initial database creation. It omits source PDFs, so source
page images remain unavailable until archives are deployed and their stored paths resolve.
The MCP service still returns available citation metadata. Do not promise archived images
based solely on a successful health check.

The MCP tools use deterministic research operations and do not invoke the backend model or
ingestion. The buyer's agent supplies the model. Existing REST agent/ingestion routes retain
their current provider costs and administrative credential.

The default limit is 120 HTTP requests per minute per research credential, configurable with
`REGULATION_MCP_REQUESTS_PER_MINUTE`. This includes protocol requests, not just tool calls.
Limits are in memory per worker and reset on restart. Keep one worker for the pilot. A larger
deployment needs shared quotas and proper account lifecycle integration.

## Verify after deployment

- `/api/health` returns 200.
- POST `/mcp/` without authentication returns 401 when enabled (404 means disabled or old
  code). Do not send real tokens in shared shell history.
- Connect a compatible MCP client using its secure credential configuration. Initialize,
  list tools, and confirm the ten research tools are available and `ingest_company` is absent.
- Ask `Infosys operating margin FY24 to FY25`, inspect citations and extraction trust, then
  try an unsupported company/year. Verify the latter reports a gap.
- Verify a research credential gets 401 on `/api/jobs` and `/api/ingest`, and verify a removed
  credential stops working after restart. Check persistence if a disk is configured.

Local regression coverage is in `tests/test_http_mcp.py`: an actual SDK client connects via
the mounted ASGI transport, initializes, discovers tools, calculates an answer and reads a
resource. Additional tests cover authentication, admin isolation, host/origin checks,
credential validation, revocation and independent rate limits.

## Build and submit

```sh
.venv/bin/python scripts/package_agensi.py
```

The upload artifact is `dist/regulation-analyst-agensi.zip`. It contains only four maintained
text files from `marketplace/regulation-analyst/`; no database, source PDFs, credentials,
application code or installed dependencies. Rebuild it after changing skill instructions.

Enable Creator Mode, then upload at https://www.agensi.io/dashboard/submit. Use the draft
in [AGENSI_LISTING.md](AGENSI_LISTING.md), declare the separate research service under
“Needs access to,” and test a real buyer connection before submission. Capture a real
request/result demonstration after live verification. Paid listings also need payout setup.
Agensi reviews new listings before publication; the ZIP itself does not grant backend access.

See [packaging](https://www.agensi.io/docs/packaging) and
[submission requirements](https://www.agensi.io/docs/submit-on-the-website).
