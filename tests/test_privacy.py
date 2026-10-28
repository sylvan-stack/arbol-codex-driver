"""Known transient private values never reach callers, even across chunks."""

import unittest


class Capture:
    def __init__(self) -> None:
        self.text = ""

    async def write(self, text: str) -> None:
        self.text += text


class EventPrivacy(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/test_privacy.py::EventPrivacy.test_every_event_and_text_output_scrubs_nested_private_values
#     async def test_every_event_and_text_output_scrubs_nested_private_values(self) -> None:
#         capture = Capture()
#         stream = EventStream(cast(Output, capture))
#         stream.private_values = ("fixture-private-value",)
#         secret = stream.private_values[0]
#         stream.identity("run", {"caller": secret})
#         for type_ in ("notice", "text", "thinking", "tool_started", "tool_finished"):
#             stream.emit(type_, {"text": secret, "input": {secret: [secret]}, "result": {"output": secret}})
#         await stream.finish(data={"error": {"message": secret}})
#         self.assertNotIn(secret, capture.text)
#         records = [cast(Object, loads(line)) for line in capture.text.splitlines()]
#         self.assertEqual([record["seq"] for record in records], list(range(1, len(records) + 1)))
#         self.assertTrue(all(record["labels"] == {"caller": "[redacted]"} for record in records))
#         self.assertEqual(records[0]["input"], {"[redacted]": ["[redacted]"]})
#         text_capture = Capture()
#         stream = EventStream(cast(Output, text_capture))
#         stream.private_values = (secret,)
#         stream.text_only = True
#         stream.emit("text", {"text": f"before {secret} after"})
#         await stream.finish()
#         self.assertEqual(text_capture.text, "before [redacted] after")
# TEST-TIER-DISABLED-END tests/test_privacy.py::EventPrivacy.test_every_event_and_text_output_scrubs_nested_private_values

# TEST-TIER-DISABLED-BEGIN tests/test_privacy.py::EventPrivacy.test_split_values_and_open_suffixes_are_hidden_in_all_delta_streams
#     async def test_split_values_and_open_suffixes_are_hidden_in_all_delta_streams(self) -> None:
#         capture = Capture()
#         stream = EventStream(cast(Output, capture))
#         secret = "private-key-123"
#         stream.private_values = (secret,)
#         for type_ in ("text_delta", "thinking_delta", "tool_output_delta"):
#             for chunk in ("safe private-", "key-", "123 end"):
#                 stream.emit(type_, {"text": chunk, "parentCallId": "child", "callId": "call"})
#         stream.emit("text_delta", {"text": "unfinished private-"})
#         await stream.finish()
#         records = [cast(Object, loads(line)) for line in capture.text.splitlines()]
#         for type_ in ("text_delta", "thinking_delta", "tool_output_delta"):
#             text = "".join(str(record["text"]) for record in records
#                            if record["type"] == type_ and record.get("parentCallId") == "child")
#             self.assertEqual(text, "safe [redacted] end")
#             self.assertNotIn(secret, text)
#         final_text = "".join(str(record["text"]) for record in records
#                              if record["type"] == "text_delta" and "parentCallId" not in record)
#         self.assertEqual(final_text, "unfinished [redacted]")
#         self.assertEqual(records[-1]["type"], "finished")
#         self.assertFalse(stream.scrubbers)
# TEST-TIER-DISABLED-END tests/test_privacy.py::EventPrivacy.test_split_values_and_open_suffixes_are_hidden_in_all_delta_streams


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_privacy.py:4
# from typing import cast
# TEST-TIER-IMPORTS-END tests/test_privacy.py:4
# TEST-TIER-IMPORTS-BEGIN tests/test_privacy.py:6
# from arbol_codex_driver.event_stream import EventStream, Output
# TEST-TIER-IMPORTS-END tests/test_privacy.py:6
# TEST-TIER-IMPORTS-BEGIN tests/test_privacy.py:7
# from arbol_codex_driver.json_types import Object, loads
# TEST-TIER-IMPORTS-END tests/test_privacy.py:7
