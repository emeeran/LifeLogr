"""Shared FTS5 (SQLite full-text search) helpers."""

from __future__ import annotations


def sanitize_fts_query(query: str) -> str:
    """Build a safe FTS5 ``MATCH`` expression from free-form user input.

    FTS5's MATCH parser treats tokens like ``OR``, ``*``, ``-`` and ``(`` as
    operators, so passing raw user input either throws a syntax error or matches
    something unintended. We split on whitespace and wrap each token in
    double-quotes — a quoted token is a literal phrase — so any input becomes a
    conjunction of literal term searches. Empty input yields ``""``, which FTS5
    treats as match-nothing (callers fall back to ILIKE on zero rows).

    A literal double-quote inside a token is doubled (``"`` → ``""``) per the
    FTS5 string-quoting rule, so a token containing a quote can't prematurely
    close the phrase.
    """
    tokens = [tok.replace('"', '""') for tok in query.split() if tok.strip()]
    return " ".join(f'"{tok}"' for tok in tokens)
