import pytest
import json
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from endpoints.invoke_endpoint import WebhookEndpoint


class TestWebhookCallback:
    """Test cases for webhook callback functionality."""
    
    @pytest.fixture
    def webhook_endpoint(self):
        """Create a WebhookEndpoint instance for testing."""
        endpoint = WebhookEndpoint()
        endpoint.session = Mock()
        endpoint.session.app = Mock()
        endpoint.session.app.workflow = Mock()
        return endpoint

    @pytest.fixture
    def sample_workflow_response(self):
        """Sample workflow response for testing."""
        return {
            "workflow_run_id": "run-123",
            "created_at": "2024-01-01T12:00:00Z",
            "data": {
                "outputs": {
                    "result": "test output"
                }
            }
        }

    @pytest.mark.asyncio
    async def test_send_callback_success(self, webhook_endpoint, sample_workflow_response):
        """Test successful callback sending."""
        callback_url = "https://example.com/callback"
        secret_token = "test-token-123"
        app_id = "app-456"
        
        with patch('httpx.AsyncClient') as mock_client:
            # Setup mock response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_context
            mock_context.post.return_value = mock_response
            mock_client.return_value = mock_context
            
            # Call the method
            await webhook_endpoint._send_callback(
                callback_url, secret_token, sample_workflow_response, app_id
            )
            
            # Verify the request was made correctly
            mock_context.post.assert_called_once()
            call_args = mock_context.post.call_args
            
            assert call_args[1]['json']['app_id'] == app_id
            assert call_args[1]['json']['data'] == sample_workflow_response
            assert call_args[1]['headers']['Authorization'] == f"Bearer {secret_token}"
            assert call_args[1]['headers']['Content-Type'] == "application/json"

    @pytest.mark.asyncio 
    async def test_send_callback_without_token(self, webhook_endpoint, sample_workflow_response):
        """Test callback sending without secret token."""
        callback_url = "https://example.com/callback"
        app_id = "app-456"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_context
            mock_context.post.return_value = mock_response
            mock_client.return_value = mock_context
            
            await webhook_endpoint._send_callback(
                callback_url, None, sample_workflow_response, app_id
            )
            
            # Verify no Authorization header was set
            call_args = mock_context.post.call_args
            assert 'Authorization' not in call_args[1]['headers']

    @pytest.mark.asyncio
    async def test_send_callback_retry_on_error(self, webhook_endpoint, sample_workflow_response):
        """Test callback retry mechanism on HTTP errors."""
        callback_url = "https://example.com/callback"
        app_id = "app-456"
        
        with patch('httpx.AsyncClient') as mock_client:
            # First two attempts fail, third succeeds
            mock_responses = [
                Mock(status_code=500, text="Server Error"),
                Mock(status_code=502, text="Bad Gateway"), 
                Mock(status_code=200, text="OK")
            ]
            
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_context
            mock_context.post.side_effect = mock_responses
            mock_client.return_value = mock_context
            
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                await webhook_endpoint._send_callback(
                    callback_url, None, sample_workflow_response, app_id
                )
                
                # Should have made 3 attempts
                assert mock_context.post.call_count == 3
                # Should have slept twice (between retries)
                assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_send_callback_max_retries_exhausted(self, webhook_endpoint, sample_workflow_response):
        """Test callback when all retries are exhausted."""
        callback_url = "https://example.com/callback"
        app_id = "app-456"
        
        with patch('httpx.AsyncClient') as mock_client:
            # All attempts fail
            mock_response = Mock(status_code=500, text="Server Error")
            
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_context
            mock_context.post.return_value = mock_response
            mock_client.return_value = mock_context
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                await webhook_endpoint._send_callback(
                    callback_url, None, sample_workflow_response, app_id
                )
                
                # Should have made 3 attempts (max retries)
                assert mock_context.post.call_count == 3

    def test_send_callback_async_scheduling(self, webhook_endpoint, sample_workflow_response):
        """Test that callback is scheduled asynchronously."""
        callback_url = "https://example.com/callback"
        app_id = "app-456"
        
        with patch('asyncio.create_task') as mock_create_task:
            webhook_endpoint._send_callback_async(
                callback_url, None, sample_workflow_response, app_id
            )
            
            # Verify that asyncio.create_task was called
            mock_create_task.assert_called_once()

    def test_callback_payload_structure(self, webhook_endpoint, sample_workflow_response):
        """Test that callback payload has the correct structure."""
        callback_url = "https://example.com/callback"
        secret_token = "test-token"
        app_id = "app-456"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_context
            mock_context.post.return_value = mock_response
            mock_client.return_value = mock_context
            
            # Run the callback
            asyncio.run(webhook_endpoint._send_callback(
                callback_url, secret_token, sample_workflow_response, app_id
            ))
            
            # Check the payload structure
            call_args = mock_context.post.call_args
            payload = call_args[1]['json']
            
            assert 'app_id' in payload
            assert 'timestamp' in payload
            assert 'workflow_run_id' in payload
            assert 'data' in payload
            
            assert payload['app_id'] == app_id
            assert payload['data'] == sample_workflow_response
            assert payload['workflow_run_id'] == sample_workflow_response['workflow_run_id']
            assert payload['timestamp'] == sample_workflow_response['created_at']