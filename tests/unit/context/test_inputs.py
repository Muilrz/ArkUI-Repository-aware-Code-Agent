from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from arkui_agent.context import (
    Change, ChangeKind, DiffLine, FileChange, Hint, HintKind, Hunk, InputError,
    LineKind, LineRange, Origin, ParseStatus, Provenance, Revision, RevisionStatus,
    Side, Task, TextSpan, dumps, from_dict, loads, parse_task, to_dict,
)


SOURCE = Provenance("caller:unit", Origin.EXPLICIT)


class TaskContractTests(unittest.TestCase):
    def test_chinese_template_retains_exact_text_and_extraction_offsets(self) -> None:
        raw = " 给 MenuItem 的 selected 属性补 UT。\n"
        result = parse_task(raw, repository="repo", target_revision="rev", source_id="request")
        self.assertEqual(result.status, ParseStatus.OK)
        self.assertEqual(result.value.text, raw)
        self.assertEqual([(h.kind.value, h.value) for h in result.value.hints], [
            ("component", "MenuItem"), ("property", "selected"), ("action", "补"), ("test_intent", "UT"),
        ])
        for hint in result.value.hints:
            self.assertEqual(hint.resolution, "unresolved")
            self.assertEqual(hint.provenance.origin, Origin.EXTRACTED)
            self.assertEqual(hint.provenance.rule, "task-zh-ut-v1")
            span = hint.provenance.span
            self.assertEqual(raw[span.start:span.end], hint.value)
        self.assertEqual(loads(dumps(result)), result)

    def test_labels_unknown_component_overloads_and_explicit_provenance(self) -> None:
        raw = "调查 [component: FutureWidget] [symbol: A::Set(int)] [symbol:A::Set(float)] [action:检查] [test_intent:UT]"
        explicit = Hint(HintKind.PROPERTY, "selected", SOURCE)
        result = parse_task(raw, repository="repo", target_revision="rev", source_id="request", hints=(explicit,))
        self.assertEqual(result.value.hints[0], explicit)
        self.assertEqual([h.value for h in result.value.hints[1:]],
                         ["FutureWidget", "A::Set(int)", "A::Set(float)", "检查", "UT"])
        self.assertTrue(all(h.resolution == "unresolved" for h in result.value.hints))
        self.assertEqual(parse_task(raw, repository="repo", target_revision="rev", source_id="request", hints=(explicit,)), result)
        self.assertEqual(loads(dumps(result.value)), result.value)

    def test_unknown_natural_language_is_preserved_without_guessed_facts(self) -> None:
        for raw in ("检查陌生组件为什么慢 🤔", "[unknown:Foo]", "Fix Button layout", "给 Foo 的 bar 属性做任何事情"):
            with self.subTest(raw=raw):
                result = parse_task(raw, repository="repo", target_revision="rev", source_id="request")
                self.assertEqual(result.value.text, raw)
                self.assertEqual(result.value.hints, ())

    def test_missing_revision_is_explicit_and_never_defaulted(self) -> None:
        result = parse_task("分析", repository="repo", target_revision=None, source_id="request")
        self.assertEqual(result.status, ParseStatus.UNRESOLVED)
        self.assertIsNone(result.value.target_revision.value)
        self.assertEqual(result.value.target_revision.status, RevisionStatus.UNRESOLVED)
        self.assertEqual([d.field for d in result.diagnostics], ["target_revision"])
        self.assertEqual(loads(dumps(result)), result)
        self.assertEqual(Revision("HEAD").status, RevisionStatus.DECLARED)
        with self.assertRaises(TypeError):
            parse_task("分析", repository="repo", source_id="request")
        for revision in ("", " ", 42):
            self.assertEqual(parse_task("分析", repository="repo", target_revision=revision,
                                        source_id="request").status, ParseStatus.INVALID)

    def test_structured_task_immutable_and_hint_sources_validated(self) -> None:
        task = Task("repo", Revision(None), "", (Hint(HintKind.SYMBOL, "F(int)", SOURCE),), SOURCE)
        self.assertEqual(loads(dumps(task)), task)
        with self.assertRaises(FrozenInstanceError):
            task.text = "changed"
        with self.assertRaises(InputError):
            Task("repo", Revision("r"), "foo", (
                Hint(HintKind.SYMBOL, "bar", Provenance("request", Origin.EXTRACTED, TextSpan(0, 3), "v1")),
            ), Provenance("request", Origin.INPUT))
        for raw in ("", "  ", "[component:]", "[symbol: ]"):
            self.assertEqual(parse_task(raw, repository="repo", target_revision="r", source_id="s").status,
                             ParseStatus.INVALID)


