import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("assistant_server", ROOT / "app" / "server.py")
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SERVER.initialize_database()

    def setUp(self):
        SERVER.CONFIG["use_semantic_search"] = False
        SERVER.CONFIG["use_llama_for_ambiguity"] = False

    def assert_location(self, question: str, expected: str):
        result = SERVER.answer_question(question, accessible=False)
        self.assertEqual("ok", result["status"], result)
        self.assertEqual(expected, result["matched_location"]["name"])

    def test_exact_room_and_spoken_variants(self):
        for question in (
            "Dove si trova l'aula 115?",
            "Come arrivo alla 115?",
            "Dov'è l'aula cento e quindici?",
            "Dov'è l'aula uno uno cinque?",
            "Dov'è l'aula 1.15?",
        ):
            with self.subTest(question=question):
                self.assert_location(question, "Laboratorio di robotica")

    def test_transcription_typos(self):
        self.assert_location("Dove si trova il laboratorio di roboticha?", "Laboratorio di robotica")
        self.assert_location("Dove si trova la segreteria didatica?", "Segreteria didattica")

    def test_generic_question_requests_clarification(self):
        result = SERVER.answer_question("Dove si trova un'aula?", accessible=False)
        self.assertEqual("clarification_required", result["status"])
        self.assertGreaterEqual(len(result["options"]), 2)

    def test_out_of_scope_question_is_not_answered(self):
        result = SERVER.answer_question("Che tempo farà domani?", accessible=False)
        self.assertEqual("not_found", result["status"])

    def test_semantic_fallback_selects_strong_lead(self):
        original_semantic = SERVER.semantic_scores
        original_llama = SERVER.llama_choose_location
        SERVER.CONFIG["use_semantic_search"] = True

        def fake_semantic(_question, locations):
            return {
                location["id"]: 0.92 if location["canonical_name"] == "Segreteria didattica" else 0.30
                for location in locations
            }

        try:
            SERVER.semantic_scores = fake_semantic
            SERVER.llama_choose_location = lambda _question, _locations: (None, "unavailable")
            self.assert_location("Dove devo consegnare la domanda d'iscrizione?", "Segreteria didattica")
        finally:
            SERVER.semantic_scores = original_semantic
            SERVER.llama_choose_location = original_llama

    def test_llama_can_only_select_a_candidate(self):
        original_llama = SERVER.llama_choose_location
        SERVER.CONFIG["use_llama_for_ambiguity"] = True
        secretary = next(item for item in SERVER.get_locations() if item["canonical_name"] == "Segreteria didattica")
        try:
            SERVER.llama_choose_location = lambda _question, _locations: (secretary["id"], "high")
            self.assert_location("Dove devo risolvere una pratica scolastica?", "Segreteria didattica")
        finally:
            SERVER.llama_choose_location = original_llama

    def test_semantic_tie_requires_clarification_before_llama(self):
        original_semantic = SERVER.semantic_scores
        original_llama = SERVER.llama_choose_location
        SERVER.CONFIG["use_semantic_search"] = True
        called = False

        def fake_semantic(_question, locations):
            scores = {location["id"]: 0.30 for location in locations}
            for location in locations:
                if location["canonical_name"] == "Biblioteca":
                    scores[location["id"]] = 0.62
                elif location["canonical_name"] == "Segreteria didattica":
                    scores[location["id"]] = 0.60
            return scores

        def fake_llama(_question, _locations):
            nonlocal called
            called = True
            return None, "low"

        try:
            SERVER.semantic_scores = fake_semantic
            SERVER.llama_choose_location = fake_llama
            result = SERVER.answer_question("Voglio leggere e chiedere un certificato", accessible=False)
            self.assertEqual("clarification_required", result["status"])
            self.assertEqual("semantic_tie", result["match_method"])
            self.assertFalse(called)
        finally:
            SERVER.semantic_scores = original_semantic
            SERVER.llama_choose_location = original_llama


if __name__ == "__main__":
    unittest.main()
