# -*- coding: utf-8 -*-
"""Static contract for tests/run_all.py suite evidence metadata.

Run: python tests/unit/core/runtime/test_runner_profiles.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUN_ALL = ROOT / "tests" / "run_all.py"

ALLOWED_PROFILES = {
    "safe-unit",
    "isolated-integration",
    "authorized-device",
    "provider-contract",
    "unsafe-legacy",
}
ALLOWED_EVIDENCE = {"S", "M", "I", "P", "F"}
DOMOTICA_LEGACY = "unit/skills/domotica/test_skill_domotica.py"

_pass = 0
_fail = []


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def registered_suites():
    tree = ast.parse(RUN_ALL.read_text(encoding="utf-8"))
    suites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        target_id = getattr(node.target, "id", "")
        if target_id != "suite" or not isinstance(node.iter, (ast.Tuple, ast.List)):
            continue
        values = []
        for item in node.iter.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                values = []
                break
            values.append(item.value)
        if values:
            suites.extend(values)
    return suites


def main():
    print("== run_all registered suites have explicit evidence profiles ==")
    suites = registered_suites()
    check(bool(suites), "tests/run_all.py suite tuple found")
    check(len(suites) == len(set(suites)), "registered suite paths are unique")

    sys.path.insert(0, str(ROOT))
    try:
        from tests.runner_profiles import RUNNER_PROFILES
    except Exception as exc:  # pragma: no cover - exercised by RED before manifest exists
        RUNNER_PROFILES = {}
        check(False, f"tests.runner_profiles imports ({exc})")

    manifest_paths = set(RUNNER_PROFILES)
    suite_paths = set(suites)
    check(manifest_paths == suite_paths,
          f"manifest paths match run_all.py registrations (missing={sorted(suite_paths - manifest_paths)}, extra={sorted(manifest_paths - suite_paths)})")

    for suite in suites:
        meta = RUNNER_PROFILES.get(suite, {})
        check(meta.get("profile") in ALLOWED_PROFILES, f"{suite}: allowed profile")
        check(meta.get("evidence_level") in ALLOWED_EVIDENCE, f"{suite}: allowed evidence level")
        check(isinstance(meta.get("safe_to_run_in_live_checkout"), bool),
              f"{suite}: live-checkout safety is explicit boolean")
        side_effects = meta.get("side_effects")
        requires = meta.get("requires")
        check(isinstance(side_effects, (list, tuple)) and bool(side_effects),
              f"{suite}: explicit side effects")
        check(isinstance(requires, (list, tuple)) and bool(requires),
              f"{suite}: explicit requirements")

    domotica = RUNNER_PROFILES.get(DOMOTICA_LEGACY, {})
    check(domotica.get("safe_to_run_in_live_checkout") is False,
          "legacy domotica suite is not safe in live checkout")
    check(domotica.get("profile") != "safe-unit",
          "legacy domotica suite is not mislabeled safe-unit")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50)
    print(f"{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
