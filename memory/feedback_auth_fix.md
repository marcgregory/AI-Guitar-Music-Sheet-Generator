---
name: feedback_auth_fix
description: Fixed authentication backend issues with bcrypt and token creation
metadata:
  type: feedback
---

Fixed two issues in the backend authentication:
1. The passlib library had an issue with bcrypt version detection on Python 3.13, causing AttributeError: module 'bcrypt' has no attribute '__about__'. Fixed by modifying passlib/handlers/bcrypt.py to use _bcrypt.__version__ instead of _bcrypt.__about__.__version__.
2. The login endpoint was incorrectly calling create_access_token with a 'subject' keyword argument, but the function expects 'data' and 'expires_delta'. Fixed by changing the call to use data={"sub": user.username}.

**Why:** These issues prevented user registration and login from working, returning Internal Server Errors.

**How to apply:** Ensure the passlib patch is applied (or update to a compatible version) and the auth endpoint uses the correct keyword arguments for create_access_token.