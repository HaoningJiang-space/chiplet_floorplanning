"""Fail-closed, definition-level comparisons of the bounded pad source snapshots."""

import hashlib
import re

from validation.pad_spice import logical_lines, subcircuits


def digest_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def definition_spans(text):
    # Validate nesting, duplicates and termination before selecting raw spans.
    definitions = subcircuits(text)
    pattern = re.compile(r'^\s*\.subckt\s+(\S+)[^\n]*\n.*?^\s*\.ends\b[^\n]*(?:\n|$)',
                         re.I | re.M | re.S)
    spans = {m[1].lower(): m.span() for m in pattern.finditer(text)}
    if spans.keys() != definitions.keys():
        raise ValueError('cannot isolate every subcircuit definition')
    return spans


def canonical_blocks(text):
    return {name: logical_lines(text[start:end])
            for name, (start, end) in definition_spans(text).items()}


def replace_definitions(base, reference, names):
    """Copy named upstream blocks, keeping all other source bytes and pin order."""
    names = tuple(names)
    if not names or len(set(names)) != len(names):
        raise ValueError('need distinct, nonempty replacement names')
    a, b = definition_spans(base), definition_spans(reference)
    da, db = subcircuits(base), subcircuits(reference)
    edits = []
    for name in names:
        if name not in a or name not in b:
            raise ValueError(f'missing upstream definition: {name}')
        if da[name]['pins'] != db[name]['pins']:
            raise ValueError(f'upstream port order changed: {name}')
        start, end = a[name]
        rstart, rend = b[name]
        edits.append((start, end, reference[rstart:rend]))
    result = base
    for start, end, block in sorted(edits, reverse=True):
        result = result[:start] + block + result[end:]
    before, after, upstream = canonical_blocks(base), canonical_blocks(result), canonical_blocks(reference)
    if before.keys() != after.keys():
        raise ValueError('replacement changed definition set')
    for name in before:
        if after[name] != (upstream[name] if name in names else before[name]):
            raise ValueError(f'unexpected source mutation: {name}')
    return result


def renamed_library_equal(reference, active, old, new):
    """Whole-file comparison after one declared symbol-family rename, no numeric edits."""
    return reference.replace(old, new).strip() == active.strip()
