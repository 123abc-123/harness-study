import io
import json
from pathlib import Path
import tempfile
import unittest

from internal_harness.json_stream import Reader, iter_document
from internal_harness.kg import NestedJSONAdapter


class StreamingTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent.parent / ".test-workspace"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.path = Path(self.temp.name) / "data.json"

    def tearDown(self):
        assert Path(self.temp.name).resolve().is_relative_to(Path(__file__).resolve().parent.parent / ".test-workspace")
        self.temp.cleanup()

    def test_chunk_boundaries_unicode_escapes_and_numbers(self):
        document = {"sections": [{"stable_key": "x", "text": '中文、引号"、斜杠\\、换行\n',
                                  "values": [123456, -1.25e15, 1e-17, True, None, [], {}]}],
                    "version": "A", "schema_version": 1, "standard": "synthetic"}
        self.path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        for size in (1, 2, 7, 64, 65536):
            with self.subTest(size=size):
                events = list(iter_document(self.path, chunk_size=size))
                self.assertEqual(events[0], ("section", 0, document["sections"][0]))
                self.assertEqual(dict((key, value) for kind, key, value in events if kind == "field")["version"], "A")

    def test_stream_matches_sample_and_metadata_after_sections(self):
        original = Path(__file__).resolve().parent.parent / "examples/jedec_A.json"
        data = json.loads(original.read_text(encoding="utf-8"))
        reversed_fields = {"sections": data.pop("sections"), **data}
        self.path.write_text(json.dumps(reversed_fields), encoding="utf-8")
        adapter = NestedJSONAdapter()
        metadata, sections = adapter.read(self.path)
        self.assertEqual(metadata["version"], "A")
        self.assertEqual(list(adapter.records(sections)), list(adapter.records(reversed_fields["sections"])))

    def test_malformed_and_duplicate_root_keys_rejected(self):
        for text in ('{"sections":[{},]}', '{"sections":[]', '{"sections":[]} trailing',
                     '{"sections":[],"sections":[]}', '{}', '{"sections":{}}',
                     '{"sections":[],"n":NaN}', '{"sections":[1]}'):
            self.path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(ValueError):
                list(iter_document(self.path, chunk_size=3))

    def test_per_value_limit(self):
        reader = Reader(io.StringIO(json.dumps("a" * 200)), chunk_size=16, max_value_chars=100)
        with self.assertRaises(ValueError):
            reader.value()

    def test_many_sections_yield_individually(self):
        self.path.write_text(json.dumps({"sections": [{"stable_key": str(i)} for i in range(500)]}), encoding="utf-8")
        self.assertEqual(sum(kind == "section" for kind, _, _ in iter_document(self.path, chunk_size=17)), 500)


if __name__ == "__main__":
    unittest.main()
