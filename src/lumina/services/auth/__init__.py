"""Auth Service — token issuance, user management, invite/onboarding.

Owns:
  - User registration and login (all three authority tracks)
  - Token refresh, revocation, password reset
  - Invite/onboarding flow
  - User CRUD (role updates, deactivation)

See docs/7-concepts/microservice-boundaries.md § Auth Service.
"""
