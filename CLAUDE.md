# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Dify Plugin that enables webhook-based triggering of Dify applications (both chatflows and workflows). The plugin provides flexible API key handling, middleware support, and custom request/response processing for third-party integrations.

## Development Commands

### Testing
```bash
pytest
```
- Tests are located in `tests/` directory
- Test configuration is in `pytest.ini`

### Running the Plugin Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment (copy .env.example to .env and configure)
python -m main
```

### Package for Distribution
```bash
dify-plugin plugin package .
```
- Creates a `plugin.difypkg` file for distribution

## Architecture Overview

### Core Components

- **main.py**: Entry point that initializes the Dify plugin with 120s timeout
- **group/webhook.yaml**: Main plugin configuration defining settings and endpoint mappings
- **endpoints/**: Contains endpoint definitions and core webhook logic
  - `invoke_endpoint.py`: Main webhook handler (`WebhookEndpoint` class)
  - `helpers.py`: Utility functions for middleware, API key validation, and routing
  - `*.yaml` files: Endpoint configurations for dynamic/static chatflow/workflow routes
- **middlewares/**: Extensible middleware system
  - `default_middleware.py`: Core request transformations (JSON string conversion)
  - `discord_middleware.py`: Discord webhook signature verification

### Plugin Configuration

The plugin supports multiple configuration options defined in `group/webhook.yaml`:
- **static_app_id**: Optional app selector to limit exposure to a single app
- **api_key**: Secret API key for authentication
- **api_key_location**: Where to expect the API key (`api_key_header`, `token_query_param`, or `none`)
- **middleware**: Middleware selection (`discord` or `none`)
- **signature_verification_key**: For Discord signature verification
- **explicit_inputs**: Use `req.body.inputs` vs `req.body` as input source
- **json_string_input**: Transform entire request body to JSON string
- **raw_data_output**: Send only `res.body.data` for workflow responses

### Endpoint Types

The plugin exposes four main endpoint types:
1. **Dynamic Chatflow** (`/chatflow/<app_id>`): Exposes all workspace chatflows
2. **Dynamic Workflow** (`/workflow/<app_id>`): Exposes all workspace workflows  
3. **Static Chatflow** (`/single-chatflow`): Single app chatflow endpoint
4. **Static Workflow** (`/single-workflow`): Single app workflow endpoint

### Request Flow

1. Request hits `WebhookEndpoint._invoke()` method in `endpoints/invoke_endpoint.py:33`
2. Route determination via `determine_route()` in `endpoints/helpers.py`
3. Middleware processing via `apply_middleware()` in `endpoints/helpers.py:7`
4. API key validation via `validate_api_key()` in `endpoints/helpers.py:37`
5. Request forwarding to appropriate Dify API (chatflow or workflow)
6. Response processing and optional data extraction

### Middleware System

Middleware classes follow a standard interface:
- `invoke(r: Request, settings: Mapping) -> Optional[Response]`
- Return `None` to continue processing, or `Response` to short-circuit
- Default middleware always runs after custom middleware
- Discord middleware handles Ed25519 signature verification for Discord webhooks

## Key Dependencies

- **dify_plugin**: Core Dify plugin SDK (v0.0.1b72)
- **Flask/Werkzeug**: HTTP request/response handling
- **PyNaCl**: Discord signature verification
- **httpx**: HTTP client for Dify API calls
- **pydantic**: Data validation and settings management