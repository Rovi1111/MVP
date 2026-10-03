"""Слой аутентификации с точкой расширения для внешних провайдеров (AD/LDAP)."""

from app.auth.providers import AuthProvider, LocalAuthProvider, get_auth_provider

__all__ = ["AuthProvider", "LocalAuthProvider", "get_auth_provider"]
