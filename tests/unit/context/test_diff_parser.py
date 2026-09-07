from __future__ import annotations

import unittest

from arkui_agent.context import (
    ChangeKind, LineKind, ParseStatus, RevisionStatus, Side, dumps, loads, parse_unified_diff,
)


def parse(raw: str, base: str | None = "base", head: str | None = "head"):
    return parse_unified_diff(raw, repository="repo", base_revision=base,
                              head_revision=head, source_id="patch:unit")


MODIFY = "--- src/a.cpp\n+++ src/a.cpp\n@@ -1 +1 @@ f()\n-old\n+new\n"


class UnifiedDiffTests(unittest.TestCase):
    def test_modify_and_serialization_preserve_body_section_and_provenance(self) -> None:
        result = parse(MODIFY)
        self.assertEqual(result.status, ParseStatus.OK)
        file = result.value.files[0]
        self.assertEqual(file.kind, ChangeKind.MODIFY)
        hunk = file.hunks[0]
        self.assertEqual(hunk.section, " f()")
        self.assertEqual([(line.kind, line.text) for line in hunk.lines],
                         [(LineKind.DELETE, "old"), (LineKind.ADD, "new")])
        self.assertEqual((hunk.old_range.side, hunk.new_range.side), (Side.OLD, Side.NEW))
        for item, prefix in ((file, "---"), (hunk, "@@")):
            span = item.provenance.span
            self.assertTrue(MODIFY[span.start:span.end].startswith(prefix))
            self.assertEqual(item.provenance.rule, "unified-diff-v1")
        self.assertEqual(result.value.raw_diff, MODIFY)
        self.assertEqual(loads(dumps(result)), result)
        self.assertEqual(loads(dumps(result.value)), result.value)

    def test_zero_length_insertion_and_deletion_normalize_gap_after_N(self) -> None:
        for header, body, expected in (
            ("-0,0 +1,2", "+a\n+b\n", (1, 1, 1, 3)),
            ("-3,0 +4", "+a\n", (4, 4, 4, 5)),
            ("-1,2 +0,0", "-a\n-b\n", (1, 3, 1, 1)),
            ("-4 +3,0", "-a\n", (4, 5, 4, 4)),
        ):
            with self.subTest(header=header):
                result = parse("--- a.cpp\n+++ a.cpp\n@@ " + header + " @@\n" + body)
                self.assertEqual(result.status, ParseStatus.OK)
                h = result.value.files[0].hunks[0]
                self.assertEqual((h.old_range.start_line, h.old_range.end_line,
                                  h.new_range.start_line, h.new_range.end_line), expected)
                self.assertEqual((h.old_range.start_column, h.old_range.end_column,
                                  h.new_range.start_column, h.new_range.end_column), (1, 1, 1, 1))

    def test_multi_file_multi_hunk_add_delete_rename_and_modes(self) -> None:
        raw = (
            "diff --git a/a.cpp b/a.cpp\nindex abc..def 100644\n"
            "--- a/a.cpp\n+++ b/a.cpp\n@@ -1 +1 @@\n-a\n+b\n"
            "@@ -5,2 +5,2 @@\n context\n-c\n+d\n"
            "diff --git a/new.cpp b/new.cpp\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/new.cpp\n@@ -0,0 +1 @@\n+new\n"
            "diff --git a/old.cpp b/old.cpp\ndeleted file mode 100644\n"
            "--- a/old.cpp\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
            "diff --git a/from.cpp b/to.cpp\nsimilarity index 100%\nrename from from.cpp\nrename to to.cpp\n"
            "diff --git a/mode.cpp b/mode.cpp\nold mode 100644\nnew mode 100755\n"
        )
        result = parse(raw)
        self.assertEqual(result.status, ParseStatus.OK, result.diagnostics)
        self.assertEqual([f.kind for f in result.value.files], [ChangeKind.MODIFY, ChangeKind.ADD,
                         ChangeKind.DELETE, ChangeKind.RENAME, ChangeKind.MODIFY])
        self.assertEqual([len(f.hunks) for f in result.value.files], [2, 1, 1, 0, 0])
        self.assertIsNone(result.value.files[1].old_path)
        self.assertIsNone(result.value.files[2].new_path)
        self.assertEqual(loads(dumps(result)), result)

    def test_rename_with_edits_empty_added_file_and_traditional_paths(self) -> None:
        raw = ("diff --git a/from.cpp b/to.cpp\nsimilarity index 50%\n"
               "rename from from.cpp\nrename to to.cpp\n--- a/from.cpp\n+++ b/to.cpp\n"
               "@@ -1 +1 @@\n-a\n+b\n")
        self.assertEqual(parse(raw).value.files[0].kind, ChangeKind.RENAME)
        self.assertEqual(parse("diff --git a/new b/new\nnew file mode 100644\n").value.files[0].kind,
                         ChangeKind.ADD)
        raw = "--- dir/原 文件.cpp\told timestamp\n+++ dir/原 文件.cpp\tnew timestamp\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertEqual(parse(raw).value.files[0].old_path, "dir/原 文件.cpp")

    def test_crlf_unicode_no_newline_markers_and_final_unterminated_diff_line(self) -> None:
        raw = "--- a\n+++ a\n@@ -1 +1 @@\n-旧\n\\ No newline at end of file\n+新\n\\ No newline at end of file"
        for text in (raw, raw.replace("\n", "\r\n")):
            result = parse(text)
            self.assertEqual(result.status, ParseStatus.OK)
            self.assertEqual(result.raw_input, text)
            self.assertEqual(len(result.value.files[0].hunks[0].lines), 4)
            self.assertEqual(loads(dumps(result)), result)

    def test_diff_syntax_inside_source_content_is_not_metadata(self) -> None:
        raw = "--- a\n+++ a\n@@ -1,2 +1,2 @@\n--- old text\n-GIT binary patch\n+++ new text\n+diff --cc source\n"
        result = parse(raw)
        self.assertEqual(result.status, ParseStatus.OK)
        self.assertEqual([line.text for line in result.value.files[0].hunks[0].lines],
                         ["-- old text", "GIT binary patch", "++ new text", "diff --cc source"])

    def test_absent_revisions_never_select_head_or_worktree(self) -> None:
        for base, head, fields in ((None, "h", ["base_revision"]), ("b", None, ["head_revision"]),
                                  (None, None, ["base_revision", "head_revision"])):
            result = parse(MODIFY, base, head)
            self.assertEqual(result.status, ParseStatus.UNRESOLVED)
            self.assertEqual([d.field for d in result.diagnostics], fields)
            self.assertEqual(result.value.base_revision.value, base)
            self.assertEqual(result.value.head_revision.value, head)
            self.assertEqual(loads(dumps(result)), result)
        self.assertEqual(parse(MODIFY).value.base_revision.status, RevisionStatus.DECLARED)
        self.assertEqual(parse(MODIFY, " ").status, ParseStatus.INVALID)

    def test_binary_combined_and_extensions_are_atomic_unsupported(self) -> None:
        for raw in (
            "diff --git a/a b/a\nGIT binary patch\nliteral 3\nabc\n",
            "Binary files a/a and b/a differ\n",
            "diff --cc a.cpp\nindex abc,def..123\n@@@ -1 -1 +1 @@@\n",
            "diff --combined a.cpp\n",
            'diff --git "a/a b" "b/a b"\n',
            "diff --git a/a b/b\ncopy from a\ncopy to b\n",
        ):
            for prefix in ("", MODIFY):
                with self.subTest(raw=raw, prefix=bool(prefix)):
                    result = parse(prefix + raw)
                    self.assertEqual(result.status, ParseStatus.UNSUPPORTED)
                    self.assertIsNone(result.value)
                    self.assertEqual(result.raw_input, prefix + raw)
                    self.assertTrue(result.diagnostics)
                    self.assertEqual(loads(dumps(result)), result)

    def test_path_escape_and_invalid_ranges_rejected(self) -> None:
        for path in ("../a", "src/../a", "/absolute", "C:/a", "a\\b", "./a", "a//b", "a\x00b"):
            result = parse(f"--- {path}\n+++ {path}\n@@ -1 +1 @@\n-a\n+b\n")
            self.assertEqual(result.status, ParseStatus.INVALID, path)
        for raw in (
            "", "--- a\n", "--- a\n+++ a\n", MODIFY + "+extra\n",
            MODIFY.replace("-1 +1", "-0 +1"), MODIFY.replace("-1 +1", "-1,2 +1"),
            MODIFY.replace("-1 +1", "--1 +1"), MODIFY.replace("-1 +1", "-1,-2 +1"),
            "--- a\n+++ a\n@@ -0,0 +0,0 @@\n",
            MODIFY + "@@ -1 +1 @@\n-x\n+y\n",
            MODIFY + MODIFY,
            "diff --git a/../a b/a\nnew file mode 100644\n",
            "diff --git a/a b/a\n--- a/other\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n",
            "diff --git a/a b/b\nrename from a\n",
            "diff --git a/a b/a\nnew file mode 100644\nnew file mode 100755\n",
            "diff --git a/a b/a\nold mode 100644\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n",
            MODIFY.replace("\n", "\r"),
            "--- /dev/null\n+++ a\n@@ -2,0 +1 @@\n+a\n",
            "--- a\n+++ /dev/null\n@@ -1 +2,0 @@\n-a\n",
            "--- a\n+++ a\n@@ -1 +1 @@\n\\ No newline at end of file\n-a\n+b\n",
            "--- a\n+++ a\n@@ -1,2 +1 @@\n-a\n\\ No newline at end of file\n-b\n+c\n",
            "--- a\n+++ a\n@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n@@ -4 +4 @@\n-c\n+d\n",
        ):
            with self.subTest(raw=raw):
                result = parse(raw)
                self.assertEqual(result.status, ParseStatus.INVALID, result.diagnostics)
                self.assertIsNone(result.value)
                self.assertEqual(loads(dumps(result)), result)


if __name__ == "__main__":
    unittest.main()
