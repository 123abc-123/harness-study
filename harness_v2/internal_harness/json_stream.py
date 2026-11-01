"""Stream a JSON root object and its sections array using only the standard library.

Memory is bounded by a single top-level section, with an explicit per-value limit.
This is not a general event parser and does not promise O(1) memory for huge chapters.
"""

import json


def reject_constant(value):
    raise ValueError(f"Nonstandard JSON number: {value}")


class Reader:
    def __init__(self, stream, chunk_size=65536, max_value_chars=32_000_000):
        self.stream = stream
        self.chunk_size = chunk_size
        self.max_value_chars = max_value_chars
        self.buffer = ""
        self.eof = False
        self.decoder = json.JSONDecoder(parse_constant=reject_constant)

    def more(self):
        chunk = self.stream.read(self.chunk_size)
        self.eof = not chunk
        self.buffer += chunk

    def peek(self):
        while True:
            self.buffer = self.buffer.lstrip(" \r\n\t")
            if self.buffer or self.eof:
                return self.buffer[:1]
            self.more()

    def consume(self, expected):
        if self.peek() != expected:
            raise ValueError(f"Malformed JSON: expected {expected!r}")
        self.buffer = self.buffer[1:]

    def value(self):
        if not self.peek():
            raise ValueError("Unexpected end of JSON")
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError as error:
                if self.eof:
                    raise ValueError("Invalid or incomplete JSON value") from error
                if len(self.buffer) > self.max_value_chars:
                    raise ValueError("One JSON value exceeds 32 million characters; split the chapter")
                self.more()
                continue
            # A scalar token may be split exactly at the buffer boundary.
            if end == len(self.buffer) and not self.eof:
                self.more()
                continue
            if end > self.max_value_chars:
                raise ValueError("One JSON value exceeds the configured character limit")
            if end < len(self.buffer) and self.buffer[end] not in " \r\n\t,:]}":
                # Incomplete numeric exponent at a chunk boundary, e.g. '1e'.
                if not self.eof and len(self.buffer) <= self.max_value_chars:
                    self.more()
                    continue
                raise ValueError("Invalid character after JSON value")
            self.buffer = self.buffer[end:]
            return value


def iter_document(path, chunk_size=65536):
    """Yield ('field', key, value) or ('section', index, object); validate whole file."""
    with open(path, encoding="utf-8-sig") as stream:
        reader = Reader(stream, chunk_size=chunk_size)
        reader.consume("{")
        seen = set()
        if reader.peek() != "}":
            while True:
                key = reader.value()
                if not isinstance(key, str) or key in seen:
                    raise ValueError("Root keys must be unique strings")
                seen.add(key)
                reader.consume(":")
                if key == "sections":
                    reader.consume("[")
                    index = 0
                    if reader.peek() != "]":
                        while True:
                            section = reader.value()
                            if not isinstance(section, dict):
                                raise ValueError("sections must contain objects")
                            yield "section", index, section
                            index += 1
                            if reader.peek() == "]":
                                break
                            reader.consume(",")
                    reader.consume("]")
                else:
                    yield "field", key, reader.value()
                if reader.peek() == "}":
                    break
                reader.consume(",")
        reader.consume("}")
        if reader.peek():
            raise ValueError("Unexpected data after JSON root")
        if "sections" not in seen:
            raise ValueError("Missing sections array")
