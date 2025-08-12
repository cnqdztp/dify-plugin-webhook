import json
import logging
import asyncio
from typing import Mapping, Dict, Any, Optional
from werkzeug import Request, Response
from dify_plugin import Endpoint
from endpoints.helpers import apply_middleware, validate_api_key, determine_route
import httpx

logger = logging.getLogger(__name__)

class WebhookEndpoint(Endpoint):
    """
    The UnifiedEndpoint handles both workflow and chatflow requests through a single interface.

    This endpoint routes requests to the appropriate Dify API based on the path:
    - Paths starting with /workflow/ will invoke Dify workflows
    - Paths starting with /chatflow/ will invoke Dify chatflows

    For chatflow requests, the following parameters are required:
    - `app_id` (required): The ID of the chatflow to trigger
    - `query` (required): A string representing the query to be processed
    - `inputs` (optional): An object containing inputs needed for the chatflow
    - `conversation_id` (optional): A string representing the conversation ID

    For workflow requests, the following parameters are required:
    - `app_id` (required): The ID of the workflow to trigger
    - `inputs` (optional): An object containing inputs needed for the workflow

    The endpoint behavior can be configured with:
    - `explicit_inputs`: When true, inputs should be in req.body.inputs. When false, req.body is used.
    - `raw_data_output`: When true, workflow responses will only return the data.outputs
    """

    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """
        Invokes the endpoint with the given request for either chatflow or workflow.
        """
        logger.info("Received request to unified endpoint")

        # Determine the endpoint mode
        route = determine_route(r.path)
        if not route:
            logger.error("Invalid path: %s", r.path)
            return Response(json.dumps({"error": "Invalid path. Use /workflow/ or /chatflow/"}),
                            status=404, content_type="application/json")

        logger.info("Request mode: %s", route)

        # Apply middleware
        middleware_response = apply_middleware(r, settings)
        if middleware_response:
            logger.debug("Middleware response: %s", middleware_response)
            return middleware_response

        # Validate API key
        validation_response = validate_api_key(r, settings)
        if validation_response:
            logger.debug("API key validation failed: %s", validation_response)
            return validation_response

        try:
            request_body = getattr(
                r, 'default_middleware_json', {}) or r.get_json()
            
            dynamic_app_id = values.get("app_id")
            static_app_id = settings.get("static_app_id")
            if isinstance(static_app_id, dict):
                static_app_id = static_app_id.get('app_id')
                
            logger.debug("Parsed request body: %s", request_body)
            logger.debug("Extracted dynamic_app_id: %s", dynamic_app_id)
            logger.debug("Extracted static_app_id: %s", static_app_id)

            if not dynamic_app_id and not static_app_id:
                logger.error("app_id is required but not provided.")
                return Response(status=404, content_type="application/json")

            # Handle inputs based on explicit_inputs setting
            explicit_inputs = settings.get('explicit_inputs', True)

            if explicit_inputs:
                inputs = request_body.get("inputs", {})
            else:
                inputs = request_body.copy()

            if not isinstance(inputs, dict):
                logger.error(
                    "Invalid inputs type: expected object, got %s", type(inputs).__name__)
                return Response(json.dumps({"error": "inputs must be an object"}),
                                status=400, content_type="application/json")

            # initialize empty response
            response = None

            if route == "/chatflow/<app_id>":
                if static_app_id:
                    # Do not handle requests to /chatflow/<app_id> when a static app_id is defined
                    # Static app_id is explicitly used to only expose one single app
                    return Response(status=404, content_type="application/json")

                query = request_body.get(
                    "query", None) if explicit_inputs else inputs.pop("query", None)
                if not query or not isinstance(query, str):
                    logger.error("query is required and must be a string")
                    return Response(json.dumps({"error": "query must be a string"}),
                                    status=400, content_type="application/json")

                conversation_id = request_body.get(
                    "conversation_id") if explicit_inputs else inputs.pop("conversation_id", None)
                if conversation_id is not None and not isinstance(conversation_id, str):
                    logger.error(
                        "conversation_id must be a string if provided")
                    return Response(json.dumps({"error": "conversation_id must be a string"}),
                                    status=400, content_type="application/json")

                # Invoke chatflow
                response = self._invoke_chatflow(
                    dynamic_app_id, query, conversation_id, inputs)
            elif route == "/single-chatflow":
                query = request_body.get(
                    "query") if explicit_inputs else inputs.pop("query", None)
                if not query or not isinstance(query, str):
                    logger.error("query is required and must be a string")
                    return Response(json.dumps({"error": "query must be a string"}),
                                    status=400, content_type="application/json")

                conversation_id = request_body.get(
                    "conversation_id") if explicit_inputs else inputs.pop("conversation_id", None)
                if conversation_id is not None and not isinstance(conversation_id, str):
                    logger.error(
                        "conversation_id must be a string if provided")
                    return Response(json.dumps({"error": "conversation_id must be a string"}),
                                    status=400, content_type="application/json")

                # Invoke chatflow
                response = self._invoke_chatflow(
                    static_app_id, query, conversation_id, inputs)

            elif route == "/workflow/<app_id>":
                if static_app_id:
                    # Do not handle requests to /chatflow/<app_id> when a static app_id is defined
                    # Static app_id is explicitly used to only expose one single app
                    return Response(status=404, content_type="application/json")
                # Invoking workflow
                response = self._invoke_workflow(
                    dynamic_app_id, inputs, settings.get('raw_data_output', False))

            elif route == "/single-workflow":
                # Invoking workflow
                response = self._invoke_workflow(
                    static_app_id, inputs, settings.get('raw_data_output', False))
                
                # Send callback if configured for static app
                if static_app_id and settings.get('callback_url'):
                    self._send_callback_async(
                        settings.get('callback_url'),
                        settings.get('callback_secret_token'),
                        response,
                        static_app_id
                    )

            if not response:
                return Response(json.dumps({"error": "Failed to get response"}), status=500, content_type="application/json")
            else:
                # Return response
                logger.debug("%s response: %s", route, response)
                return Response(json.dumps(response), status=200, content_type="application/json")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Error during request processing: %s", str(e))
            return Response(json.dumps({"error": str(e)}), status=500, content_type="application/json")

    def _invoke_chatflow(self, app_id: str, query: str, conversation_id: Optional[str], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invokes a Dify chatflow with the given parameters.

        Args:
            app_id: The ID of the chatflow to invoke
            query: The user query to process
            conversation_id: Optional conversation ID for continuing a conversation
            inputs: Additional inputs for the chatflow

        Returns:
            The chatflow response
        """
        logger.info("Invoking chatflow with app_id: %s", app_id)
        dify_response = self.session.app.chat.invoke(
            app_id=app_id,
            query=query,
            conversation_id=conversation_id,
            inputs=inputs,
            response_mode="blocking"
        )
        return dify_response

    def _invoke_workflow(self, app_id: str, inputs: Dict[str, Any], raw_data_output: bool) -> Dict[str, Any]:
        """
        Invokes a Dify workflow with the given parameters.

        Args:
            app_id: The ID of the workflow to invoke
            inputs: Inputs for the workflow
            raw_data_output: If True, returns only the outputs field of the response

        Returns:
            The workflow response, either full or just the outputs depending on raw_data_output
        """
        logger.info(
            "Invoking workflow with app_id: %s and inputs: %s", app_id, inputs)
        dify_response = self.session.app.workflow.invoke(
            app_id=app_id,
            inputs=inputs,
            response_mode="blocking"
        )

        # Process workflow response if raw_data_output is enabled
        return dify_response["data"]["outputs"] if raw_data_output else dify_response
    
    def _send_callback_async(self, callback_url: str, secret_token: Optional[str], 
                            workflow_response: Dict[str, Any], app_id: str) -> None:
        """
        Sends an asynchronous callback with workflow results.
        
        Args:
            callback_url: The URL to send the callback to
            secret_token: Optional secret token for authentication
            workflow_response: The workflow response data to send
            app_id: The app ID that generated this response
        """
        try:
            # Run callback in background to avoid blocking the main response
            asyncio.create_task(self._send_callback(
                callback_url, secret_token, workflow_response, app_id
            ))
            logger.info("Scheduled callback to %s for app_id: %s", callback_url, app_id)
        except Exception as e:
            logger.error("Failed to schedule callback: %s", str(e))
    
    async def _send_callback(self, callback_url: str, secret_token: Optional[str],
                           workflow_response: Dict[str, Any], app_id: str) -> None:
        """
        Sends a callback HTTP request with workflow results.
        
        Args:
            callback_url: The URL to send the callback to
            secret_token: Optional secret token for authentication
            workflow_response: The workflow response data to send
            app_id: The app ID that generated this response
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Dify-Webhook-Plugin/1.0"
        }
        
        if secret_token:
            headers["Authorization"] = f"Bearer {secret_token}"
        
        callback_payload = {
            "app_id": app_id,
            "timestamp": workflow_response.get("created_at"),
            "workflow_run_id": workflow_response.get("workflow_run_id"),
            "data": workflow_response
        }
        
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        callback_url,
                        json=callback_payload,
                        headers=headers
                    )
                    
                    if response.status_code in [200, 201, 202, 204]:
                        logger.info(
                            "Callback sent successfully to %s (status: %d) for app_id: %s",
                            callback_url, response.status_code, app_id
                        )
                        return
                    else:
                        logger.warning(
                            "Callback failed with status %d: %s for app_id: %s", 
                            response.status_code, response.text, app_id
                        )
                        
            except httpx.TimeoutException:
                logger.error("Callback timeout (attempt %d/%d) to %s for app_id: %s", 
                           attempt + 1, max_retries, callback_url, app_id)
            except Exception as e:
                logger.error("Callback error (attempt %d/%d) to %s for app_id: %s: %s", 
                           attempt + 1, max_retries, callback_url, app_id, str(e))
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
        
        logger.error("All callback attempts failed for %s, app_id: %s", callback_url, app_id)
