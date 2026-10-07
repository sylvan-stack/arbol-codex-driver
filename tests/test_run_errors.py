import unittest
from typing import cast

from arbol_codex_driver.json_types import Json, Object, dumps, object_value, utf8
from arbol_codex_driver.run_errors import CONNECTION_CLASSES, classify_error, structured_error_status, text_wait
from arbol_codex_driver.run_events import RunEvents


class RunErrors(unittest.TestCase):
    def classify(self, info: Json, message: str = "The vendor failed.") -> Object:
        return classify_error({"message": message, "codexErrorInfo": info})

    def test_every_structured_class_and_exact_retry_policy(self) -> None:
        groups = {
            "credential_rejected": ("unauthorized",),
            "rate_limited": ("usageLimitExceeded", "rateLimitExceeded"),
            "context_exceeded": ("contextWindowExceeded",),
            "vendor_unavailable": ("serverOverloaded", "internalServerError", "flexUnavailable"),
            "vendor_error": (
                "cyberPolicy",
                "misalignmentPolicyViolation",
                "tooManyDenials",
                "badRequest",
                "sessionBudgetExceeded",
                "other",
                "futureClass",
            ),
            "tool_failed": ("sandboxError", "threadRollbackFailed", "activeTurnNotSteerable"),
        }
        for code, classes in groups.items():
            for name in classes:
                with self.subTest(name=name):
                    info: Json = {name: {"turnKind": "review"}} if name == "activeTurnNotSteerable" else name
                    result = self.classify(info)
                    self.assertEqual(result["code"], code)
                    self.assertEqual(result["retryable"], code in ("rate_limited", "vendor_unavailable"))
                    self.assertEqual(
                        result["detail"], {"basis": "wording" if name == "other" else "fields", "vendorCode": name}
                    )
                    self.assertNotIn("retryAfterSeconds", result)

    def test_connection_statuses_and_first_row_precedence(self) -> None:
        for name in (*CONNECTION_CLASSES, "usageLimitExceeded", "contextWindowExceeded", "futureClass", "sandboxError"):
            for status in (401, 403):
                with self.subTest(name=name, status=status):
                    result = self.classify({name: {"httpStatusCode": status}}, "usage limit; retry in 8 minutes")
                    self.assertEqual(result["code"], "credential_rejected")
                    self.assertFalse(result["retryable"])
                    self.assertNotIn("retryAfterSeconds", result)
                    self.assertEqual(object_value(result["detail"])["vendorStatus"], status)
        for name in CONNECTION_CLASSES:
            for connection_status, code in (
                (500, "vendor_unavailable"),
                (503, "vendor_unavailable"),
                (600, "vendor_unavailable"),
                (None, "vendor_unavailable"),
                (400, "vendor_error"),
                (429, "vendor_error"),
            ):
                with self.subTest(name=name, status=connection_status):
                    result = self.classify({name: {"httpStatusCode": connection_status}}, "rate limit; codex login")
                    self.assertEqual(result["code"], code)
                    self.assertEqual(object_value(result["detail"])["basis"], "fields")
        for value in (True, "401", 401.0, -1):
            self.assertIsNone(structured_error_status({"codexErrorInfo": {"futureClass": {"httpStatusCode": value}}}))

    def test_structured_classes_never_use_wording_fallback(self) -> None:
        text = "rate limit; codex login; this model requires a newer version of codex; retry in 5 minutes"
        for name, code in (
            ("badRequest", "vendor_error"),
            ("contextWindowExceeded", "context_exceeded"),
            ("sandboxError", "tool_failed"),
            ("futureClass", "vendor_error"),
        ):
            with self.subTest(name=name):
                result = self.classify(name, text)
                self.assertEqual(result["code"], code)
                self.assertEqual(object_value(result["detail"])["basis"], "fields")
                self.assertNotIn("retryAfterSeconds", result)
        result = self.classify("rateLimitExceeded", "invalid api key; retry in 5 minutes")
        self.assertEqual(result["code"], "rate_limited")
        self.assertEqual(result["retryAfterSeconds"], 300)

    def test_other_vendor_json_model_and_effort_refusals(self) -> None:
        cases: list[Object] = [
            {
                "type": "invalid_request_error",
                "message": "The 'no-such-model' model is not supported when using Codex with a ChatGPT account.",
            },
            {
                "message": "Unsupported value: 'minimal' is not supported with the 'gpt-6.1-sol' model.",
                "code": "unsupported_value",
                "param": "reasoning.effort",
            },
            {
                "message": "[reasoning.effort] [invalid_enum_value] Invalid value: 'bogus'. Supported values are: 'none', 'low'.",
                "code": "invalid_enum_value",
                "param": "reasoning.effort",
            },
        ]
        for vendor in cases:
            answer: Object = {"type": "error", "status": 400, "error": vendor, "privateBody": "do not expose the body"}
            with self.subTest(vendor=vendor):
                result = self.classify("other", dumps(answer))
                self.assertEqual(result["code"], "invalid_input")
                self.assertEqual(result["message"], vendor["message"])
                self.assertEqual(object_value(result["detail"])["vendorStatus"], 400)
                self.assertEqual(object_value(result["detail"])["basis"], "fields")
                self.assertNotIn("privateBody", dumps(result))
        negative_cases: list[tuple[Json, int, Object]] = [
            (None, 400, cases[0]),
            ("badRequest", 400, cases[0]),
            ("other", 500, cases[0]),
            (
                "other",
                400,
                {"message": "Unsupported value: 'wrong'.", "param": "service_tier", "code": "unsupported_value"},
            ),
            (
                "other",
                400,
                {"message": "The request was refused.", "param": "reasoning.effort", "code": "invalid_request_error"},
            ),
        ]
        for info, status, vendor in negative_cases:
            with self.subTest(info=info, status=status, vendor=vendor):
                result = self.classify(info, dumps({"status": status, "error": vendor}))
                self.assertEqual(result["code"], "vendor_error")
        result = self.classify("other", dumps({"status": 403, "error": {"message": "usage limit"}}))
        self.assertEqual(result["code"], "credential_rejected")
        self.assertEqual(structured_error_status({"message": dumps({"status": 403}), "codexErrorInfo": "other"}), 403)

    def test_exact_wording_lists_removed_fragments_and_tool_version(self) -> None:
        for info in (None, "other"):
            for phrase in (
                "rate limit",
                "rate_limit",
                "too many requests",
                "usage limit",
                "usage cap",
                "insufficient_quota",
                "limit reached",
                "you've hit your",
                "you have hit your",
                "weekly limit",
                "daily limit",
            ):
                with self.subTest(info=info, phrase=phrase):
                    result = self.classify(info, phrase.upper())
                    self.assertEqual(result["code"], "rate_limited")
                    self.assertEqual(object_value(result["detail"])["basis"], "wording")
            for phrase in (
                "not logged in",
                "logged out",
                "codex login",
                "invalid api key",
                "missing credentials",
                "please login",
            ):
                with self.subTest(info=info, phrase=phrase):
                    result = self.classify(info, phrase.upper())
                    self.assertEqual(result["code"], "credential_rejected")
                    self.assertEqual(object_value(result["detail"])["basis"], "wording")
            for text in ("identifier 429, 401", "quota", "unauthorized", "request rejected"):
                result = self.classify(info, text)
                self.assertEqual(result["code"], "vendor_error")
                self.assertEqual(object_value(result["detail"])["basis"], "wording")
        for text in (
            "The model requires a newer version of codex.",
            "The model requires a newer version of the codex CLI.",
        ):
            result = classify_error({"message": text, "codexErrorInfo": "other"}, tool_version="0.159.2")
            self.assertEqual(result["code"], "tool_unsupported")
            self.assertEqual(object_value(result["detail"])["toolVersion"], "0.159.2")
            self.assertEqual(object_value(result["detail"])["basis"], "wording")
        self.assertEqual(self.classify(None, "The model requires a newer version of codex.")["code"], "vendor_error")
        self.assertEqual(self.classify("other", "rate limit; invalid api key")["code"], "rate_limited")

    def test_wait_units_unknown_waits_and_nonfinite_values(self) -> None:
        for text, seconds in (
            ("retry in 5 minutes", 300),
            ("try again in 2 min", 120),
            ("wait 0.5m", 30),
            ("retry in 2 seconds", 2),
            ("wait 3s", 3),
            ("retry after 5 minutes", 300),
            ("retry after 7", 7),
            ("RETRY AFTER 0.5 seconds", 0.5),
            ("retry after 0", 0),
        ):
            with self.subTest(text=text):
                self.assertEqual(text_wait(text), seconds)
                self.assertEqual(self.classify("rateLimitExceeded", text)["retryAfterSeconds"], seconds)
        for text in (
            "retry in 5",
            "try again in 5",
            "wait 5",
            "retry after 5 hours",
            "retry after -5 seconds",
            "retry after 5 attempts",
            "retry in 5ms",
            "wait 1 day",
            "retry after 1e999",
            "wait " + "9" * 400 + " minutes",
        ):
            with self.subTest(text=text):
                self.assertIsNone(text_wait(text))
                self.assertNotIn("retryAfterSeconds", self.classify("rateLimitExceeded", text))

    def test_safe_bounded_messages_and_details_without_raw_vendor_response(self) -> None:
        secret = "private-key"
        answer: Object = {
            "status": 400,
            "error": {"message": "🌲" * 400 + secret, "code": "🌲" * 400 + secret},
            "unrelated": secret,
        }
        result = classify_error(
            {"codexErrorInfo": "other", "message": dumps(answer), "additionalDetails": secret},
            tool_version="🌲" * 100 + secret,
            secrets=(secret,),
        )
        self.assertNotIn(secret, dumps(result))
        self.assertNotIn("unrelated", dumps(result))
        self.assertLessEqual(len(utf8(str(result["message"]))), 1024)
        detail = object_value(result["detail"])
        self.assertLessEqual(len(utf8(str(detail["vendorCode"]))), 256)
        self.assertLessEqual(len(utf8(str(detail["toolVersion"]))), 64)
        self.assertNotIn("�", dumps(result))
        for info in (None, "other", "contextWindowExceeded"):
            result = self.classify(info, dumps({"status": 400, "largeBody": "secret body"}))
            self.assertEqual(result["message"], "The vendor refused the Codex turn.")
            self.assertNotIn("largeBody", dumps(result))
        self.assertEqual(self.classify("other", "{malformed JSON")["code"], "vendor_error")
        self.assertEqual(classify_error(None)["message"], "codex failed the turn.")


