/**
 * Whether sign-in with Cytonn SSO exists. It does not: api/sso.py is a stub that raises, and nothing in this app
 * signs anyone in or protects any page. The landing page reads this one constant; flip it only when the sign-in
 * itself has been built (see BLOCKED_REASON and UNBLOCK in api/sso.py).
 */
export const SSO_ENABLED = false;
