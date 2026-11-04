"""
connectors.py
-------------
Authenticated connection handlers for IBM i (AS400).

Two connection modes are supported:

1. ODBC  (recommended, primary)
   Uses pyodbc + the "IBM i Access ODBC Driver" (part of IBM i Access
   Client Solutions) to run SQL directly against Db2 for i / QSYS2
   catalog views. This is the reliable, structured path used for almost
   all checks in checks_config.json.

2. SSH   (supplementary)
   Uses paramiko to open a session on the IBM i SSH daemon and execute
   QSHELL / CL commands. This is provided as a generic remote-command
   executor. IMPORTANT CAVEAT: many CL "DSP"-style commands are
   screen/spool oriented and do not return clean text to stdout without
   extra OUTFILE/spooled-file handling that can vary by OS release and
   job environment. Treat the ssh_command field in checks_config.json as
   a starting point to validate against your target system, not a
   guaranteed-correct implementation. Where a check truly needs
   structured, trustworthy data, use ODBC mode.

Both connectors are strictly READ-ONLY in how this tool uses them - no
check in checks_config.json issues anything other than SELECT queries
or DSPxxx/RTVxxx style retrieval commands. Nothing in this tool modifies
system values, user profiles, or objects.
"""

import re


class ConnectionError_(Exception):
    pass


class IBMiODBCConnector:
    """Runs SQL SELECT statements against Db2 for i via ODBC."""

    def __init__(self, host, user, password, port=8471, driver=None, ssl=True, query_timeout=45):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        # Default driver name as installed by IBM i Access Client Solutions.
        # On Windows this is usually "IBM i Access ODBC Driver".
        # On Linux with the iAccess ODBC package it may be "IBM i Access ODBC Driver 64-bit".
        self.driver = driver or "IBM i Access ODBC Driver"
        self.ssl = ssl
        self.conn = None
        # Safety net: no single check should be able to hang an entire run.
        # If a query runs longer than this, pyodbc raises and the check is
        # reported as ERROR (with the timeout noted) rather than blocking
        # every check after it. 0 would mean "no limit" - deliberately not
        # used here.
        self.query_timeout = query_timeout

    def connect(self):
        try:
            import pyodbc
        except ImportError as e:
            raise ConnectionError_(
                "pyodbc is not installed. Run: pip install pyodbc"
            ) from e

        conn_str = (
            f"DRIVER={{{self.driver}}};"
            f"SYSTEM={self.host};"
            f"UID={self.user};"
            f"PWD={self.password};"
            f"PORT={self.port};"
        )
        if self.ssl:
            conn_str += "SSL=1;"

        try:
            self.conn = pyodbc.connect(conn_str, timeout=15)
            # Applies to every cursor's query execution from here on (this is
            # separate from the connection-establishment timeout above).
            self.conn.timeout = self.query_timeout
        except Exception as e:
            raise ConnectionError_(f"ODBC connection failed: {e}") from e
        return True

    def run_query(self, sql):
        """Runs a SELECT and returns (columns, rows) or raises ConnectionError_."""
        if not self.conn:
            raise ConnectionError_("Not connected.")
        try:
            cur = self.conn.cursor()
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            rows = [list(r) for r in rows]
            cur.close()
            return columns, rows
        except Exception as e:
            msg = str(e)
            if "HYT00" in msg or "timeout" in msg.lower():
                raise ConnectionError_(
                    f"Query exceeded the {self.query_timeout}s timeout and was aborted. "
                    f"This check likely needs a narrower scope (e.g. a library/path filter) "
                    f"on this system. Original error: {e}"
                ) from e
            raise ConnectionError_(f"Query failed: {e}") from e

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


class IBMiSSHConnector:
    """
    Generic remote command executor over SSH (via paramiko).

    Best suited for:
      - QSHELL / PASE commands that write natively to stdout
        (ls, stat, find, cat, PTF/QSHELL utilities you've verified)
      - CL commands you have confirmed return usable text on your
        target release when run through 'system "<CMD>"'

    Not guaranteed for:
      - DSPxxx/WRKxxx commands that default to spooled/print output
        (these need OUTFILE or CPYSPLF handling specific to your
        environment - validate before relying on results)
    """

    def __init__(self, host, user, password, port=22, timeout=15):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout
        self.client = None

    def connect(self):
        try:
            import paramiko
        except ImportError as e:
            raise ConnectionError_(
                "paramiko is not installed. Run: pip install paramiko"
            ) from e

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        except Exception as e:
            raise ConnectionError_(f"SSH connection failed: {e}") from e
        return True

    def run_command(self, command):
        """Runs a remote command, returns (stdout_text, stderr_text, exit_code)."""
        if not self.client:
            raise ConnectionError_("Not connected.")
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=30)
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            code = stdout.channel.recv_exit_status()
            return out, err, code
        except Exception as e:
            raise ConnectionError_(f"Command execution failed: {e}") from e

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None


def strip_control_chars(text):
    """Utility: clean up SSH output (EBCDIC->text conversion artifacts, etc.)."""
    if text is None:
        return ""
    return re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", "", text)
