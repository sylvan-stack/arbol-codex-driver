# Test inventory: arbol-codex-driver

Reviewed source revision: `7db318307aa04f172b1d4daecf3262215ef759eb`. Static inventory dated 28 October 2026. See [TESTS.md](../TESTS.md) for execution and restoration rules.

**Top** means individually reviewed and active. **Mid*** means commented and provisionally reserved for a separate testing task; usefulness still needs assessment before restoration. **Low** means removed in the preceding pruning review. A function/program count is not an assertion count or a discovery result.

## scripts/check_build.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`unit`](../scripts/check_build.py#L58) | Mid* / refuses | Broad qualification or diagnostic entry point. Its original implementation is commented and the callable refuses, so disabled checks cannot yield a passing release claim. |
| [`contract`](../scripts/check_build.py#L72) | Mid* / refuses | Broad qualification or diagnostic entry point. Its original implementation is commented and the callable refuses, so disabled checks cannot yield a passing release claim. |
| [`live`](../scripts/check_build.py#L87) | Mid* / refuses | Broad qualification or diagnostic entry point. Its original implementation is commented and the callable refuses, so disabled checks cannot yield a passing release claim. |

## scripts/check_errors.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`check_errors`](../scripts/check_errors.py#L1) | Mid* / commented | Standalone browser, native, installation or qualification program. Its combined checks need a dedicated testing task; the whole program has no individually justified top-tier selection. |

## scripts/check_tools.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`check_tools`](../scripts/check_tools.py#L1) | Mid* / commented | Standalone browser, native, installation or qualification program. Its combined checks need a dedicated testing task; the whole program has no individually justified top-tier selection. |

## scripts/verify_build.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`verify_build`](../scripts/verify_build.py#L1) | Mid* / commented | Standalone browser, native, installation or qualification program. Its combined checks need a dedicated testing task; the whole program has no individually justified top-tier selection. |

## src/arbol_codex_driver/dev.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`probe`](../src/arbol_codex_driver/dev.py#L61) | Mid* / refuses | Broad qualification or diagnostic entry point. Its original implementation is commented and the callable refuses, so disabled checks cannot yield a passing release claim. |
| [`live_check`](../src/arbol_codex_driver/dev.py#L468) | Mid* / refuses | Broad qualification or diagnostic entry point. Its original implementation is commented and the callable refuses, so disabled checks cannot yield a passing release claim. |

## tests/test_accounts_continuity.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`Accounts.test_local_concurrent_creation_update_preserves_owner_settings_and_remove_isolated`](../tests/test_accounts_continuity.py#L9) | Mid* / commented | Scenario: local concurrent creation update preserves owner settings and remove isolated. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Accounts.test_unsigned_refusals_and_malformed_state_do_not_start_vendor_or_disclose_contents`](../tests/test_accounts_continuity.py#L46) | Mid* / commented | Scenario: unsigned refusals and malformed state do not start vendor or disclose contents. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Accounts.test_usage_last_good_cache_rejection_and_catalog_fallback`](../tests/test_accounts_continuity.py#L63) | Mid* / commented | Scenario: usage last good cache rejection and catalog fallback. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Accounts.test_live_progress_dead_and_reused_owner_recovery`](../tests/test_accounts_continuity.py#L88) | Mid* / commented | Scenario: live progress dead and reused owner recovery. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Accounts.test_login_replacement_cancels_pending_and_sign_out_clears_credentials`](../tests/test_accounts_continuity.py#L107) | Mid* / commented | Scenario: login replacement cancels pending and sign out clears credentials. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Continuity.test_resume_overrides_and_delayed_restored_usage_do_not_count_previous_thread`](../tests/test_accounts_continuity.py#L178) | Mid* / commented | Scenario: resume overrides and delayed restored usage do not count previous thread. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Continuity.test_native_history_and_visible_text_fallback_preserve_tools_images_and_system_prompt`](../tests/test_accounts_continuity.py#L203) | Mid* / commented | Scenario: native history and visible text fallback preserve tools images and system prompt. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Continuity.test_resume_vendor_refusal_and_missing_rollout_rebuild_then_failed_resume_invalidates_map`](../tests/test_accounts_continuity.py#L254) | Mid* / commented | Scenario: resume vendor refusal and missing rollout rebuild then failed resume invalidates map. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_app_server.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`AppServerTests.test_private_home_configuration_clean_environment_and_owner_cleanup`](../tests/test_app_server.py#L120) | Mid* / commented | Scenario: private home configuration clean environment and owner cleanup. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_handshake_version_and_effective_configuration_are_enforced`](../tests/test_app_server.py#L140) | Mid* / commented | Scenario: handshake version and effective configuration are enforced. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_fragmented_utf8_early_notifications_burst_and_unknown_request`](../tests/test_app_server.py#L152) | Mid* / commented | Scenario: fragmented utf8 early notifications burst and unknown request. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_malformed_oversized_boolean_id_exit_and_internal_request_timeout`](../tests/test_app_server.py#L175) | Mid* / commented | Scenario: malformed oversized boolean id exit and internal request timeout. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing`](../tests/test_app_server.py#L186) | Mid* / commented | Scenario: cancelled request leaves transport available and preabort sends nothing. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_timeout_and_cancellation_include_blocked_stdin_drain`](../tests/test_app_server.py#L204) | Top / active | Blocks the app-server stdin drain before the reply wait. Exercises timeout and explicit cancellation at that earlier boundary, where a timeout wrapped only around response handling would fail. |
| [`AppServerTests.test_startup_wrong_home_config_and_cancellation_gives_eof_before_force`](../tests/test_app_server.py#L223) | Mid* / commented | Scenario: startup wrong home config and cancellation gives eof before force. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_authentication_rejection_is_specific_and_diagnostics_are_bounded`](../tests/test_app_server.py#L262) | Mid* / commented | Scenario: authentication rejection is specific and diagnostics are bounded. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_cleanup_survives_capture_failure_and_ends_ignoring_descendant`](../tests/test_app_server.py#L281) | Mid* / commented | Scenario: cleanup survives capture failure and ends ignoring descendant. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_predicate_errors_settle_only_affected_waiter`](../tests/test_app_server.py#L299) | Mid* / commented | Scenario: predicate errors settle only affected waiter. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`AppServerTests.test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc`](../tests/test_app_server.py#L315) | Mid* / commented | Scenario: notification backpressure preserves long stream and wakes for rpc. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OutputTests.test_serialized_output_gapless_events_lone_surrogates_and_cancelled_blocked_flush`](../tests/test_app_server.py#L333) | Mid* / commented | Scenario: serialized output gapless events lone surrogates and cancelled blocked flush. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OutputTests.test_broken_output_aborts_writer_and_text_mode_uses_node_unicode_replacement`](../tests/test_app_server.py#L364) | Mid* / commented | Scenario: broken output aborts writer and text mode uses node unicode replacement. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_conformance_state.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`ConformanceState.test_taken_lock_polls_every_50ms_and_fails_after_10s_with_owner`](../tests/test_conformance_state.py#L33) | Mid* / commented | Scenario: taken lock polls every 50ms and fails after 10s with owner. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ConformanceState.test_another_subscription_changes_while_first_lock_is_held`](../tests/test_conformance_state.py#L70) | Mid* / commented | Scenario: another subscription changes while first lock is held. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ConformanceState.test_version_cache_reuses_unchanged_tool_and_invalidates_path_size_and_mtime`](../tests/test_conformance_state.py#L99) | Mid* / commented | Scenario: version cache reuses unchanged tool and invalidates path size and mtime. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_dev.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`DevShapes.test_probe_shapes_keep_only_bounded_protocol_enums_and_no_values`](../tests/test_dev.py#L12) | Mid* / commented | Scenario: probe shapes keep only bounded protocol enums and no values. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevShapes.test_exhaustion_never_uses_credits_and_covers_model_specific_windows`](../tests/test_dev.py#L39) | Mid* / commented | Scenario: exhaustion never uses credits and covers model specific windows. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevShapes.test_model_choice_uses_live_catalog_and_lowest_supported_effort`](../tests/test_dev.py#L54) | Mid* / commented | Scenario: model choice uses live catalog and lowest supported effort. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevShapes.test_sparse_usage_change_does_not_invent_percentages`](../tests/test_dev.py#L72) | Mid* / commented | Scenario: sparse usage change does not invent percentages. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_cli_build_sends_exactly_one_no_tools_ready_request_and_reports_spend`](../tests/test_dev.py#L116) | Mid* / commented | Scenario: cli build sends exactly one no tools ready request and reports spend. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_probe_no_prompt_shapes_owner_isolation_and_private_cleanup`](../tests/test_dev.py#L137) | Mid* / commented | Scenario: probe no prompt shapes owner isolation and private cleanup. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_missing_unsigned_and_cached_exhaustion_refuse_before_tool_start`](../tests/test_dev.py#L164) | Mid* / commented | Scenario: missing unsigned and cached exhaustion refuse before tool start. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_refreshed_exhaustion_or_unavailable_usage_never_starts_run`](../tests/test_dev.py#L195) | Mid* / commented | Scenario: refreshed exhaustion or unavailable usage never starts run. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_live_is_explicit_five_turns_and_build_has_only_ready`](../tests/test_dev.py#L210) | Mid* / commented | Scenario: live is explicit five turns and build has only ready. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_failed_run_retains_observed_starts_tokens_and_usage_change`](../tests/test_dev.py#L276) | Mid* / commented | Scenario: failed run retains observed starts tokens and usage change. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_cleanup_failure_preserves_completed_run_spending_evidence`](../tests/test_dev.py#L290) | Mid* / commented | Scenario: cleanup failure preserves completed run spending evidence. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_partial_failure_marks_possible_missing_spend_and_preserves_observed_usage`](../tests/test_dev.py#L314) | Mid* / commented | Scenario: partial failure marks possible missing spend and preserves observed usage. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_child_cleanup_failure_retains_completed_run_evidence`](../tests/test_dev.py#L329) | Mid* / commented | Scenario: child cleanup failure retains completed run evidence. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_probe_failure_is_typed_and_missing_schema_diagnostic_is_nonsecret`](../tests/test_dev.py#L354) | Mid* / commented | Scenario: probe failure is typed and missing schema diagnostic is nonsecret. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_probe_missing_and_old_tools_preserve_public_version_refusal_details`](../tests/test_dev.py#L367) | Mid* / commented | Scenario: probe missing and old tools preserve public version refusal details. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_probe_interrupt_transport_failure_does_not_count_as_vendor_refusal`](../tests/test_dev.py#L396) | Mid* / commented | Scenario: probe interrupt transport failure does not count as vendor refusal. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_process_identity_lookup_failure_still_ends_spawned_probe_child`](../tests/test_dev.py#L427) | Mid* / commented | Scenario: process identity lookup failure still ends spawned probe child. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`DevChecks.test_forced_driver_cleanup_identity_failure_still_reaps_child`](../tests/test_dev.py#L450) | Mid* / commented | Scenario: forced driver cleanup identity failure still reaps child. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_error_runs.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`ErrorRuns.test_rejected_retry_before_turn_start_reply_interrupts_accepted_turn`](../tests/test_error_runs.py#L10) | Mid* / commented | Scenario: rejected retry before turn start reply interrupts accepted turn. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ErrorRuns.test_rejected_unknown_child_retry_is_replayed_after_spawn_discovery`](../tests/test_error_runs.py#L30) | Mid* / commented | Scenario: rejected unknown child retry is replayed after spawn discovery. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ErrorRuns.test_total_limit_cleans_vendor_and_bounds_wait_for_blocked_output`](../tests/test_error_runs.py#L52) | Mid* / commented | Scenario: total limit cleans vendor and bounds wait for blocked output. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_foundation.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`Foundation.test_state_private_layout_higher_format_and_safe_ids`](../tests/test_foundation.py#L20) | Mid* / commented | Scenario: state private layout higher format and safe ids. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_state_lock_serializes_and_reclaims_dead_owner`](../tests/test_foundation.py#L47) | Mid* / commented | Scenario: state lock serializes and reclaims dead owner. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_atomic_write_failure_cleanup_and_no_symlink_traversal`](../tests/test_foundation.py#L76) | Mid* / commented | Scenario: atomic write failure cleanup and no symlink traversal. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_arguments_settings_environment_and_error_sanitization`](../tests/test_foundation.py#L101) | Mid* / commented | Scenario: arguments settings environment and error sanitization. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_build_identity_ignores_cwd_and_rejects_invalid_metadata`](../tests/test_foundation.py#L167) | Mid* / commented | Scenario: build identity ignores cwd and rejects invalid metadata. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_migration_golden_vectors_and_nonmutating_stream_snapshots`](../tests/test_foundation.py#L182) | Mid* / commented | Scenario: migration golden vectors and nonmutating stream snapshots. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_continuity_selection_order_conditional_settlement_and_killed_owner`](../tests/test_foundation.py#L211) | Mid* / commented | Scenario: continuity selection order conditional settlement and killed owner. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_history_native_pairing_shell_fields_and_private_ordered_images`](../tests/test_foundation.py#L297) | Mid* / commented | Scenario: history native pairing shell fields and private ordered images. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_catalog_pagination_fallback_usage_and_unknown_identifiers`](../tests/test_foundation.py#L329) | Mid* / commented | Scenario: catalog pagination fallback usage and unknown identifiers. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Foundation.test_usage_windows_carry_no_resource_the_app_server_does_not_state`](../tests/test_foundation.py#L393) | Mid* / commented | Scenario: usage windows carry no resource the app server does not state. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`FamilySettings.test_an_unknown_family_setting_refuses_and_is_named`](../tests/test_foundation.py#L420) | Mid* / commented | Scenario: an unknown family setting refuses and is named. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_interrupt.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`Interrupt.test_the_tool_is_asked_once_even_after_the_grace`](../tests/test_interrupt.py#L40) | Mid* / commented | Scenario: the tool is asked once even after the grace. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_lifecycle.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`Lifecycle.test_control_signals_eof_and_peer_stop_interrupt_once_then_cleanup`](../tests/test_lifecycle.py#L196) | Mid* / commented | Scenario: control signals eof and peer stop interrupt once then cleanup. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Lifecycle.test_active_nested_and_late_discovered_children_are_interrupted_and_attributed`](../tests/test_lifecycle.py#L227) | Mid* / commented | Scenario: active nested and late discovered children are interrupted and attributed. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Lifecycle.test_accepted_turn_before_rpc_reply_is_interrupted`](../tests/test_lifecycle.py#L287) | Mid* / commented | Scenario: accepted turn before rpc reply is interrupted. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Lifecycle.test_main_completion_waits_for_late_child_and_closes_spawn_once`](../tests/test_lifecycle.py#L300) | Mid* / commented | Scenario: main completion waits for late child and closes spawn once. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Lifecycle.test_ignored_interrupt_and_stop_during_normal_eof_use_same_force_anchor`](../tests/test_lifecycle.py#L324) | Mid* / commented | Scenario: ignored interrupt and stop during normal eof use same force anchor. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Lifecycle.test_pending_first_stdin_request_signal_and_eof_cancel_before_vendor`](../tests/test_lifecycle.py#L345) | Mid* / commented | Scenario: pending first stdin request signal and eof cancel before vendor. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Lifecycle.test_broken_output_cancels_native_turn_and_cleans_workers`](../tests/test_lifecycle.py#L372) | Mid* / commented | Scenario: broken output cancels native turn and cleans workers. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Lifecycle.test_blocked_output_cleanup_and_final_deadline_for_signal_and_control`](../tests/test_lifecycle.py#L395) | Mid* / commented | Scenario: blocked output cleanup and final deadline for signal and control. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_owner_setup.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`OwnerSetup.test_preserves_mcp_tables_and_reads_no_other_owner_file`](../tests/test_owner_setup.py#L52) | Mid* / commented | Scenario: preserves mcp tables and reads no other owner file. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OwnerSetup.test_missing_tables_empty_table_and_each_run_reads_current_owner_home`](../tests/test_owner_setup.py#L105) | Mid* / commented | Scenario: missing tables empty table and each run reads current owner home. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OwnerSetup.test_malformed_unreadable_and_non_json_tables_have_nonsecret_errors`](../tests/test_owner_setup.py#L120) | Mid* / commented | Scenario: malformed unreadable and non json tables have nonsecret errors. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OwnerSetup.test_diagnostics_scrub_longest_literals_and_preserve_structured_fields`](../tests/test_owner_setup.py#L144) | Mid* / commented | Scenario: diagnostics scrub longest literals and preserve structured fields. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OwnerDiagnostics.test_transient_owner_payload_keeps_exact_json_values_and_home_unmodified`](../tests/test_owner_setup.py#L225) | Mid* / commented | Scenario: transient owner payload keeps exact json values and home unmodified. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OwnerDiagnostics.test_echoed_setup_errors_are_private_and_tool_payloads_are_unchanged`](../tests/test_owner_setup.py#L234) | Mid* / commented | Scenario: echoed setup errors are private and tool payloads are unchanged. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`OwnerDiagnostics.test_split_stderr_values_are_never_retained_or_reported`](../tests/test_owner_setup.py#L247) | Mid* / commented | Scenario: split stderr values are never retained or reported. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_packaging.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`PackagingTests.test_corrupted_cached_distribution_is_refused_without_a_download`](../tests/test_packaging.py#L14) | Mid* / commented | Scenario: corrupted cached distribution is refused without a download. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`PackagingTests.test_archive_pin_rejects_nonhex_digests_and_untrusted_sources`](../tests/test_packaging.py#L34) | Mid* / commented | Scenario: archive pin rejects nonhex digests and untrusted sources. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`PackagingTests.test_candidate_cannot_overwrite_a_numbered_build`](../tests/test_packaging.py#L50) | Mid* / commented | Scenario: candidate cannot overwrite a numbered build. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`PackagingTests.test_build_record_requires_matching_number_entry_and_version`](../tests/test_packaging.py#L58) | Mid* / commented | Scenario: build record requires matching number entry and version. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`PackagingTests.test_unit_gate_refuses_an_empty_suite`](../tests/test_packaging.py#L87) | Mid* / commented | Scenario: unit gate refuses an empty suite. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`PackagingTests.test_live_gate_uses_direct_packaged_entry_and_clean_environment`](../tests/test_packaging.py#L100) | Mid* / commented | Scenario: live gate uses direct packaged entry and clean environment. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`PackagingTests.test_live_gate_refuses_relative_or_empty_test_state_before_start`](../tests/test_packaging.py#L120) | Mid* / commented | Scenario: live gate refuses relative or empty test state before start. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_privacy.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`EventPrivacy.test_every_event_and_text_output_scrubs_nested_private_values`](../tests/test_privacy.py#L16) | Mid* / commented | Scenario: every event and text output scrubs nested private values. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`EventPrivacy.test_split_values_and_open_suffixes_are_hidden_in_all_delta_streams`](../tests/test_privacy.py#L40) | Mid* / commented | Scenario: split values and open suffixes are hidden in all delta streams. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_process_groups.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`ProcessGroupTests.test_same_owner_requires_pid_and_start_time_with_two_second_tolerance`](../tests/test_process_groups.py#L27) | Mid* / commented | Scenario: same owner requires pid and start time with two second tolerance. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ProcessGroupTests.test_reused_group_leader_is_never_selected`](../tests/test_process_groups.py#L34) | Mid* / commented | Scenario: reused group leader is never selected. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ProcessGroupTests.test_live_leader_in_another_group_is_never_selected`](../tests/test_process_groups.py#L41) | Mid* / commented | Scenario: live leader in another group is never selected. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ProcessGroupTests.test_departed_leader_keeps_its_surviving_members_owned`](../tests/test_process_groups.py#L48) | Mid* / commented | Scenario: departed leader keeps its surviving members owned. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ProcessGroupTests.test_departed_leader_without_members_is_finished`](../tests/test_process_groups.py#L55) | Mid* / commented | Scenario: departed leader without members is finished. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ProcessGroupTests.test_zombie_only_group_is_finished`](../tests/test_process_groups.py#L62) | Mid* / commented | Scenario: zombie only group is finished. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ProcessGroupTests.test_verified_group_collects_nested_descendants_and_separate_groups`](../tests/test_process_groups.py#L69) | Mid* / commented | Scenario: verified group collects nested descendants and separate groups. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ProcessGroupTests.test_duplicate_owners_are_signalled_only_once`](../tests/test_process_groups.py#L85) | Mid* / commented | Scenario: duplicate owners are signalled only once. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ForcedProcessGroupTests.test_immediate_kill_refuses_reused_or_wrong_group_leaders`](../tests/test_process_groups.py#L93) | Top / active | Feeds changed process start time and changed process group into the immediate-kill path and asserts that no group signal is sent. Protects unrelated processes from cleanup of a stale owner. |
| [`ForcedProcessGroupTests.test_immediate_kill_requires_fresh_snapshot_and_surviving_member`](../tests/test_process_groups.py#L103) | Mid* / commented | Scenario: immediate kill requires fresh snapshot and surviving member. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ForcedProcessGroupTests.test_a_group_that_is_ending_may_answer_eperm`](../tests/test_process_groups.py#L116) | Mid* / commented | Scenario: a group that is ending may answer eperm. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_request_events.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`Requests.test_request_precedence_private_input_and_opaque_labels`](../tests/test_request_events.py#L9) | Mid* / commented | Scenario: request precedence private input and opaque labels. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Requests.test_request_defaults_and_ignored_settings_effort_provenance`](../tests/test_request_events.py#L63) | Mid* / commented | Scenario: request defaults and ignored settings effort provenance. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Requests.test_request_malformed_images_history_limits_and_identity_before_refusal`](../tests/test_request_events.py#L92) | Mid* / commented | Scenario: request malformed images history limits and identity before refusal. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Requests.test_request_large_stdin_line_is_not_vendor_frame_bound`](../tests/test_request_events.py#L185) | Mid* / commented | Scenario: request large stdin line is not vendor frame bound. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Mapper.test_text_authoritative_blocks_reasoning_usage_dedup_and_reroute`](../tests/test_request_events.py#L214) | Mid* / commented | Scenario: text authoritative blocks reasoning usage dedup and reroute. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Mapper.test_shell_mapping_late_results_failures_and_interrupted_calls_once`](../tests/test_request_events.py#L246) | Mid* / commented | Scenario: shell mapping late results failures and interrupted calls once. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Mapper.test_collaboration_concurrent_receivers_and_nested_spawn_discovery`](../tests/test_request_events.py#L299) | Mid* / commented | Scenario: collaboration concurrent receivers and nested spawn discovery. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Mapper.test_protocol_malformed_foreign_notices_outcome_and_utf8_truncation`](../tests/test_request_events.py#L359) | Mid* / commented | Scenario: protocol malformed foreign notices outcome and utf8 truncation. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`Mapper.test_shell_unwrap_preserves_quoting`](../tests/test_request_events.py#L386) | Mid* / commented | Scenario: shell unwrap preserves quoting. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_run_clocks.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`RunClockTests.test_start_budget_spans_individual_startup_requests`](../tests/test_run_clocks.py#L6) | Mid* / commented | Scenario: start budget spans individual startup requests. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunClockTests.test_any_notification_resets_idle_and_zero_disables_it`](../tests/test_run_clocks.py#L18) | Mid* / commented | Scenario: any notification resets idle and zero disables it. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunClockTests.test_running_call_and_background_work_preserve_idle_budget`](../tests/test_run_clocks.py#L32) | Mid* / commented | Scenario: running call and background work preserve idle budget. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunClockTests.test_total_limit_is_independent_of_notifications_and_work`](../tests/test_run_clocks.py#L43) | Mid* / commented | Scenario: total limit is independent of notifications and work. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_run_errors.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`RunErrors.test_every_structured_class_and_exact_retry_policy`](../tests/test_run_errors.py#L12) | Mid* / commented | Scenario: every structured class and exact retry policy. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrors.test_connection_statuses_and_first_row_precedence`](../tests/test_run_errors.py#L43) | Mid* / commented | Scenario: connection statuses and first row precedence. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrors.test_structured_classes_never_use_wording_fallback`](../tests/test_run_errors.py#L70) | Mid* / commented | Scenario: structured classes never use wording fallback. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrors.test_other_vendor_json_model_and_effort_refusals`](../tests/test_run_errors.py#L89) | Mid* / commented | Scenario: other vendor json model and effort refusals. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrors.test_exact_wording_lists_removed_fragments_and_tool_version`](../tests/test_run_errors.py#L140) | Mid* / commented | Scenario: exact wording lists removed fragments and tool version. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrors.test_wait_units_unknown_waits_and_nonfinite_values`](../tests/test_run_errors.py#L188) | Mid* / commented | Scenario: wait units unknown waits and nonfinite values. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrors.test_safe_bounded_messages_and_details_without_raw_vendor_response`](../tests/test_run_errors.py#L221) | Mid* / commented | Scenario: safe bounded messages and details without raw vendor response. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrorEvents.test_final_error_notification_and_turn_failure_both_use_classifier`](../tests/test_run_errors.py#L265) | Mid* / commented | Scenario: final error notification and turn failure both use classifier. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrorEvents.test_each_retry_emits_notice_and_first_credential_refusal_is_remembered`](../tests/test_run_errors.py#L289) | Mid* / commented | Scenario: each retry emits notice and first credential refusal is remembered. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrorEvents.test_child_retry_refusal_is_visible_at_root_with_version_and_secrets`](../tests/test_run_errors.py#L323) | Mid* / commented | Scenario: child retry refusal is visible at root with version and secrets. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunErrorEvents.test_refusal_before_spawn_discovery_and_nested_refusal_reach_root`](../tests/test_run_errors.py#L358) | Mid* / commented | Scenario: refusal before spawn discovery and nested refusal reach root. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_run_limits.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`RunUsage.test_sparse_notifications_preserve_stored_fields_and_latest_values`](../tests/test_run_limits.py#L26) | Mid* / commented | Scenario: sparse notifications preserve stored fields and latest values. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunUsage.test_window_kind_comes_from_duration_and_by_id_updates_work`](../tests/test_run_limits.py#L47) | Mid* / commented | Scenario: window kind comes from duration and by id updates work. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunUsage.test_malformed_update_keeps_last_good_report`](../tests/test_run_limits.py#L59) | Mid* / commented | Scenario: malformed update keeps last good report. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunUsage.test_wait_requires_current_vendor_exhaustion_and_reset_without_cache_guessing`](../tests/test_run_limits.py#L70) | Mid* / commented | Scenario: wait requires current vendor exhaustion and reset without cache guessing. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunUsageStorage.test_persist_preserves_concurrent_fields_and_compatible_record`](../tests/test_run_limits.py#L105) | Mid* / commented | Scenario: persist preserves concurrent fields and compatible record. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`RunUsageStorage.test_late_report_does_not_restore_account_or_overwrite_newer_usage`](../tests/test_run_limits.py#L127) | Mid* / commented | Scenario: late report does not restore account or overwrite newer usage. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_tool_mapping.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`MapperTools.test_patch_kinds_and_vendor_failure_leave_run_completed`](../tests/test_tool_mapping.py#L40) | Mid* / commented | Scenario: patch kinds and vendor failure leave run completed. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`MapperTools.test_mcp_result_metadata_structured_content_and_error_reason`](../tests/test_tool_mapping.py#L73) | Mid* / commented | Scenario: mcp result metadata structured content and error reason. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`MapperTools.test_generic_tool_failures_preserve_reasons_and_success_false_is_failed`](../tests/test_tool_mapping.py#L107) | Mid* / commented | Scenario: generic tool failures preserve reasons and success false is failed. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`MapperTools.test_web_results_are_opaque_and_large_mcp_results_are_utf8_bounded`](../tests/test_tool_mapping.py#L158) | Mid* / commented | Scenario: web results are opaque and large mcp results are utf8 bounded. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`MapperTools.test_child_post_turn_output_notices_and_retry_keep_parent_attribution`](../tests/test_tool_mapping.py#L189) | Mid* / commented | Scenario: child post turn output notices and retry keep parent attribution. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`MapperTools.test_child_request_notice_without_turn_replays_after_spawn_discovery`](../tests/test_tool_mapping.py#L231) | Mid* / commented | Scenario: child request notice without turn replays after spawn discovery. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`MapperTools.test_child_other_call_remains_open_after_both_turns_complete`](../tests/test_tool_mapping.py#L265) | Mid* / commented | Scenario: child other call remains open after both turns complete. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## tests/test_tool_runs.py

| Test or check | Tier / state | Justification |
| --- | --- | --- |
| [`ToolRuns.test_resume_forwards_changed_owner_mcp_in_memory_without_polluting_saved_state`](../tests/test_tool_runs.py#L6) | Mid* / commented | Scenario: resume forwards changed owner mcp in memory without polluting saved state. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |
| [`ToolRuns.test_late_noncommand_child_tool_closes_after_completed_turns_and_background_work`](../tests/test_tool_runs.py#L74) | Mid* / commented | Scenario: late noncommand child tool closes after completed turns and background work. Disabled because no independently reviewed top-tier rationale was established for this case. Mid is provisional, not a verdict that every assertion is useful. |

## Low tier removed in the prior pass

Source remains in Git at the reviewed revision; these cases are not reintroduced as comments. Supporting evidence is in the October pruning report.

| Former test | Tier / state | Justification |
| --- | --- | --- |
| `tests/test_packaging.py::PackagingTests.test_package_metadata_must_agree` | Low / removed | Sets two version strings to unequal values and asserts the explicit equality guard; no package installation or compatibility boundary is exercised. |
| `tests/test_packaging.py::PackagingTests.test_contract_gate_takes_the_suite_from_readonly` | Low / removed | Mocks the runner and checks only the default/overridden path concatenated into its argv; it does not establish conformance. |
| `tests/test_packaging.py::PackagingTests.test_live_gate_defaults_to_the_test_state_directory` | Low / removed | Mocks execution and compares a literal default directory appended to the current home. |
