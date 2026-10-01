"""Password policy (docs/PRODUCTION.md §1 ``PASSWORD_MIN_LENGTH``): length + trivial-password refusal."""

from __future__ import annotations

import secrets
import string

from app.config import settings
from app.errors import ApiError

#: Short embedded list of the most common passwords / patterns (lower-cased, compared after normalisation).
_COMMON = frozenset(
    {
        "password",
        "motdepasse",
        "azerty",
        "qwerty",
        "123456",
        "1234567890",
        "admin",
        "administrateur",
        "orbit",
        "orbitadmin",
        "orbit-admin",
        "welcome",
        "bienvenue",
        "letmein",
        "changeme",
        "soleil",
        "iloveyou",
        "jetaime",
        "football",
        "passw0rd",
        "p@ssw0rd",
        "secret",
        "loulou",
        "doudou",
        "chouchou",
        "marseille",
        "dragon",
        "monkey",
        "master",
        "sunshine",
        "princess",
        "abc123",
    }
)
_SEQUENCES = ("0123456789", "abcdefghijklmnopqrstuvwxyz", "azertyuiop", "qwertyuiop", "qsdfghjklm")


def password_problems(password: str, *, email: str | None = None, full_name: str | None = None) -> list[str]:
    """French reasons why ``password`` is refused (empty list = acceptable)."""
    problems: list[str] = []
    minimum = settings.password_min_length
    if len(password) < minimum:
        problems.append(f"au moins {minimum} caractères")
    if len(password) > 256:
        problems.append("au plus 256 caractères")
    lowered = password.lower()
    compact = "".join(ch for ch in lowered if ch.isalnum())
    stripped_digits = compact.rstrip(string.digits)
    if lowered in _COMMON or compact in _COMMON or stripped_digits in _COMMON:
        problems.append("mot de passe trop courant")
    if len(set(password)) <= 3:
        problems.append("trop peu de caractères différents")
    if any(compact and compact in seq for seq in _SEQUENCES) and len(compact) >= 6:
        problems.append("suite de caractères triviale")
    if email:
        local = email.lower().split("@")[0]
        if lowered == email.lower() or (len(local) >= 4 and local in lowered):
            problems.append("ne doit pas contenir l'adresse e-mail")
    if full_name:
        for part in full_name.lower().split():
            if len(part) >= 4 and part in lowered:
                problems.append("ne doit pas contenir votre nom")
                break
    return problems


def enforce_password_policy(password: str, *, email: str | None = None, full_name: str | None = None) -> None:
    """Raise 422 ``weak_password`` with a French explanation when the password is refused."""
    problems = password_problems(password, email=email, full_name=full_name)
    if problems:
        raise ApiError(422, "Mot de passe refusé : " + ", ".join(problems) + ".", code="weak_password")


def generate_password(length: int = 20) -> str:
    """Random password satisfying the policy (temporary / bootstrap passwords)."""
    alphabet = string.ascii_letters + string.digits + "-_.!@#%"
    while True:
        candidate = "".join(
            secrets.choice(alphabet) for _ in range(max(length, settings.password_min_length))
        )
        if not password_problems(candidate):
            return candidate
