"""Explicit dispatch infrastructure; importing starts no work or network calls."""
from .models import DeliveryAdapter, DeliveryEnvelope, DeliveryOutcome

__all__ = ['DeliveryAdapter','DeliveryEnvelope','DeliveryOutcome']