class RangeAndStructuredChangeTests(unittest.TestCase):
    def test_range_is_one_based_half_open_with_explicit_side(self) -> None:
        self.assertEqual(LineRange(Side.OLD, 1, 1).count, 0)
        self.assertEqual(LineRange(Side.NEW, 2, 5).count, 3)
        for args in ((Side.OLD, 0, 1), (Side.NEW, 4, 3), (Side.OLD, True, 2),
                     (Side.OLD, 1.0, 2), ("old", 1, 2), (Side.OLD, 1, 2, 0, 1),
                     (Side.OLD, 1, 2, 1, 2)):
            with self.subTest(args=args), self.assertRaises(InputError):
                LineRange(*args)

    def test_structured_change_and_hunk_validation(self) -> None:
        hunk = Hunk(LineRange(Side.OLD, 1, 1), LineRange(Side.NEW, 1, 2), "",
                    (DiffLine(LineKind.ADD, "new"),), SOURCE)
        file = FileChange(None, "src/a.cpp", ChangeKind.ADD, (hunk,), (), SOURCE)
        change = Change("repo", Revision(None), Revision("head"), (file,), None, SOURCE)
        self.assertEqual(loads(dumps(change)), change)
        for mutate in (
            lambda: replace(hunk, old_range=LineRange(Side.NEW, 1, 1)),
            lambda: replace(hunk, new_range=LineRange(Side.NEW, 1, 3)),
            lambda: replace(file, old_path="old.cpp"),
            lambda: replace(file, hunks=(replace(hunk, old_range=LineRange(Side.OLD, 4, 4)),)),
            lambda: replace(change, files=(file, file)),
        ):
            with self.assertRaises(InputError):
                mutate()


class SerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.value = parse_task("中文", repository="repo", target_revision="r", source_id="s").value

    def test_canonical_unicode_and_stable_round_trip(self) -> None:
        encoded = dumps(self.value)
        self.assertIn("中文", encoded)
        self.assertEqual(dumps(loads(encoded)), encoded)
        self.assertEqual(from_dict(to_dict(self.value)), self.value)

    def test_strict_schema_scalars_unknown_fields_and_versions(self) -> None:
        for version in (2, True, "1", None):
            document = to_dict(self.value)
            document["schema_version"] = version
            with self.assertRaises(InputError):
                from_dict(document)
        for field, value in (("extra", 1), ("hints", {}), ("text", 1), ("$type", "SymbolIdentity")):
            document = to_dict(self.value)
            document["payload"][field] = value
            with self.assertRaises(InputError):
                from_dict(document)
        document = to_dict(self.value)
        del document["payload"]["target_revision"]
        with self.assertRaises(InputError):
            from_dict(document)
        document = to_dict(self.value)
        document["payload"]["provenance"]["origin"] = "repository_fact"
        with self.assertRaises(InputError):
            from_dict(document)
        for raw in ('{"schema_version":1,"schema_version":1}', "{", "null", "[]"):
            with self.assertRaises(InputError):
                loads(raw)

    def test_wire_ranges_and_provenance_are_revalidated(self) -> None:
        result = parse_task("[symbol:Foo]", repository="repo", target_revision="r", source_id="s")
        for mutate in (
            lambda payload: payload.update(raw_input="different"),
            lambda payload: payload["value"]["hints"][0]["provenance"]["span"].update(start=True),
            lambda payload: payload["value"]["hints"][0].update(value="Bar"),
            lambda payload: payload["value"]["provenance"].update(source_id="other"),
        ):
            document = to_dict(result)
            mutate(document["payload"])
            with self.assertRaises(InputError):
                from_dict(document)

    def test_deserialization_revalidates_missing_revision_result(self) -> None:
        result = parse_task("x", repository="repo", target_revision=None, source_id="s")
        document = to_dict(result)
        document["payload"]["status"] = "ok"
        with self.assertRaises(InputError):
            from_dict(document)


if __name__ == "__main__":
    unittest.main()
