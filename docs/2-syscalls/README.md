# Section 2 — System Calls (API Reference)

HTTP API endpoints exposed by the Lumina API server.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| [/api/chat](lumina-api-server.md#post-apichat) | POST | Optional | Process a conversational turn |
| [/api/health](lumina-api-server.md#get-apihealth) | GET | None | Health check |
| [/api/domain-info](lumina-api-server.md#get-apidomain-info) | GET | None | Domain UI manifest |
| [/api/tool/{tool_id}](lumina-api-server.md#post-apitooltool_id) | POST | Optional | Invoke a tool adapter |
| [/api/ctl/validate](lumina-api-server.md#get-apictlvalidate) | GET | Role-gated | CTL chain validation |
| [/api/auth/register](lumina-api-server.md#post-apiauthregister) | POST | None | Register a new user |
| [/api/auth/login](lumina-api-server.md#post-apiauthlogin) | POST | None | Authenticate and get JWT |
| [/api/auth/refresh](lumina-api-server.md#post-apiauthrefresh) | POST | Bearer | Refresh a JWT |
| [/api/auth/me](lumina-api-server.md#get-apiauthme) | GET | Bearer | Current user profile |
| [/api/auth/users](lumina-api-server.md#get-apiauthusers) | GET | root/it_support | List all users |
