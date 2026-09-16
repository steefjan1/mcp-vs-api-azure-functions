"""Minimal pure-Python cl100k_base token counter.

Exact for ASCII input (the regex translates \\p{L}/\\p{N} to ASCII classes),
which is all this experiment feeds it. Requires Python 3.11+ for possessive
quantifiers. Falls back path for tiktoken users lives in the caller.
"""
import base64
import re
from pathlib import Path

_PAT = re.compile(
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\nA-Za-z0-9]?+[A-Za-z]+|[0-9]{1,3}| ?[^\sA-Za-z0-9]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""
)

def load_ranks(path):
    ranks = {}
    for line in Path(path).read_text().splitlines():
        if not line:
            continue
        tok, rank = line.split()
        ranks[base64.b64decode(tok)] = int(rank)
    return ranks

def _bpe_count(piece: bytes, ranks) -> int:
    if piece in ranks:
        return 1
    parts = [bytes([b]) for b in piece]
    while len(parts) > 1:
        best_rank = None
        best_i = None
        for i in range(len(parts) - 1):
            r = ranks.get(parts[i] + parts[i + 1])
            if r is not None and (best_rank is None or r < best_rank):
                best_rank, best_i = r, i
        if best_i is None:
            break
        parts[best_i:best_i + 2] = [parts[best_i] + parts[best_i + 1]]
    return len(parts)

def count_tokens(text: str, ranks) -> int:
    total = 0
    for m in _PAT.finditer(text):
        total += _bpe_count(m.group().encode("utf-8"), ranks)
    return total
