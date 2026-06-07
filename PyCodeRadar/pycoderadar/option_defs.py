# -*- coding: utf-8 -*-
"""
GUI option metadata: tuples of (attr_name, label, tooltip).

Driving the option-panel construction from data keeps MainWindow thin and
makes it trivial to add or remove a checkbox without touching layout code.
"""

TRACK_OPTIONS: list = [
    ("include_calls",           "Call graph",
     "List functions called from each function/method."),
    ("track_line_counts",       "Line counts",
     "Show how many lines each function/class spans."),
    ("track_complexity",        "Cyclomatic complexity",
     "Estimate branching complexity (CC) for each function."),
    ("track_return_types",      "Return types",
     "Include annotated return types in signatures."),
    ("track_annotations",       "Arg type annotations",
     "Include per-argument type annotations in signatures."),
    ("track_exceptions",        "Exceptions raised",
     "List exception types raised by each function."),
    ("track_import_categories", "Group imports (stdlib / third-party / local)",
     "Split the import list into three labelled groups."),
    ("track_todos",             "TODO / FIXME / XXX comments",
     "Scan source comments for TODO/FIXME/XXX/HACK/NOTE tags."),
    ("track_wrappers",          "Wrapper functions / methods",
     "Identify thin passthrough functions that mainly delegate to one other call.\n"
     "Shown as  ↪ target()  after the signature."),
]

ANTIPATTERN_OPTIONS: list = [
    ("detect_wildcard",          "Wildcard imports (`from x import *`)",
     "Flag `from x import *` statements."),
    ("detect_duplicate_imports", "Duplicate imports",
     "Flag names imported more than once."),
    ("detect_unused_imports",    "Unused imports",
     "Flag imports whose local name is never referenced."),
    ("detect_mutable_defaults",  "Mutable default arguments",
     "Flag `def f(x=[])` / `def f(x={})` patterns."),
    ("detect_bare_except",       "Bare `except:` clauses",
     "Flag `except:` without an exception type."),
    ("detect_exec_eval",         "`exec()` / `eval()` usage",
     "Flag direct use of exec() or eval()."),
    ("detect_long_functions",    "Long functions",
     "Flag functions exceeding the line-count threshold."),
    ("detect_too_many_args",     "Too many arguments",
     "Flag functions exceeding the argument-count threshold."),
    ("detect_god_classes",       "God classes",
     "Flag classes exceeding the method-count threshold."),
    ("detect_print",             "`print()` leftovers",
     "Flag top-level print() calls as possible debug output."),
]

LEGACY_OPTIONS: list = [
    ("detect_percent_format",  "%-style string formatting",
     'Flag `"hello %s" % name` — prefer f-strings or .format().\n'
     "Only triggers when the left operand is a string literal."),
    ("detect_super_args",      "super() with explicit args",
     "Flag `super(ClassName, self)` — use bare `super()` in Python 3."),
    ("detect_type_comments",   "PEP 484 type comments  (# type: int)",
     "Flag inline `# type:` comments — use inline annotations instead.\n"
     "`# type: ignore` is intentionally excluded."),
]

# Mypy individual strictness flags shown under "MYPY — strictness & filters".
MYPY_STRICT_FLAGS: list = [
    ("mypy_disallow_untyped_defs",       "--disallow-untyped-defs",
     "Require type annotations on every function definition."),
    ("mypy_disallow_incomplete_defs",    "--disallow-incomplete-defs",
     "Reject partially annotated functions (some args typed, some not)."),
    ("mypy_check_untyped_defs",          "--check-untyped-defs",
     "Type-check the bodies of functions even when they lack annotations."),
    ("mypy_disallow_any_generics",       "--disallow-any-generics",
     "Disallow generic types without explicit type parameters (e.g. List[Any])."),
    ("mypy_warn_return_any",             "--warn-return-any",
     "Warn when a typed function returns a value typed as Any."),
    ("mypy_warn_unused_ignores",         "--warn-unused-ignores",
     "Warn when a # type: ignore comment is no longer needed."),
    ("mypy_no_implicit_optional",        "--no-implicit-optional",
     "Do not treat default=None as an implicit Optional[T].\n"
     "(Enabled by default here — this is almost always what you want.)"),
    ("mypy_strict_equality",             "--strict-equality",
     "Prohibit equality comparisons that can never be True."),
    ("mypy_disallow_untyped_decorators", "--disallow-untyped-decorators",
     "Reject decorators that do not have complete type annotations."),
]
