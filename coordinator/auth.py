import hmac
import hashlib
import secrets
from coordinator.config import settings

def generate_nonce() -> str:
    return secrets.token_hex(16)

def sign_nonce(nonce: str) -> str:
    """Signs a nonce using the cluster secret."""
    secret = settings.cluster_secret.encode('utf-8')
    return hmac.new(secret, nonce.encode('utf-8'), hashlib.sha256).hexdigest()

def verify_signature(nonce: str, signature: str) -> bool:
    """Verifies that the signature of a nonce is valid for the cluster secret."""
    expected_signature = sign_nonce(nonce)
    return hmac.compare_digest(expected_signature, signature)
