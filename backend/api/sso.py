"""Sign-in with Cytonn SSO: a stub.  Nothing here signs anyone in.

The review API has no authentication at all, and this module does not change that: there
is no session, cookie, token or middleware, and no route calls it.  It exists so the one
place sign-in will be written is named, with what blocks it and what would unblock it.
Which identity provider Cytonn uses is not known, so none is assumed and no SSO library
is a dependency.
"""

BLOCKED_REASON = (
    "Cytonn has not yet provided the identity provider type, client ID, an approved redirect address, "
    "or the list of allowed users."
)
UNBLOCK = (
    "Get those four items from Cytonn IT, then implement begin_sso_login() and the callback, and read "
    "the signed-in name for the greeting."
)


def begin_sso_login():
    # TODO: needs the four items in UNBLOCK before any of this can be written without guessing.
    raise NotImplementedError(BLOCKED_REASON)
