# MCP Gateway Deployment Guide — Enterprise Multi-User Deployment

**Audience:** IT/platform teams at law firms deploying the CourtListener MCP server for multi-user internal use.
**Source repos:** [Bifrost OSS](https://github.com/maximhq/bifrost), [Microsoft MCP Gateway](https://github.com/microsoft/mcp-gateway)

---

## The Interface Contract

The MCP server uses two distinct authentication layers. Gateways must inject both headers when endpoint auth is enforced:

```
x-api-key: <INTERNAL_AUTH_SECRET>          # Endpoint protection (opt-in — omit if not set)
X-CourtListener-Token: <user's-cl-api-key> # Per-user CourtListener data access
```

**`x-api-key` / `INTERNAL_AUTH_SECRET`** — protects the MCP server endpoint itself. If `INTERNAL_AUTH_SECRET` is set on the server, all non-health requests must include this header or receive HTTP 401. If the variable is not set, the check is skipped (open access). In production deployments behind a reverse proxy or gateway, inject `x-api-key` at the proxy layer — MCP clients (Claude Desktop, claude.ai) do not need to configure it manually.

**`X-CourtListener-Token`** — the user's own CourtListener API key for data access. Required for any tool that calls the CourtListener API. This header must arrive on every MCP request (initialize, tools/list, tools/call). The server:
- Hashes the token with SHA256 to create a per-user pool key
- Returns or creates a `CourtListenerClient` for that user
- Each client has its own `RateLimiter` (60 citations/min) and shares a `CircuitBreaker`

The gateway's job is: authenticate the user (Entra ID or other IdP) → map identity to CL API key → inject both headers. The MCP server does not care which gateway did this.

### What the Server Already Handles

Everything below is implemented and requires no gateway changes:

| Capability | Status |
|---|---|
| `x-api-key` endpoint auth (opt-in via `INTERNAL_AUTH_SECRET`) | ✓ Implemented |
| `X-CourtListener-Token` header auth | ✓ Implemented |
| Per-user client pool (LRU, 1000 entries) | ✓ Implemented |
| Per-user rate limiter (60 citations/min) | ✓ Implemented |
| Shared circuit breaker (CourtListener API health) | ✓ Implemented |
| Single-user fallback (env var / DPAPI, backward compat) | ✓ Implemented |
| CORS origins configurable via `CORS_ORIGINS` / `CORS_EXTRA_ORIGIN` env vars | ✓ Implemented |

**Self-hosted without a gateway:** For individual or small-team use, the server accepts a CourtListener API token in a standard `Authorization: Bearer <token>` header — no gateway required. Configure it directly in your MCP client:

```json
{
  "mcpServers": {
    "courtlistener": {
      "url": "https://mcp.yourhost.com/mcp",
      "headers": { "Authorization": "Bearer <your-cl-api-token>" }
    }
  }
}
```

This is a single shared token. For multi-user deployments, use a gateway to inject per-user tokens as described below.

### Rate Limit Architecture

```
Per-user CourtListener API key
    → 60 citations/minute (CourtListener hard limit — applies at their API)
    → Per-user RateLimiter in MCP server client pool (enforced client-side before the API call)
    → Optional: Bifrost rate_limit per virtual key (second layer, for quota enforcement at the gateway)

Shared circuit breaker
    → Trips after 5 consecutive failures across all users
    → 30-second backoff before retry
    → Reflects CourtListener API health globally — not per-user state
    → Protects all users from piling on a degraded upstream
```

---

## Option 1: Bifrost Enterprise (Recommended)

> **Paid tier required.** Everything in this section — virtual keys, OIDC claim binding, per-key header injection, practice group policies, Promptguard, and the Helm chart — requires a Bifrost Enterprise license. The OSS core (`github.com/maximhq/bifrost`) does not include these features. Contact Maxim AI for trial/pricing: `getmaxim.ai/bifrost/enterprise`.

**Why Bifrost for law firms:**
- Fully proxies the MCP protocol including tools, resources, and prompts
- Header injection is a first-class feature (configured per virtual key, no custom code)
- One deployment covers both MCP gateway and LLM traffic routing
- Promptguard plugin scans tool results for prompt injection before they reach the LLM — **but only if LLM API calls also route through Bifrost.** Bifrost must be in both the MCP path and the LLM path for this protection to apply. If lawyers use Claude Desktop (Anthropic subscription) or Microsoft Copilot, their LLM calls go directly to Anthropic/Azure — not through Bifrost — so Promptguard does not cover those sessions. This protection is most relevant when Bifrost is deployed as a unified LLM + MCP gateway, e.g. routing to OpenAI or Azure OpenAI via Bifrost's provider config.

### Architecture

```
Lawyer's Claude Desktop / Microsoft Copilot
    │
    │  MCP over HTTPS + OAuth 2.1 (PKCE)
    │  Authorization: Bearer <entra_jwt>
    ▼
Bifrost Enterprise (firm-hosted or Maxim SaaS)
    │  1. Validates Entra ID JWT (RS256, aud/iss/exp)
    │  2. Extracts oid claim → looks up virtual key
    │  3. Reads headers from virtual key MCPClientConfig
    │  4. Injects X-CourtListener-Token: <cl_api_key>
    ▼
CourtListener MCP Server
    │  Reads X-CourtListener-Token
    │  Per-user client pool + rate limiter
    │  Shared circuit breaker
    ▼
CourtListener REST API v4
    (per-user 60 citations/min)
```

### Step 1: Entra ID App Registration

In Azure Portal > App Registrations > New registration:

```
Name: CourtListener MCP (Bifrost)
Supported account types: Accounts in this organizational directory only
Redirect URI: https://bifrost.firm.com/oauth/callback  (Web)
```

After registration:

1. **Expose an API** → Application ID URI: `api://<client-id>`
2. **Add a scope:** `mcp.access` — "Access CourtListener MCP tools"
3. **Authorized client applications:**
   - Claude Desktop: `aebc6443-996d-45c2-90f0-388ff96faa56` (VS Code client ID, used by Claude Desktop)
   - Any other MCP clients your firm uses
4. **App roles** (optional, for practice group segmentation):
   ```json
   { "displayName": "CourtListener Litigation", "value": "CourtListener.Litigation" }
   { "displayName": "CourtListener All", "value": "CourtListener.All" }
   ```
5. **Token configuration:** Ensure `oid` claim is included (it is by default in v2.0 tokens)

Copy: **Application (client) ID**, **Directory (tenant) ID**, **Client Secret** (Certificates & Secrets > New).

### Step 2: Bifrost OIDC Configuration

In Bifrost's config (UI or API), configure Entra ID as the external identity provider:

```json
{
  "oauth2_configs": [
    {
      "id": "entra-firm",
      "client_id": "<bifrost-app-client-id>",
      "client_secret": "<bifrost-app-client-secret>",
      "server_url": "https://login.microsoftonline.com/<tenant-id>/v2.0",
      "redirect_uri": "https://bifrost.firm.com/oauth/callback",
      "scopes": ["openid", "profile", "email", "api://<client-id>/mcp.access"]
    }
  ]
}
```

Bifrost's OAuth2 discovery (`framework/oauth2/discovery.go`) will automatically:
1. Probe the Entra ID metadata endpoint (`/.well-known/openid-configuration`)
2. Extract `authorization_endpoint`, `token_endpoint`, `jwks_uri`
3. Handle PKCE (code_verifier / code_challenge via SHA256) per RFC 7636
4. Cache and refresh tokens as needed

No manual configuration of `authorize_url` or `token_url` required — Bifrost discovers them.

### Step 3: Virtual Key per Lawyer

Each lawyer gets a Bifrost virtual key (configured via Bifrost API or UI). The virtual key binds the lawyer's Entra `oid` claim to their CourtListener API key and injects it as a header.

**Virtual key structure (Bifrost API):**

```json
{
  "key_name": "lawyer-jsmith",
  "metadata": {
    "display_name": "Jane Smith",
    "entra_oid": "<jane's-entra-oid>",
    "department": "Litigation"
  },
  "mcp_client_config": {
    "name": "courtlistener",
    "connection_type": "http",
    "connection_string": "https://mcp.courtlistener.com/mcp",
    "auth_type": "headers",
    "headers": {
      "x-api-key": "<INTERNAL_AUTH_SECRET>",
      "X-CourtListener-Token": "<jane's-courtlistener-api-key>"
    },
    "tools_to_execute": ["courtlistener_validate_citations", "courtlistener_extract_citations",
                         "courtlistener_search_cases", "courtlistener_search_clusters",
                         "courtlistener_lookup_citation", "courtlistener_get_cluster",
                         "courtlistener_citations_get_guidance"]
  }
}
```

**How the header injection works (from Bifrost source `core/schemas/mcp.go`):**

When `auth_type` is `"headers"`, Bifrost calls `HttpHeaders()`:
```go
case MCPAuthTypeHeaders:
    for key, value := range c.Headers {
        headers[key] = value.GetValue()
    }
```
These headers are attached via `transport.WithHTTPHeaders()` and sent on **every** HTTP request to the MCP server — including `initialize`, `tools/list`, and every `tools/call`. There is no separate "connection-only" channel; one `headers` map covers all.

**Practice group access control via `tools_to_execute`:**

| Entra Group | `tools_to_execute` | Access |
|---|---|---|
| `CourtListener.All` | `["*"]` | All 7 tools |
| `CourtListener.Basic` | `["courtlistener_validate_citations", "courtlistener_extract_citations"]` | Validate + extract only |
| `CourtListener.Disabled` | `[]` | Blocked (deny-by-default) |

Bifrost reads group membership from the Entra ID `roles` claim and selects the matching virtual key policy. No MCP server changes needed.

### Step 4: MCP Backend Registration

Register the CourtListener MCP server as a backend in Bifrost:

```json
{
  "name": "courtlistener-mcp",
  "connection_type": "http",
  "connection_string": "https://mcp.courtlistener.com/mcp",
  "auth_type": "headers",
  "is_ping_available": true,
  "tool_sync_interval": "10m"
}
```

Bifrost will call `tools/list` every 10 minutes to keep the tool catalog fresh.

### Step 5: Deployment

**Docker Compose (testing):**

```yaml
version: "3.9"
services:
  bifrost:
    image: maximhq/bifrost:latest
    ports:
      - "8765:8765"
    environment:
      - BIFROST_ENTERPRISE_LICENSE=<license-key>
      - ENTRA_TENANT_ID=<tenant-id>
      - ENTRA_CLIENT_ID=<client-id>
      - ENTRA_CLIENT_SECRET=<client-secret>
    volumes:
      - ./bifrost-config.json:/app/config.json
```

**Kubernetes (Helm, production):**

The Bifrost Helm chart ([`helm-charts/bifrost/`](https://github.com/maximhq/bifrost/tree/main/helm-charts/bifrost)) deploys StatefulSets with:
- Redis (session + rate limit state)
- PostgreSQL (virtual key store, audit logs)
- Qdrant (optional: vector search for tool catalog)

```bash
helm install bifrost ./helm-charts/bifrost \
  --set config.enterprise.entra_tenant_id=<tenant-id> \
  --set secrets.entra_client_secret=<secret> \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=bifrost.firm.com
```

Key values to review in `helm-charts/bifrost/values.yaml`:
- `replicaCount` — scale horizontally for HA
- `redis.enabled` — required for distributed session state
- `postgresql.enabled` — required for virtual key persistence
- `ingress.tls` — configure TLS cert (required for OAuth callbacks)

### Step 6: Bulk Key Provisioning

For a firm with 500+ lawyers, provision virtual keys in bulk via the Bifrost API:

```python
# Reads CSV: email, entra_oid, cl_api_key, department
import csv, requests

BIFROST_API = "https://bifrost.firm.com/api/v1"
BIFROST_ADMIN_KEY = "<admin-api-key>"

with open("lawyers.csv") as f:
    for row in csv.DictReader(f):
        payload = {
            "key_name": f"lawyer-{row['email'].replace('@firm.com','')}",
            "metadata": {
                "display_name": row["name"],
                "entra_oid": row["entra_oid"],
                "department": row["department"]
            },
            "mcp_client_config": {
                "name": "courtlistener",
                "connection_type": "http",
                "connection_string": "https://mcp.courtlistener.com/mcp",
                "auth_type": "headers",
                "headers": {
                    "x-api-key": INTERNAL_AUTH_SECRET,
                    "X-CourtListener-Token": row["cl_api_key"]
                },
                "tools_to_execute": ["*"] if row["department"] == "Litigation" else
                                    ["courtlistener_validate_citations",
                                     "courtlistener_extract_citations"]
            }
        }
        r = requests.post(f"{BIFROST_API}/virtual-keys", json=payload,
                          headers={"Authorization": f"Bearer {BIFROST_ADMIN_KEY}"})
        print(f"{row['email']}: {r.status_code}")
```

**Rotation:** When a CourtListener API key rotates, update only the Bifrost virtual key — no MCP server restart needed, no client reconfiguration:

```bash
curl -X PATCH https://bifrost.firm.com/api/v1/virtual-keys/lawyer-jsmith \
  -H "Authorization: Bearer <admin-key>" \
  -d '{"mcp_client_config": {"headers": {"X-CourtListener-Token": "<new-key>"}}}'
```

### Step 7: Testing the Full Flow

```bash
# 1. Acquire an Entra ID token (simulate lawyer login)
az account get-access-token --resource api://<client-id> --query accessToken -o tsv

# 2. Verify Bifrost validates the token and routes to the right virtual key
curl -X POST https://bifrost.firm.com/mcp \
  -H "Authorization: Bearer <entra_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# 3. Verify the tool call reaches CourtListener with the correct API key
# (Check Bifrost access logs — should show X-CourtListener-Token injected)

# 4. Test Claude Desktop
# Add to claude_desktop_config.json:
{
  "mcpServers": {
    "courtlistener": {
      "url": "https://bifrost.firm.com/mcp",
      "transport": "http"
    }
  }
}
# Claude Desktop will trigger OAuth: browser opens Entra ID login → firm SSO
```

### MCP Apps (UI Panel) — Gateway Limitation

> **The citation results inline panel does not render through any gateway, including Bifrost.**

The MCP Apps iframe is rendered by the MCP client (Claude Desktop, claude.ai) when it fetches the resource from the MCP server directly. When a gateway sits in between, the `ui://` resource URI scheme and the session context required for the panel do not survive proxying — the client sees tools but the panel is not triggered.

**Workaround:** Connect Claude Desktop directly to the MCP server endpoint (bypassing the gateway) for full panel support. Use the gateway path for Copilot or other clients that do not support MCP Apps panels at all — tools still work fully through the gateway.

> **Warning:** Bypassing the gateway means bypassing per-user token injection. The MCP server falls back to the single shared API key in `COURTLISTENER_API_TOKEN` — putting the entire firm back on one rate limit bucket (60 citations/min shared across all users). For a single-user setup this is fine; for any multi-user deployment, the panel is a cosmetic benefit that is not worth the rate limit regression.
>
> | Scenario | Users | Shared key | Per-user keys (gateway) |
> |---|---|---|---|
> | Small firm | 20 | 3 calls/user/min | 60 calls/user/min |
> | Mid-size firm | 200 | 0.3 calls/user/min | 60 calls/user/min |
> | AmLaw 100 firm | 2,000 | 0.03 calls/user/min | 60 calls/user/min |
> | Free Law membership | 10,000+ | unusable | 60 calls/user/min |

**In practice, the panel is not required for a good user experience.** The tool docstrings and structured return format are written to guide the LLM into producing a well-formatted citation report in-conversation — status badges (✅ / ⚠️), direct CourtListener links, and a clear suspect/verified summary — without any special prompting from the user. Gateway deployments targeting Copilot or ChatGPT work well without the panel.

---

## Option 2: Microsoft MCP Gateway (OSS)

**Repo:** `github.com/microsoft/mcp-gateway`
**When to choose:** Firm already runs AKS, wants pure Azure/Microsoft stack, no additional vendor.
**Deployment:** Kubernetes-only — requires AKS, CosmosDB, Redis, ACR.

### Architecture

```
Lawyer's VS Code / Copilot
    │
    │  MCP over HTTPS + Bearer token (Entra ID JWT)
    ▼
Microsoft MCP Gateway (AKS)
    │  1. Validates Entra ID JWT
    │  2. Extracts oid claim → X-Mcp-UserId header
    │  3. Extracts roles → X-Mcp-Roles header
    │  4. Forwards to MCP proxy pod
    ▼
mcp-proxy container (AKS pod)
    │  MCP_PROXY_URL=https://mcp.courtlistener.com/mcp
    │  Forwards request to CourtListener MCP server
    ▼
CourtListener MCP Server
    │  Reads X-Mcp-UserId
    │  Must look up CL API key from key store ← IMPORTANT DIFFERENCE
    ▼
CourtListener REST API v4
```

### Critical Difference from Bifrost

The Microsoft MCP Gateway **does not inject the CourtListener API key**. It forwards three identity headers to the MCP backend (`Authorization/ForwardedIdentityHeaders.cs`):

```csharp
public const string UserId = "X-Mcp-UserId";    // Entra oid claim
public const string UserName = "X-Mcp-UserName"; // display name
public const string Roles = "X-Mcp-Roles";       // comma-separated roles
```

The `oid` claim is extracted from the JWT (`IdentityExtensions.cs`):
```csharp
public static string? GetUserId(this ClaimsPrincipal principal) =>
    principal?.Claims?.FirstOrDefault(r => r.Type == ClaimTypes.NameIdentifier)?.Value ??
    principal?.Claims?.FirstOrDefault(r => r.Type == "oid")?.Value;
```

**This means the MCP server must look up the CourtListener API key itself** using `X-Mcp-UserId` as the lookup key. Two implementation paths:

**Path A: Add a key lookup table to the MCP server**

The MCP server reads `X-Mcp-UserId` instead of `X-CourtListener-Token` and resolves the key:

```python
# In _resolve_token(), after the header fallback:
try:
    request = get_http_request()
    # Path A: Microsoft MCP Gateway sends X-Mcp-UserId
    user_id = request.headers.get("x-mcp-userid")
    if user_id:
        cl_token = await _lookup_cl_key(user_id)  # Azure Key Vault or CosmosDB
        if cl_token:
            return cl_token
    # Path B: Bifrost / APIM sends X-CourtListener-Token directly
    header_token = request.headers.get("x-courtlistener-token")
    if header_token:
        return header_token.strip()
except RuntimeError:
    pass  # STDIO transport
```

Key store options:
- **Azure Key Vault** — secrets named `cl-api-key-<oid>`, RBAC for MCP server's managed identity
- **CosmosDB** — partition key = `oid`, MCP server queries on each new user
- **Redis** — fast lookup, warm from CosmosDB at startup

**Path B: Add APIM in front of the gateway**

Put Azure APIM between the client and the Microsoft MCP Gateway. APIM runs the `validate-azure-ad-token` policy + a `lookup-courtlistener-key` policy (Azure Function) before forwarding to the gateway. The gateway then forwards the injected `X-CourtListener-Token` to the MCP proxy → MCP server. Complex, but keeps the MCP server unchanged.

**Recommendation:** Path B defeats the purpose of the OSS gateway. Path A (key lookup in the MCP server) is cleaner for this use case, but requires changes to `_resolve_token()`. If you're already committed to the Microsoft MCP Gateway, implement Path A.

### Deploying the MCP Server as an Adapter

Build the MCP proxy image with the CourtListener MCP server URL:

```sh
# Build and push the mcp-proxy image
az acr build -r "mgreg<label>" \
  -f sample-servers/mcp-proxy/Dockerfile sample-servers/mcp-proxy \
  -t "mgreg<label>.azurecr.io/mcp-proxy:1.0.0"
```

Register the CourtListener MCP server as an adapter:

```http
POST https://<gateway-host>/adapters
Authorization: Bearer <entra_admin_token>
Content-Type: application/json
```

```json
{
  "name": "courtlistener",
  "imageName": "mcp-proxy",
  "imageVersion": "1.0.0",
  "description": "CourtListener citation validation MCP server",
  "environmentVariables": {
    "MCP_PROXY_URL": "https://mcp.courtlistener.com/mcp"
  },
  "requiredRoles": ["CourtListener.Access"],
  "useWorkloadIdentity": true
}
```

`requiredRoles` enforces RBAC via `SimplePermissionProvider` — lawyers without `CourtListener.Access` in their Entra token get HTTP 403 from the gateway.

### Entra ID Setup for Microsoft MCP Gateway

```bash
# 1. Create app registration (same as Bifrost Step 1)
# 2. Define app roles: CourtListener.Access, CourtListener.Admin
# 3. Expose API: api://<client-id>
# 4. Authorize VS Code (aebc6443...) and Azure CLI (04b07795...)

# 5. Deploy gateway with your client ID
kubectl apply -f deployment/k8s/local-deployment.yml  # or Azure ARM template

# 6. Acquire token and test
az account get-access-token --resource <client-id>
curl -X POST https://<gateway-host>/adapters/courtlistener/mcp \
  -H "Authorization: Bearer <token>" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### MCP Apps (UI Panel) — Not Supported Through Any Gateway

The citation results inline panel does not render through the Microsoft MCP Gateway, for the same reason as Bifrost: the `ui://` resource URI and session context required for the panel do not survive proxying. Tools function fully.

The same rate limit tradeoff applies: bypassing the gateway for panel support loses per-user token injection and collapses all users onto a shared 60 citations/min bucket. See the rate limit table in the Bifrost panel section above. In practice the panel is not needed — the tool's structured output and prompt engineering guide the LLM to produce an equivalent in-conversation report.

---

## Option 3: Azure APIM (Brief)

Key facts:
- **Native MCP support** in all tiers (Developer through Premium v2) as of late 2025
- **JWT validation:** `validate-azure-ad-token` policy — no custom code
- **Key injection:** Requires Azure Policy + Azure Function or CosmosDB lookup for `oid → CL API key` mapping. Not a built-in primitive.
- **CRITICAL LIMITATION:** Tools only — MCP resources and prompts not supported. Citation results UI panel will not render.
- **Self-hosted gateway:** Available for on-premises / data residency requirements
- **Best for:** Microsoft-first firms that want full Azure governance (Monitor, API Center, Application Insights) — UI panels don't work through any gateway so this is not a differentiator

---

## Gateway Feature Comparison

| Capability | Bifrost Enterprise | Microsoft MCP Gateway (OSS) | Azure APIM |
|---|---|---|---|
| Entra ID JWT validation | ✓ OIDC config | ✓ Built-in | ✓ Native policy |
| Per-user key injection | ✓ Virtual key headers | ✗ Forwards X-Mcp-UserId only | Via policy + function |
| MCP resources (UI panels) | ✗ Panel broken through gateway | ✗ Panel broken through gateway | ✗ Not supported |
| MCP tools | ✓ | ✓ | ✓ |
| PKCE / OAuth 2.1 | ✓ Auto-discovery | Via Entra / client | Via Entra / client |
| Prompt injection scanning | ✓ Promptguard (only if LLM also routes through Bifrost) | ✗ | Via custom policy |
| Existing Azure infrastructure | New vendor | ✓ (AKS required) | ✓ No new vendor |
| Kubernetes required | No (Docker OK) | Yes (AKS) | No (managed service) |
| MCP server changes needed | None | Yes (if Path A) | None |
| Per-user rate limiting | Per virtual key | Requires custom impl | Per subscription key |
| Bulk key provisioning API | ✓ REST API | ✗ (DIY CosmosDB) | ✓ Subscription API |
| Horizontal scaling | Helm (StatefulSet) | AKS HPA | Managed |
| Cost model | Enterprise license | OSS + Azure infra | Per-API call + tier |

---

## Key Provisioning Decision

The biggest operational question is how 500+ lawyers each get a CourtListener API key.

**Option A — Bulk negotiated (recommended for large firms)**

Negotiate with Free Law Project for a multi-seat arrangement. They provision one API key per seat and provide a CSV: `email, cl_api_key`. Firm IT imports into Bifrost via the provisioning script above. Annual renewal = new CSV import.

**Option B — Self-service per lawyer**

Each lawyer creates a free CourtListener account at `courtlistener.com`, generates their API key, and submits it via an internal IT form (ServiceNow, etc.). IT imports into Bifrost. Most friction but no negotiation required — works immediately with existing free accounts.

**Key rotation:**

When a CourtListener API key rotates (annually or on security incident), update the Bifrost virtual key via PATCH. The MCP server's LRU pool will naturally expire the old client entry within 1000 new sessions (pool size). For immediate invalidation: `POST /api/v1/virtual-keys/lawyer-jsmith/invalidate` flushes the pool entry.

---

## Which Gateway Should You Choose?

| Firm profile | Recommendation |
|---|---|
| Already running Bifrost for LLM traffic | Bifrost Enterprise — add MCP config to existing deployment |
| Microsoft-first, Copilot primary client, no UI panel needed | Azure APIM — no new vendor, native governance |
| AKS already deployed, want OSS solution, can modify MCP server | Microsoft MCP Gateway + Path A key lookup |
| Wants UI panels | Connect Claude Desktop directly to MCP server (no gateway for panel path) |
| Okta / Ping / other IdP | Bifrost (supports any OIDC provider via `server_url`) |
| Smallest possible footprint, single-tenant firm | Self-hosted MCP server with single API key in env var — no gateway needed |

---

## Pre-Deployment Questions

Answer these before starting:

1. **Gateway vendor:** Is Bifrost Enterprise on the firm's approved vendor list, or is a Microsoft-stack solution (APIM, Microsoft MCP Gateway) required?
2. **API key provisioning:** Self-service per lawyer (free, immediate) or negotiated bulk (lower friction at scale)?
3. **Matter attribution:** Does the firm need to log which matter triggered each citation search? If yes, this requires a custom `X-Matter-Id` header and changes to the MCP server's logging layer — plan for it before deployment.
4. **Data residency:** Does client data need to stay on-premises or in a specific Azure region? Bifrost has a self-hosted option; APIM has a self-hosted gateway; the Microsoft MCP Gateway is Kubernetes-native and can run anywhere.
5. **Rollout scope:** Litigation department first, or firm-wide? Piloting with one practice group reduces risk and surfaces rate limit / UX issues before broad rollout.

## Implementation Order

1. **API keys** — Decide provisioning model (A or B above). Collect or generate keys for the pilot group.
2. **Entra ID app registration** — Create the app reg, expose the API scope, authorize MCP client apps (Step 1 of the Bifrost section above).
3. **Deploy MCP server** — Docker or Kubernetes. Set `INTERNAL_AUTH_SECRET` to a random secret; configure the gateway to inject `x-api-key` with that value on every request. Leave `COURTLISTENER_API_TOKEN` unset (forces header-only mode — any request without `X-CourtListener-Token` is rejected, ensuring no shared-key fallback in production).
4. **Gateway trial** — Configure OIDC + one virtual key. Test the full auth flow end-to-end with a single test user before bulk provisioning.
5. **Pilot: 5–10 lawyers** — Validate rate limit behavior, error messages, and the in-conversation report format. Confirm no matter attribution requirement.
6. **Bulk provisioning** — Import full roster via the provisioning script. Configure practice group tool policies.
7. **Firm-wide rollout** — Brief IT helpdesk on the OAuth login flow (browser opens once at first use, then tokens are cached). Announce to attorneys.

---

## Related Files

- `src/courtlistener_mcp/main.py` — `_resolve_token()` (header → env → elicitation), `_get_client()` (pool), `_get_shared_circuit_breaker()`
- `src/courtlistener_mcp/api/client.py` — `CourtListenerClient`, `CircuitBreaker`, `RateLimiter`
- [Bifrost `core/schemas/mcp.go`](https://github.com/maximhq/bifrost/blob/main/core/schemas/mcp.go) — `MCPClientConfig` schema (authoritative for header injection)
- [Bifrost `framework/oauth2/discovery.go`](https://github.com/maximhq/bifrost/blob/main/framework/oauth2/discovery.go) — RFC 8414/9728 OIDC discovery
- [Microsoft MCP Gateway `Authorization/`](https://github.com/microsoft/mcp-gateway/tree/main/dotnet/Microsoft.McpGateway.Management/src/Authorization) — gateway RBAC and forwarded identity headers
