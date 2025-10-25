# accounts/models.py
import hashlib
import os
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone

def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()

class EmailOTP(models.Model):
    PURPOSE_CHOICES = [
        ("signup", "Signup"),
        ("change_email", "Change Email"),
    ]

    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=64, db_index=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default="signup")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["email", "purpose", "is_used"]),
            models.Index(fields=["expires_at"]),
        ]

    @classmethod
    def create_for_email(cls, email: str, purpose: str = "signup", exp_minutes: int = None,
                         ip: str = None, user_agent: str = None, code: str | None = None) -> "EmailOTP":
        exp_minutes = exp_minutes or getattr(settings, "EMAIL_OTP_EXP_MINUTES", 15)
        code = code or f"{int.from_bytes(os.urandom(3), 'big') % 1_000_000:06d}"
        obj = cls.objects.create(
            email=email.lower().strip(),
            code_hash=_hash_code(code),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=exp_minutes),
            ip=ip,
            user_agent=user_agent[:4000] if user_agent else None,
        )
        obj._plain_code = code
        return obj

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def verify_code(self, code: str) -> bool:
        if self.is_used or self.is_expired():
            return False
        ok = _hash_code(code) == self.code_hash
        self.attempts = (self.attempts or 0) + 1
        if ok:
            self.is_used = True
        self.save(update_fields=["attempts", "is_used"])
        return ok
