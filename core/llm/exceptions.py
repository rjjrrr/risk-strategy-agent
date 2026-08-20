class LLMError(Exception):
    code="PROVIDER_ERROR"

class AuthError(LLMError): code="AUTH_ERROR"
class RateLimitError(LLMError): code="RATE_LIMIT"
class ProviderTimeout(LLMError): code="TIMEOUT"
class ConnectionError(LLMError): code="CONNECTION_ERROR"
class ModelNotFound(LLMError): code="MODEL_NOT_FOUND"
class InvalidResponse(LLMError): code="INVALID_RESPONSE"
class NoActiveBinding(LLMError): code="NO_ACTIVE_BINDING"
