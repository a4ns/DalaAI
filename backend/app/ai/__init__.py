"""Deterministic closure advice. Production decisions remain with a scoped master."""
from .models import (Assessment, ClosureInput, EvidenceContext, Gate, GateReport,
                     InputValidationError, Material, PhotoEvidence)
from .rules import assess_rules, evaluate_gates

__all__ = ['Assessment', 'ClosureInput', 'EvidenceContext', 'Gate', 'GateReport',
           'InputValidationError', 'Material', 'PhotoEvidence', 'assess_rules', 'evaluate_gates']
