from prcrew.diffs import ChangedFile, changed_ranges, line_is_changed

DIFF = """\
diff --git a/src/app.py b/src/app.py
index 111..222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,6 +10,8 @@ def handler():
 context
-old line
+new line one
+new line two
 context
@@ -40,2 +42,3 @@
 context
+tail line
 context
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1,3 +0,0 @@
-a
-b
-c
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
"""


def test_changed_ranges_new_side():
    files = changed_ranges(DIFF)
    by_path = {f.path: f.ranges for f in files}
    # deleted files have no new-side lines and are excluded entirely
    assert set(by_path) == {"src/app.py", "new.py"}
    assert by_path["src/app.py"] == [(10, 17), (42, 44)]
    assert by_path["new.py"] == [(1, 2)]


def test_line_is_changed():
    files = changed_ranges(DIFF)
    assert line_is_changed(files, "src/app.py", 11)
    assert not line_is_changed(files, "src/app.py", 30)
    assert not line_is_changed(files, "unknown.py", 1)


def test_zero_length_new_hunk_and_garbage_lines_ignored():
    assert changed_ranges("not a diff at all\n") == []


def test_added_content_line_that_looks_like_a_header_is_not_a_file_boundary():
    d = """diff --git a/real.py b/real.py
--- a/real.py
+++ b/real.py
@@ -1,2 +1,3 @@
 context
+++ b/injected.py
 more context
@@ -50,2 +52,3 @@
 context
+tail line
 context
"""
    files = changed_ranges(d)
    assert [f.path for f in files] == ["real.py"]
    assert line_is_changed(files, "real.py", 53)


def test_line_is_changed_scans_all_entries_for_a_path():
    files = [ChangedFile("x.py", [(1, 2)]), ChangedFile("x.py", [(100, 101)])]
    assert line_is_changed(files, "x.py", 101)
