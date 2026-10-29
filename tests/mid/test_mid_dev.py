"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_dev as _support
from test_dev import (AsyncMock ,Cancellation ,Coroutine ,Failure ,Path ,asyncio ,command ,loads ,now ,object_value ,patch ,read_json ,stop_child ,sys ,write_json)


class DevChecks(_support.DevChecks):
# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_cli_build_sends_exactly_one_no_tools_ready_request_and_reports_spend
    async def test_cli_build_sends_exactly_one_no_tools_ready_request_and_reports_spend(self) -> None:
        code, output, error = await self.invoke(["dev", "build-check"])
        self.assertEqual((code, error), (0, b""), output)
        result = object_value(loads(output.decode()))
        self.assertEqual((result["outcome"], result["turnsAttempted"], result["inferenceRequests"]), ("passed", 1, 1))
        self.assertEqual(result["subscriptionId"], "test-chatgpt")
        self.assertTrue(object_value(result["tokenUsage"]))
        self.assertIn("usageChange", result)
        self.assertEqual(read_json(Path(str(result["reportPath"]))), result)
        self.assertIn("runtime", object_value(result["provenance"]))
        requests = [record for record in self.records() if record.get("stage") == "input"]
        self.assertEqual(len(requests), 1)
        checks = object_value(requests[0]["checks"])
        params = object_value(object_value(checks["input"])["params"])
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(params["sandboxPolicy"], {"type": "readOnly", "networkAccess": False})
        self.assertFalse(any(path.name.startswith("build-check-") for path in (self.state / "tmp").iterdir()))
        self.assertNotIn(b"fixture@example.invalid", output)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_cli_build_sends_exactly_one_no_tools_ready_request_and_reports_spend

# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_probe_no_prompt_shapes_owner_isolation_and_private_cleanup
    async def test_probe_no_prompt_shapes_owner_isolation_and_private_cleanup(self) -> None:
        owner = self.home / ".codex"
        owner.mkdir()
        sentinel = owner / "auth.json"
        sentinel.write_text("private-owner-login-sentinel")
        metadata = sentinel.stat()
        self.env.update(OPENAI_API_KEY="inherited-secret", CODEX_HOME=str(owner), CLAUDECODE="1")
        code, output, error = await self.invoke(["dev", "probe"])
        self.assertEqual((code, error), (0, b""), output)
        result = object_value(loads(output.decode()))
        self.assertEqual((result["inferenceRequests"], result["outcome"]), (0, "passed"))
        self.assertEqual(sentinel.read_text(), "private-owner-login-sentinel")
        self.assertEqual(sentinel.stat().st_mtime_ns, metadata.st_mtime_ns)
        self.assertFalse(any(path.name.startswith("probe-") for path in (self.state / "tmp").iterdir()))
        for private in ("private-owner-login-sentinel", "fixture@example.invalid", "fixture-secret", "gpt-6.1-sol"):
            self.assertNotIn(private.encode(), output)
        records = self.records()
        self.assertFalse(any(record.get("stage") == "input" for record in records))
        for record in records:
            environment = record.get("environment", [])
            assert isinstance(environment, list)
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("CLAUDECODE", environment)
        self.assertEqual(read_json(Path(str(result["reportPath"]))), result)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_probe_no_prompt_shapes_owner_isolation_and_private_cleanup

# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_missing_unsigned_and_cached_exhaustion_refuse_before_tool_start
    async def test_missing_unsigned_and_cached_exhaustion_refuse_before_tool_start(self) -> None:
        path = self.state / "subscriptions/test-chatgpt/record.json"
        original = object_value(read_json(path))
        for kind in ("missing", "unsigned", "exhausted"):
            self.scenario("C32 plain")
            if kind == "missing":
                path.unlink()
            else:
                record = {**original, "state": "signed_out" if kind == "unsigned" else "signed_in"}
                if kind == "exhausted":
                    record["lastUsage"] = {
                        "outcome": "ok",
                        "fetchedAt": now(),
                        "windows": [{"usedPercent": 100}],
                        "extra": {"credits": {"hasCredits": True}},
                    }
                write_json(path, record)
            for mode in ("build-check", "live-check"):
                code, output, error = await self.invoke(["dev", mode])
                self.assertEqual((code, error), (1, b""), output)
                result = object_value(loads(output.decode()))
                self.assertEqual(
                    object_value(result["error"])["code"],
                    "not_found" if kind == "missing" else "not_signed_in" if kind == "unsigned" else "rate_limited",
                )
                self.assertEqual((result["turnsAttempted"], result["inferenceRequests"]), (0, 0))
                self.assertFalse(self.log.exists())
            write_json(path, original)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_missing_unsigned_and_cached_exhaustion_refuse_before_tool_start


# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_process_identity_lookup_failure_still_ends_spawned_probe_child
    async def test_process_identity_lookup_failure_still_ends_spawned_probe_child(self) -> None:
        pid_file = self.home / "probe-child-pid"
        script = (
            "import os,time; from pathlib import Path; Path("
            + repr(str(pid_file))
            + ").write_text(str(os.getpid())); time.sleep(30)"
        )

        async def failed_lookup(pid: int) -> None:
            async with asyncio.timeout(2):
                while not pid_file.exists():
                    await asyncio.sleep(0.005)
            raise Failure("internal", "Synthetic process lookup failure.")

        with patch("arbol_codex_driver.dev_support.process_owner", failed_lookup):
            with self.assertRaises(Failure):
                await command(sys.executable, ["-I", "-c", script], self.env, self.home, Cancellation())
        from arbol_codex_driver.state import process_owner

        self.assertIsNone(await process_owner(int(pid_file.read_text())))
# TEST-TIER-END tests/test_dev.py::DevChecks.test_process_identity_lookup_failure_still_ends_spawned_probe_child

# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_forced_driver_cleanup_identity_failure_still_reaps_child
    async def test_forced_driver_cleanup_identity_failure_still_reaps_child(self) -> None:
        ready = self.home / "ignoring-child-ready"
        script = (
            "import signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path("
            + repr(str(ready))
            + ").touch(); time.sleep(30)"
        )
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            script,
            start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.children.append(child)
        async with asyncio.timeout(2):
            while not ready.exists():
                await asyncio.sleep(0.005)
        real_wait = asyncio.wait_for

        async def fast_wait(work: Coroutine[object, object, object], seconds: float) -> object:
            if seconds == 20:
                work.close()
                raise TimeoutError
            return await real_wait(work, seconds)

        with (
            patch("arbol_codex_driver.dev_support.asyncio.wait_for", fast_wait),
            patch(
                "arbol_codex_driver.dev_support.process_owner",
                AsyncMock(side_effect=Failure("internal", "Synthetic identity failure.")),
            ),
        ):
            with self.assertRaises(Failure) as raised:
                await stop_child(child)
        self.assertEqual(raised.exception.result["code"], "internal")
        self.assertIsNotNone(child.returncode)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_forced_driver_cleanup_identity_failure_still_reaps_child
