"""
checks_engine.py
-----------------
Loads checks_config.json, executes each check against whichever connector
is active (ODBC or SSH), evaluates the result, and returns a uniform
CheckResult record ready for display / reporting.
"""

import json
import datetime
from dataclasses import dataclass, field
from connectors import ConnectionError_, strip_control_chars


@dataclass
class CheckResult:
    check_id: str
    cis_ref: str
    name: str
    category: str
    command_used: str
    evidence: str
    status: str          # "PASS", "FAIL", "REVIEW", "ERROR"
    recommendation: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat(timespec="seconds"))


def load_checks(path="checks_config.json"):
    with open(path, "r") as f:
        data = json.load(f)
    return data.get("checks", [])


def _row_to_dict(columns, row):
    return dict(zip(columns, row))


_NOMAX_TEXT = {"*NOMAX", "*NONE"}


def _resolve_numeric(row_dict, field_name):
    """Get a usable number for `field_name`, tolerating IBM i releases that
    populate the 'wrong' column relative to what QSYS2.SYSTEM_VALUE_INFO's
    documentation describes (e.g. a numeric system value's value showing up
    in CURRENT_CHARACTER_VALUE as a zero-padded string like '000005', with
    CURRENT_NUMERIC_VALUE left null). Tries the requested field first, then
    its character/numeric sibling, then handles *NOMAX-style text used by
    numeric_max_or_notnomax callers.

    Returns (numeric_value_or_None, raw_display_value).
    """
    value = row_dict.get(field_name)

    def _try_parse(v):
        if v is None:
            return None
        s = str(v).strip()
        if s == "":
            return None
        if s.upper() in _NOMAX_TEXT:
            return -1.0
        try:
            return float(s)
        except ValueError:
            return None

    parsed = _try_parse(value)
    if parsed is not None:
        return parsed, value

    sibling = None
    if field_name == "CURRENT_NUMERIC_VALUE":
        sibling = "CURRENT_CHARACTER_VALUE"
    elif field_name == "CURRENT_CHARACTER_VALUE":
        sibling = "CURRENT_NUMERIC_VALUE"
    if sibling and sibling in row_dict:
        sib_value = row_dict.get(sibling)
        sib_parsed = _try_parse(sib_value)
        if sib_parsed is not None:
            return sib_parsed, sib_value

    # Nothing usable found - return the original (likely None) for error reporting.
    return None, value


def _evaluate(evaluation, row_dict, row_count):
    """Returns (status, evidence_suffix) based on the evaluation spec."""
    etype = evaluation.get("type")

    if etype == "row_count_review":
        return "REVIEW", evaluation.get("note", "Manual review required.")

    if not row_dict:
        return "ERROR", "No data returned for evaluation."

    field_name = evaluation.get("field")
    value = row_dict.get(field_name)

    if etype == "numeric_min":
        v, raw = _resolve_numeric(row_dict, field_name)
        if v is None:
            return "ERROR", f"Non-numeric value returned: {raw!r}"
        ok = v >= evaluation["min"]
        return ("PASS" if ok else "FAIL"), f"Value={raw}, required >= {evaluation['min']}"

    if etype == "numeric_max_or_notnomax":
        # value of -1 conventionally represents *NOMAX/*NONE in many QSYS2 numeric columns
        v, raw = _resolve_numeric(row_dict, field_name)
        if v is None:
            return "ERROR", f"Non-numeric value returned: {raw!r}"
        if v == -1:
            return "FAIL", f"Value=*NOMAX/*NONE (-1), required <= {evaluation['max']}"
        ok = v <= evaluation["max"]
        return ("PASS" if ok else "FAIL"), f"Value={raw}, required <= {evaluation['max']}"

    if etype == "numeric_min_max_range":
        v, raw = _resolve_numeric(row_dict, field_name)
        if v is None:
            return "ERROR", f"Non-numeric value returned: {raw!r}"
        ok = evaluation["min"] <= v <= evaluation["max"]
        return ("PASS" if ok else "FAIL"), f"Value={raw}, required between {evaluation['min']} and {evaluation['max']}"

    if etype == "numeric_in_set":
        v, raw = _resolve_numeric(row_dict, field_name)
        if v is None:
            return "ERROR", f"Non-numeric value returned: {raw!r}"
        ok = v in [float(x) for x in evaluation["allowed"]]
        return ("PASS" if ok else "FAIL"), f"Value={raw}, allowed={evaluation['allowed']}"

    if etype == "string_in_set":
        sval = str(value).strip() if value is not None else ""
        ok = sval in evaluation["allowed"]
        return ("PASS" if ok else "FAIL"), f"Value={sval!r}, allowed={evaluation['allowed']}"

    if etype == "string_contains_all":
        sval = str(value) if value is not None else ""
        missing = [s for s in evaluation["required_substrings"] if s not in sval]
        ok = len(missing) == 0
        return ("PASS" if ok else "FAIL"), f"Value={sval!r}, missing={missing if missing else 'none'}"

    return "ERROR", f"Unknown evaluation type: {etype}"


