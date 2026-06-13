"""Tests du référentiel taxonomie tags V3 + mapping déterministe (chantier E.1/E.2)."""
import unittest

import tags_taxonomy


class TaxonomyLoadTest(unittest.TestCase):
    def test_loads_active_v3_tags(self):
        tags = tags_taxonomy.load_taxonomy()
        self.assertGreaterEqual(len(tags), 90)  # ~97 tags actifs
        self.assertTrue(all(t.get("is_active") for t in tags))
        # chaque tag a au moins un code OU un nom
        self.assertTrue(all(t.get("tag_code") or t.get("name_v3") for t in tags))

    def test_categories_include_expected(self):
        cats = [c.lower() for c in tags_taxonomy.categories()]
        self.assertTrue(any("charging assistance" in c for c in cats))
        self.assertTrue(any("customer claim" in c for c in cats))

    def test_compact_for_prompt_is_compact(self):
        txt = tags_taxonomy.compact_for_prompt()
        # une ligne par catégorie, pas les 97 tags injectés
        self.assertLessEqual(len(txt.splitlines()), 12)
        self.assertIn("Charging assistance", txt)


class MapToTagTest(unittest.TestCase):
    def test_maps_within_subcategory_with_confidence(self):
        # On prend un vrai tag et on vérifie qu'un texte proche de son name_v3 le retrouve.
        tags = tags_taxonomy.load_taxonomy()
        sample = next(t for t in tags if t.get("subcategory") and t.get("name_v3"))
        res = tags_taxonomy.map_to_tag(sample["category"], sample["subcategory"], sample["name_v3"])
        self.assertEqual(res["tag_code"], sample["tag_code"])
        self.assertEqual(res["confidence"], "high")

    def test_unknown_category_is_low_confidence(self):
        res = tags_taxonomy.map_to_tag("Inexistant", None, "n'importe quoi")
        self.assertEqual(res["confidence"], "low")
        self.assertIsNone(res["tag_code"])

    def test_no_category_returns_low(self):
        res = tags_taxonomy.map_to_tag(None, None, "texte")
        self.assertEqual(res["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