class RunErrorEvents(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[Object] = []
        self.mapper = RunEvents(
            "thread",
            "turn",
            "model",
            lambda type_, data: self.events.append({"type": type_, **data}),
            tool_version="0.159.2",
            secrets=("private-key",),
        )

    def notify(self, method: str, params: Object) -> None:
        self.mapper.consume(method, {"threadId": "thread", "turnId": "turn", **params})

    def test_final_error_notification_and_turn_failure_both_use_classifier(self) -> None:
        self.notify(
            "error", {"willRetry": False, "error": {"codexErrorInfo": "contextWindowExceeded", "message": "too big"}}
        )
        self.notify("turn/completed", {"turn": {"id": "turn", "status": "failed", "error": None}})
        self.assertEqual(self.mapper.outcome, "failed")
        self.assertEqual(object_value(self.mapper.error)["code"], "context_exceeded")
        mapper = RunEvents("thread", "turn", "model", lambda type_, data: None)
        mapper.consume(
            "turn/completed",
            {
                "threadId": "thread",
                "turn": {
                    "id": "turn",
                    "status": "failed",
                    "error": {"codexErrorInfo": "rateLimitExceeded", "message": "retry in 1 minute"},
                },
            },
        )
        self.assertEqual(object_value(mapper.error)["code"], "rate_limited")
        self.assertEqual(object_value(mapper.error)["retryAfterSeconds"], 60)

    def test_each_retry_emits_notice_and_first_credential_refusal_is_remembered(self) -> None:
        self.notify(
            "error",
            {
                "willRetry": True,
                "error": {
                    "codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": None}},
                    "message": "Reconnecting... 2/5",
                },
            },
        )
        self.assertIsNone(self.mapper.credential_rejection)
        for status in (401, 403):
            self.notify(
                "error",
                {
                    "willRetry": True,
                    "error": {
                        "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": status}},
                        "message": f"rejected {status}: private-key",
                    },
                },
            )
        self.assertEqual(len(self.events), 3)
        self.assertTrue(all(item["type"] == "notice" and item["code"] == "retrying" for item in self.events))
        rejection = object_value(self.mapper.credential_rejection)
        self.assertEqual(rejection["code"], "credential_rejected")
        self.assertEqual(object_value(rejection["detail"])["vendorStatus"], 401)
        self.assertEqual(object_value(rejection["detail"])["toolVersion"], "0.159.2")
        self.assertNotIn("private-key", dumps(cast(Json, self.events)))
        self.assertIsNone(self.mapper.outcome)

    def test_child_retry_refusal_is_visible_at_root_with_version_and_secrets(self) -> None:
        self.notify("item/started", {"item": {"id": "spawn", "type": "collabAgentToolCall", "tool": "spawnAgent"}})
        self.notify(
            "item/completed",
            {
                "item": {
                    "id": "spawn",
                    "type": "collabAgentToolCall",
                    "tool": "spawnAgent",
                    "status": "completed",
                    "receiverThreadIds": ["child"],
                }
            },
        )
        self.mapper.consume(
            "error",
            {
                "threadId": "child",
                "turnId": "child-turn",
                "willRetry": True,
                "error": {"codexErrorInfo": "unauthorized", "message": "private-key refused"},
            },
        )
        rejection = object_value(self.mapper.credential_rejection)
        self.assertEqual(rejection["code"], "credential_rejected")
        self.assertEqual(object_value(rejection["detail"])["toolVersion"], "0.159.2")
        self.assertNotIn("private-key", dumps(rejection))
        self.assertEqual(self.events[-1]["parentCallId"], "spawn")
        self.notify(
            "error", {"willRetry": False, "error": {"codexErrorInfo": "unauthorized", "message": "later root refusal"}}
        )
        self.assertEqual(self.mapper.credential_rejection, rejection)

    def test_refusal_before_spawn_discovery_and_nested_refusal_reach_root(self) -> None:
        self.notify("item/started", {"item": {"id": "spawn", "type": "collabAgentToolCall", "tool": "spawnAgent"}})
        self.mapper.consume(
            "error",
            {
                "threadId": "child",
                "turnId": "child-turn",
                "willRetry": True,
                "error": {"codexErrorInfo": "unauthorized", "message": "early child refusal"},
            },
        )
        self.assertIsNone(self.mapper.credential_rejection)
        self.notify(
            "item/completed",
            {
                "item": {
                    "id": "spawn",
                    "type": "collabAgentToolCall",
                    "tool": "spawnAgent",
                    "status": "completed",
                    "receiverThreadIds": ["child"],
                }
            },
        )
        first = object_value(self.mapper.credential_rejection)
        self.assertEqual(first["message"], "early child refusal")
        nested: Object = {"id": "nested", "type": "collabAgentToolCall", "tool": "spawnAgent"}
        self.mapper.consume("item/started", {"threadId": "child", "turnId": "child-turn", "item": nested})
        self.mapper.consume(
            "item/completed",
            {
                "threadId": "child",
                "turnId": "child-turn",
                "item": {**nested, "status": "completed", "receiverThreadIds": ["grandchild"]},
            },
        )
        self.mapper.consume(
            "error",
            {
                "threadId": "grandchild",
                "turnId": "grandchild-turn",
                "willRetry": False,
                "error": {"codexErrorInfo": "unauthorized", "message": "later nested refusal"},
            },
        )
        child = self.mapper.agents["child"].mapper
        assert child is not None
        grandchild = child.agents["grandchild"].mapper
        assert grandchild is not None
        self.assertEqual(object_value(grandchild.credential_rejection)["message"], "later nested refusal")
        self.assertEqual(self.mapper.credential_rejection, first)