def run_check_odbc(check, odbc_connector):
    sql = check.get("odbc_query")
    if not sql:
        return CheckResult(
            check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
            category=check.get("category", ""), command_used="(no ODBC query defined for this check)",
            evidence="Skipped - no ODBC query configured.", status="ERROR",
            recommendation=check.get("recommendation", ""),
        )
    try:
        columns, rows = odbc_connector.run_query(sql)
    except ConnectionError_ as e:
        return CheckResult(
            check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
            category=check.get("category", ""), command_used=check.get("command_used_label", sql),
            evidence=f"Query error: {e}", status="ERROR",
            recommendation=check.get("recommendation", ""),
        )

    row_count = len(rows)
    evaluation = check.get("evaluation", {})

    if evaluation.get("type") == "row_count_review":
        preview_rows = rows[:15]
        evidence_lines = [", ".join(columns)] + [", ".join(str(v) for v in r) for r in preview_rows]
        if row_count > 15:
            evidence_lines.append(f"... ({row_count - 15} more rows not shown)")
        evidence = f"{row_count} row(s) returned.\n" + "\n".join(evidence_lines)
        status, note = _evaluate(evaluation, {}, row_count)
        evidence += f"\n\nReview note: {note}"
        # Zero rows on a "flag if present" style query is usually good news - note it plainly.
        if row_count == 0:
            evidence = "0 rows returned (no matching entries found)."
    else:
        row_dict = _row_to_dict(columns, rows[0]) if rows else {}
        status, note = _evaluate(evaluation, row_dict, row_count)
        raw_evidence = ", ".join(f"{k}={v}" for k, v in row_dict.items()) if row_dict else "No rows returned."
        evidence = f"{raw_evidence}\n{note}"

    return CheckResult(
        check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
        category=check.get("category", ""), command_used=check.get("command_used_label", sql),
        evidence=evidence, status=status,
        recommendation=check.get("recommendation", ""),
    )


def run_check_ssh(check, ssh_connector):
    cmd = check.get("ssh_command")
    if not cmd:
        return CheckResult(
            check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
            category=check.get("category", ""), command_used="(no SSH command defined for this check)",
            evidence="Skipped - this check has no SSH equivalent configured. Use ODBC mode for this control.",
            status="ERROR", recommendation=check.get("recommendation", ""),
        )
    try:
        out, err, code = ssh_connector.run_command(cmd)
    except ConnectionError_ as e:
        return CheckResult(
            check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
            category=check.get("category", ""), command_used=cmd,
            evidence=f"Command error: {e}", status="ERROR",
            recommendation=check.get("recommendation", ""),
        )

    out_clean = strip_control_chars(out).strip()
    err_clean = strip_control_chars(err).strip()
    evidence = out_clean if out_clean else "(no stdout returned)"

    evaluation = check.get("evaluation", {})
    etype = evaluation.get("type")

    # File-based checks (e.g. cat'ing sshd_config) return genuine, reliable stdout,
    # so these get a real PASS/FAIL via regex rather than being forced to REVIEW.
    if etype == "ssh_regex_all_present":
        import re as _re
        missing = [p for p in evaluation["patterns"] if not _re.search(p, out_clean, _re.MULTILINE | _re.IGNORECASE)]
        status = "PASS" if not missing else "FAIL"
        note = "All required settings found." if not missing else f"Missing/not matching: {missing}"
        if err_clean:
            evidence += f"\n[stderr] {err_clean}"
        evidence += f"\n\n{note}"
        return CheckResult(
            check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
            category=check.get("category", ""), command_used=cmd,
            evidence=evidence, status=status, recommendation=check.get("recommendation", ""),
        )

    if etype == "ssh_regex_none_present":
        import re as _re
        found = [p for p in evaluation["patterns"] if _re.search(p, out_clean, _re.MULTILINE | _re.IGNORECASE)]
        status = "FAIL" if found else "PASS"
        note = f"Disallowed setting(s) found: {found}" if found else "None of the disallowed patterns were found."
        if err_clean:
            evidence += f"\n[stderr] {err_clean}"
        evidence += f"\n\n{note}"
        return CheckResult(
            check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
            category=check.get("category", ""), command_used=cmd,
            evidence=evidence, status=status, recommendation=check.get("recommendation", ""),
        )

    # Default: CL/QSHELL command of unknown output reliability -> evidence for manual review.
    if err_clean:
        evidence += f"\n[stderr] {err_clean}"
    evidence += (
        "\n\nNOTE: SSH-mode output for CL commands may require additional spooled-file/"
        "OUTFILE handling not implemented here - treat as raw evidence for manual review, "
        "or confirm with ODBC mode for an authoritative pass/fail."
    )

    return CheckResult(
        check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
        category=check.get("category", ""), command_used=cmd,
        evidence=evidence, status="REVIEW",
        recommendation=check.get("recommendation", ""),
    )


def run_check_manual(check):
    """Checks with no reliable SQL or SSH-scriptable path (e.g. Service Tools screens,
    NetServer 5250 menus). Always returns REVIEW with the manual verification steps as evidence."""
    return CheckResult(
        check_id=check["id"], cis_ref=check.get("cis_ref", ""), name=check["name"],
        category=check.get("category", ""),
        command_used=check.get("manual_command", "(interactive 5250 procedure - see evidence)"),
        evidence=check.get("manual_note", "This control has no scriptable SQL/SSH path on IBM i and "
                                          "must be verified interactively."),
        status="REVIEW", recommendation=check.get("recommendation", ""),
    )


def run_all_checks(checks, mode, odbc_connector=None, ssh_connector=None, progress_callback=None):
    """
    mode: "odbc" or "ssh"
    progress_callback: optional function(index, total, check_name) called before each check
    """
    results = []
    total = len(checks)
    for i, check in enumerate(checks):
        if progress_callback:
            progress_callback(i + 1, total, check.get("name", check.get("id", "?")))
        if check.get("evaluation", {}).get("type") == "manual_only":
            result = run_check_manual(check)
        elif mode == "odbc":
            result = run_check_odbc(check, odbc_connector)
        elif mode == "ssh":
            result = run_check_ssh(check, ssh_connector)
        else:
            raise ValueError(f"Unknown mode: {mode}")
        results.append(result)
    return results
