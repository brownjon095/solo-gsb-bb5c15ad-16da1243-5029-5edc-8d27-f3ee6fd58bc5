"""Unit tests for the pure three-way merge engine (no dependencies)."""

import unittest

from app.merge import PLACEHOLDER_KEY, merge3, parse_pointer


class MergeEngineTest(unittest.TestCase):
    def test_single_side_change_is_adopted(self):
        base = {"a": 1, "b": 2}
        left = {"a": 10, "b": 2}
        right = {"a": 1, "b": 20}
        doc, conflicts = merge3(base, left, right)
        self.assertEqual(doc, {"a": 10, "b": 20})
        self.assertEqual(conflicts, [])

    def test_both_sides_same_change_merges(self):
        doc, conflicts = merge3({"a": 1}, {"a": 5}, {"a": 5})
        self.assertEqual(doc, {"a": 5})
        self.assertEqual(conflicts, [])

    def test_scalar_conflict_keeps_placeholder_and_candidates(self):
        doc, conflicts = merge3({"a": 1}, {"a": 2}, {"a": 3})
        self.assertEqual(doc, {"a": {PLACEHOLDER_KEY: "/a"}})
        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c["pointer"], "/a")
        self.assertEqual((c["base"], c["left"], c["right"]), (1, 2, 3))
        self.assertEqual(c["missing"], [])

    def test_nested_recursion_by_json_pointer(self):
        base = {"svc": {"replicas": 1, "image": "v1"}}
        left = {"svc": {"replicas": 3, "image": "v1"}}
        right = {"svc": {"replicas": 1, "image": "v2"}}
        doc, conflicts = merge3(base, left, right)
        self.assertEqual(doc, {"svc": {"replicas": 3, "image": "v2"}})
        self.assertEqual(conflicts, [])

    def test_nested_conflict_pointer(self):
        base = {"svc": {"db": {"host": "a"}}}
        left = {"svc": {"db": {"host": "b"}}}
        right = {"svc": {"db": {"host": "c"}}}
        doc, conflicts = merge3(base, left, right)
        self.assertEqual(conflicts[0]["pointer"], "/svc/db/host")
        self.assertEqual(doc["svc"]["db"]["host"], {PLACEHOLDER_KEY: "/svc/db/host"})

    def test_delete_vs_unchanged_deletes(self):
        doc, conflicts = merge3({"a": 1, "b": 2}, {"b": 2}, {"a": 1, "b": 2})
        self.assertEqual(doc, {"b": 2})
        self.assertEqual(conflicts, [])

    def test_delete_vs_modify_conflicts(self):
        doc, conflicts = merge3({"a": 1}, {}, {"a": 9})
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["missing"], ["left"])
        self.assertEqual(conflicts[0]["right"], 9)

    def test_both_added_same_key_different_value_conflicts(self):
        doc, conflicts = merge3({}, {"x": 1}, {"x": 2})
        self.assertEqual(conflicts[0]["missing"], ["base"])

    def test_both_added_objects_merge_recursively(self):
        doc, conflicts = merge3({}, {"o": {"a": 1}}, {"o": {"b": 2}})
        self.assertEqual(doc, {"o": {"a": 1, "b": 2}})
        self.assertEqual(conflicts, [])

    def test_arrays_are_scalar_conflicts(self):
        doc, conflicts = merge3({"l": [1]}, {"l": [1, 2]}, {"l": [1, 3]})
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["left"], [1, 2])
        self.assertEqual(conflicts[0]["right"], [1, 3])

    def test_bool_and_number_are_different_changes(self):
        # base flag=false, left=1, right=true: two *different* changes, not
        # an identical one — Python's ``==`` would equate 1 and True.
        doc, conflicts = merge3({"flag": False}, {"flag": 1}, {"flag": True})
        self.assertEqual(doc, {"flag": {PLACEHOLDER_KEY: "/flag"}})
        self.assertEqual(len(conflicts), 1)
        conflict = conflicts[0]
        self.assertEqual(conflict["pointer"], "/flag")
        self.assertIs(conflict["base"], False)
        self.assertEqual(conflict["left"], 1)
        self.assertNotIsInstance(conflict["left"], bool)
        self.assertIs(conflict["right"], True)
        self.assertEqual(conflict["missing"], [])

    def test_int_and_float_are_different_changes(self):
        doc, conflicts = merge3({"n": 0}, {"n": 1}, {"n": 1.0})
        self.assertEqual(doc, {"n": {PLACEHOLDER_KEY: "/n"}})
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["pointer"], "/n")
        self.assertIsInstance(conflicts[0]["left"], int)
        self.assertIsInstance(conflicts[0]["right"], float)

    def test_type_distinction_recurses_into_objects(self):
        base = {"db": {"ssl": False}}
        left = {"db": {"ssl": 1}}
        right = {"db": {"ssl": True}}
        doc, conflicts = merge3(base, left, right)
        self.assertEqual(doc, {"db": {"ssl": {PLACEHOLDER_KEY: "/db/ssl"}}})
        self.assertEqual([c["pointer"] for c in conflicts], ["/db/ssl"])

    def test_type_distinction_recurses_into_arrays(self):
        doc, conflicts = merge3({"l": [1]}, {"l": [True]}, {"l": [1.0]})
        self.assertEqual(doc, {"l": {PLACEHOLDER_KEY: "/l"}})
        self.assertEqual([c["pointer"] for c in conflicts], ["/l"])
        self.assertEqual(conflicts[0]["left"], [True])
        self.assertEqual(conflicts[0]["right"], [1.0])

    def test_identical_bool_change_still_auto_merges(self):
        doc, conflicts = merge3({"flag": False}, {"flag": True}, {"flag": True})
        self.assertEqual(doc, {"flag": True})
        self.assertEqual(conflicts, [])

    def test_identical_float_change_still_auto_merges(self):
        doc, conflicts = merge3({"n": 0}, {"n": 1.0}, {"n": 1.0})
        self.assertEqual(doc, {"n": 1.0})
        self.assertEqual(conflicts, [])

    def test_single_side_type_only_change_is_adopted(self):
        # left only retypes 1 -> True; right kept base: the change is seen
        # (loose == would call left unchanged and silently keep 1).
        doc, conflicts = merge3({"n": 1}, {"n": True}, {"n": 1})
        self.assertEqual(doc, {"n": True})
        self.assertEqual(conflicts, [])

    def test_explicit_null_vs_delete_still_conflicts(self):
        doc, conflicts = merge3({"a": 1}, {"a": None}, {})
        self.assertEqual(len(conflicts), 1)
        self.assertIsNone(conflicts[0]["left"])
        self.assertEqual(conflicts[0]["missing"], ["right"])

    def test_single_side_explicit_null_add_is_adopted(self):
        doc, conflicts = merge3({}, {"a": None}, {})
        self.assertEqual(doc, {"a": None})
        self.assertEqual(conflicts, [])

    def test_pointer_escaping(self):
        self.assertEqual(parse_pointer("/a~1b/c~0d"), ["a/b", "c~d"])
        self.assertEqual(parse_pointer(""), [])


if __name__ == "__main__":
    unittest.main()
