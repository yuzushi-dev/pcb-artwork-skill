"""Small, bounded S-expression reader for KiCad source-preserving edits.

`sexpdata` 1.0.2 (BSD-2-Clause, released 2024-01-09) was evaluated first.
Its released parser returns values without the start/end span of every list and
does not expose input-size or nesting budgets.  Those are the two properties
the patcher needs, so wrapping it would still require a second parser.

Spans are Python string offsets.  ``start`` points at ``(``; ``end`` is the
exclusive offset immediately after ``)``.
"""

from dataclasses import dataclass


MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 256
MAX_NODES = 1_000_000
MAX_TOKENS = 1_000_000
MAX_STRING_BYTES = 1024 * 1024


class ParseError(ValueError):
    """A malformed or over-budget S-expression with a source position."""

    def __init__(self, message, text, offset):
        offset = max(0, min(offset, len(text)))
        line = text.count("\n", 0, offset) + 1
        previous_newline = text.rfind("\n", 0, offset)
        column = offset - previous_newline
        super().__init__(f"{message} at line {line}, column {column}, offset {offset}")
        self.offset = offset
        self.line = line
        self.column = column


@dataclass(eq=True)
class Node:
    values: list
    start: int
    end: int

    @property
    def head(self):
        return self.values[0] if self.values and isinstance(self.values[0], str) else None

    def children(self, head):
        return [value for value in self.values if isinstance(value, Node) and value.head == head]

    def child(self, head):
        matches = self.children(head)
        if len(matches) > 1:
            raise ValueError(
                f"duplicate child '{head}' at second source offset {matches[1].start}"
            )
        return matches[0] if matches else None


class _Parser:
    def __init__(self, text):
        self.text = text
        self.length = len(text)
        self.offset = 0
        self.nodes = 0
        self.tokens = 0

    def count_token(self, offset):
        self.tokens += 1
        if self.tokens > MAX_TOKENS:
            raise ParseError(f"token limit exceeds {MAX_TOKENS}", self.text, offset)

    def skip_space(self):
        while self.offset < self.length:
            char = self.text[self.offset]
            if char.isspace():
                self.offset += 1
            elif char == ";":
                newline = self.text.find("\n", self.offset + 1)
                self.offset = self.length if newline < 0 else newline + 1
            else:
                return

    def node(self, depth):
        if depth > MAX_DEPTH:
            raise ParseError(f"nesting depth exceeds {MAX_DEPTH}", self.text, self.offset)
        if self.offset >= self.length or self.text[self.offset] != "(":
            raise ParseError("expected '('", self.text, self.offset)

        start = self.offset
        self.offset += 1
        self.nodes += 1
        self.count_token(start)
        if self.nodes > MAX_NODES:
            raise ParseError(f"node limit exceeds {MAX_NODES}", self.text, start)

        values = []
        while True:
            self.skip_space()
            if self.offset >= self.length:
                raise ParseError("unclosed expression", self.text, start)
            char = self.text[self.offset]
            if char == ")":
                self.offset += 1
                return Node(values, start, self.offset)
            if char == "(":
                values.append(self.node(depth + 1))
            elif char == '"':
                values.append(self.string())
            else:
                values.append(self.atom())

    def string(self):
        start = self.offset
        self.offset += 1
        self.count_token(start)
        chunks = []
        chunk_start = self.offset
        byte_length = 0
        escapes = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
        while self.offset < self.length:
            char = self.text[self.offset]
            self.offset += 1
            byte_length += len(char.encode("utf-8"))
            if byte_length > MAX_STRING_BYTES:
                raise ParseError(f"string byte limit exceeds {MAX_STRING_BYTES}", self.text, start)
            if char == '"':
                chunks.append(self.text[chunk_start : self.offset - 1])
                return "".join(chunks)
            if char == "\\":
                chunks.append(self.text[chunk_start : self.offset - 1])
                if self.offset >= self.length:
                    raise ParseError("unterminated string escape", self.text, self.offset - 1)
                escaped = self.text[self.offset]
                self.offset += 1
                byte_length += len(escaped.encode("utf-8"))
                if byte_length > MAX_STRING_BYTES:
                    raise ParseError(f"string byte limit exceeds {MAX_STRING_BYTES}", self.text, start)
                if escaped not in escapes:
                    raise ParseError(f"unsupported string escape \\{escaped}", self.text, self.offset - 2)
                chunks.append(escapes[escaped])
                chunk_start = self.offset
        raise ParseError("unterminated string", self.text, start)

    def atom(self):
        start = self.offset
        self.count_token(start)
        while self.offset < self.length:
            char = self.text[self.offset]
            if char.isspace() or char in "();\"":
                break
            self.offset += 1
        if self.offset == start:
            if self.text[self.offset] == ")":
                raise ParseError("unexpected closing parenthesis", self.text, self.offset)
            raise ParseError("expected atom", self.text, self.offset)
        return self.text[start : self.offset]


def parse(text):
    """Parse exactly one list expression into a :class:`Node`."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    try:
        byte_length = len(text.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ParseError("input contains an invalid Unicode surrogate", text, error.start) from error
    if byte_length > MAX_BYTES:
        raise ParseError(f"input byte limit exceeds {MAX_BYTES}", text, 0)

    parser = _Parser(text)
    parser.skip_space()
    if parser.offset >= parser.length:
        raise ParseError("expected one root expression", text, parser.offset)
    if text[parser.offset] != "(":
        raise ParseError("expected one root expression", text, parser.offset)
    root = parser.node(1)
    parser.skip_space()
    if parser.offset != parser.length:
        if text[parser.offset] == ")":
            raise ParseError("unexpected closing parenthesis", text, parser.offset)
        raise ParseError("trailing expression", text, parser.offset)
    return root
