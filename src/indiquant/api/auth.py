import hashlib
import hmac
from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

# In a real app, this would be in a DB/Env. We simulate one valid token.
# Let's say valid token is "tapetide-secret-token"
VALID_TOKENS_HASHES = {
    # SHA256 of "tapetide-secret-token"
    "d92729e25246d1ff7564af74b68d72a9aa387876c6db321ee5bcaaa77b077d6b": "user_1"
}

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    # Hash the provided token
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    if token_hash not in VALID_TOKENS_HASHES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return VALID_TOKENS_HASHES[token_hash]
