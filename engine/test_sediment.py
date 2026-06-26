#!/usr/bin/env python3
"""Tests for the no-op (sediment) heuristic: python3 engine/test_sediment.py"""
from __future__ import annotations

import unittest

from contract_lib import is_low_signal_intent, is_sediment_intent


GLOSSARY_TERMS: set[tuple[str, ...]] = {
    ("cart",),
    ("line", "item"),
    ("ship", "window"),
}


class SedimentTests(unittest.TestCase):
    def test_sediment_restates_name(self) -> None:
        self.assertTrue(is_sediment_intent("get_user", "Gets the user."))
        self.assertTrue(is_sediment_intent("create_short_link", "Creates a short link."))
        self.assertTrue(is_sediment_intent("resolve", "Resolves it."))
        self.assertTrue(is_sediment_intent("count", "Returns the count."))
        self.assertTrue(is_sediment_intent("createShortLink", "creates a short link"))  # camelCase

    def test_real_intent_is_not_sediment(self) -> None:
        self.assertFalse(is_sediment_intent(
            "resolve", "Look up a short code and return the destination URL."))
        self.assertFalse(is_sediment_intent(
            "charge", "Dedupes by idempotency key so a retry never double-charges."))
        self.assertFalse(is_sediment_intent(
            "alpha", "Alpha now doubles x before returning it."))
        self.assertFalse(is_sediment_intent(
            "get_user", "Raises NotFound when the user is missing, rather than returning None."))

    def test_empty_intent_is_not_sediment(self) -> None:
        # missing @intent is the gate's job, not the sediment lint's
        self.assertFalse(is_sediment_intent("get_user", ""))
        self.assertFalse(is_sediment_intent("get_user", "   "))


class LowSignalTests(unittest.TestCase):
    def test_vague_intent_is_low_signal(self) -> None:
        self.assertTrue(is_low_signal_intent("handles the request", GLOSSARY_TERMS))
        self.assertTrue(is_low_signal_intent("processes the data", GLOSSARY_TERMS))
        self.assertTrue(is_low_signal_intent("does the thing", GLOSSARY_TERMS))

    def test_intent_with_glossary_term_is_not_low_signal(self) -> None:
        self.assertFalse(is_low_signal_intent(
            "Returns the Cart's LineItems sorted by ShipWindow", GLOSSARY_TERMS))
        self.assertFalse(is_low_signal_intent(
            "Ships the LineItem via the Cart", GLOSSARY_TERMS))

    def test_empty_intent_is_not_low_signal(self) -> None:
        # missing @intent is the gate's job, not the signal lint's
        self.assertFalse(is_low_signal_intent("", GLOSSARY_TERMS))
        self.assertFalse(is_low_signal_intent("   ", GLOSSARY_TERMS))

    def test_no_glossary_terms_means_everything_is_low_signal(self) -> None:
        self.assertTrue(is_low_signal_intent("Returns the Cart's LineItems sorted by ShipWindow", set()))


if __name__ == "__main__":
    unittest.main()
