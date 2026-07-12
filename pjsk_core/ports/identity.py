"""Identity resolver port — maps platform identities to internal QQ numbers."""

from typing import Protocol

from pjsk_core.domain.users import QqNumber


class IdentityResolver(Protocol):
    """Resolve external platform identity (e.g. Official QQ OpenID)
    to an internal QQ number via binding table lookup."""

    async def resolve(
        self, platform: str, external_id: str
    ) -> QqNumber | None: ...
