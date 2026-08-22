import logging
from urllib.parse import parse_qs
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken, TokenError

User = get_user_model()
logger = logging.getLogger(__name__)


@database_sync_to_async
def get_user_from_token(token_string):
    """
    Decodes SimpleJWT access token and resolves authenticated user.
    """
    try:
        access_token = AccessToken(token_string)
        user_id = access_token.get('user_id')
        if user_id:
            user = User.objects.get(id=user_id, is_active=True)
            return user
    except (TokenError, User.DoesNotExist, Exception) as e:
        logger.debug(f"JWT WebSocket authentication failed: {str(e)}")
    return AnonymousUser()


class JWTAuthMiddleware:
    """
    Channels ASGI middleware extracting JWT access token from query string (?token=...)
    or Authorization header, populating scope['user'].
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode('utf-8')
        query_params = parse_qs(query_string)
        token = None

        if 'token' in query_params:
            token = query_params['token'][0]
        else:
            # Fallback to Authorization header
            headers = dict(scope.get('headers', []))
            if b'authorization' in headers:
                auth_header = headers[b'authorization'].decode('utf-8')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]

        if token:
            scope['user'] = await get_user_from_token(token)
        else:
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)
