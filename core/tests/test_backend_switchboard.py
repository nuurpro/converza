import os
import unittest
from unittest.mock import AsyncMock, patch


class MentionParserTests(unittest.TestCase):
    def test_extract_mentions_returns_unique_agent_slugs_and_ignores_owner(self):
        from lib.mentions import extract_mentions

        text = "Ask @Milo to brief @Vea, then tell @owner. @milo already knows."

        self.assertEqual(extract_mentions(text), ["milo", "vea"])


class SwitchboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.classifier = patch('lib.switchboard.classify_output', AsyncMock(return_value='customer_copy'))
        self.classifier.start()
        self.addCleanup(self.classifier.stop)

    async def test_context_assembler_uses_brand_identity_and_agent_scoped_memory(self):
        from lib.context_assembler import assemble_context
        from lib.repository import InMemoryRepository

        repo = InMemoryRepository()
        repo.seed_brand_passport("org-1", {"brand_name": "Osman Skincare"})
        await repo.insert_agent_memory("org-1", "milo", "user", "Milo memory")
        await repo.insert_agent_memory("org-1", "vea", "user", "Vea memory")

        context = await assemble_context("org-1", "milo", repo=repo)

        self.assertEqual(context["brand_passport"]["brand_name"], "Osman Skincare")
        self.assertIn("ROLE:", context["identity"])
        self.assertEqual([row["content"] for row in context["memory"]], ["Milo memory"])

    async def test_narrate_step_writes_started_and_completed_rows_plus_squad_messages(self):
        from lib.narration import narrate_step
        from lib.repository import InMemoryRepository

        repo = InMemoryRepository()
        run_id = await repo.create_agent_run("org-1", "milo", "owner", "Research")

        async with narrate_step(
            repo=repo,
            org_id="org-1",
            agent_slug="milo",
            run_id=run_id,
            step_label="Reviewing brand and request",
        ):
            pass

        self.assertEqual(
            [step["step_status"] for step in repo.agent_run_steps],
            ["started", "completed"],
        )
        self.assertEqual(len(repo.squad_messages), 2)
        self.assertIn("Starting reviewing brand and request", repo.squad_messages[0]["content"])
        self.assertIn("Finished reviewing brand and request", repo.squad_messages[1]["content"])

    async def test_milo_narration_uses_real_counted_output_and_no_fake_market_stat(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import handle_direct_agent_message

        repo = InMemoryRepository()
        repo.seed_brand_passport("org-1", {"brand_name": "Osman Skincare"})

        with patch(
            "lib.switchboard.call_engine",
            AsyncMock(
                return_value=(
                    "1. Stop losing midnight leads.\n"
                    "2. Reply before competitors wake up.\n"
                    "3. Book the consultation while intent is hot."
                )
            ),
        ):
            from lib.switchboard import run_agent
            legacy = await repo.create_draft('org-1','milo','Legacy draft','')
            await run_agent(
                org_id="org-1",
                agent_slug="milo",
                text="Draft hooks for lead response speed",
                repo=repo,
                triggered_by='owner', existing_draft=legacy,
            )

        contents = [message["content"] for message in repo.squad_messages]
        self.assertFalse(any("cold plunge" in content for content in contents))
        self.assertTrue(any("3 drafted items" in content for content in contents))

    async def test_milo_narration_changes_with_actual_output_count(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import handle_direct_agent_message

        repo = InMemoryRepository()
        repo.seed_brand_passport("org-skincare", {"brand_name": "Osman Skincare"})
        repo.seed_brand_passport("org-clinic", {"brand_name": "Atlas Dental"})

        with patch(
            "lib.switchboard.call_engine",
            AsyncMock(
                side_effect=[
                    "1. Repair cracked skin before winter.\n2. Keep hands camera-ready.",
                    "1. Fix the tooth pain today.\n2. Book a same-day consult.\n3. Smile before Friday.",
                ]
            ),
        ):
            from lib.switchboard import run_agent
            legacy = await repo.create_draft('org-skincare','milo','Legacy draft','')
            await run_agent(
                org_id="org-skincare",
                agent_slug="milo",
                text="Draft hand cream hooks",
                repo=repo,
                triggered_by='owner', existing_draft=legacy,
            )
            legacy = await repo.create_draft('org-clinic','milo','Legacy draft','')
            await run_agent(
                org_id="org-clinic",
                agent_slug="milo",
                text="Draft emergency dental hooks",
                repo=repo,
                triggered_by='owner', existing_draft=legacy,
            )

        finished = [
            message["content"]
            for message in repo.squad_messages
            if message["content"].startswith("Finished drafting hooks")
        ]
        self.assertEqual(
            finished,
            [
                "Finished drafting hooks - 2 drafted items",
                "Finished drafting hooks - 3 drafted items",
            ],
        )
        self.assertFalse(
            any("cold plunge" in content or "+18%" in content or "5 hooks" in content for content in finished)
        )

    async def test_owner_milo_campaign_is_queued_without_preapproval_vea_handoff(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import handle_squad_owner_message

        repo = InMemoryRepository()
        repo.seed_brand_passport("org-1", {"brand_name": "Osman Skincare"})

        with (
            patch(
                "lib.switchboard.call_engine",
                AsyncMock(
                    side_effect=[
                        "Five strong hooks are ready. @Vea render the best one into a 15s video.",
                        "This serum keeps skin calm after cold weather in one simple daily step.",
                    ]
                ),
            ),
        ):
            await handle_squad_owner_message(
                org_id="org-1",
                text="Push our new serum, get a video ready",
                repo=repo,
            )

        self.assertEqual(repo.squad_messages[0]["sender_slug"], "owner")
        self.assertEqual(
            [run["agent_slug"] for run in repo.agent_runs],
            ["milo"],
        )
        self.assertEqual(repo.drafts, [])
        from services.milo.store import MiloStore
        jobs=await MiloStore(repo).jobs('org-1')
        self.assertEqual([j['kind'] for j in jobs],['generate'])
        self.assertEqual(repo.agent_runs[-1]["status"], "completed")

    async def test_owner_squad_message_routes_all_explicit_mentions(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import handle_squad_owner_message

        repo = InMemoryRepository()
        repo.seed_brand_passport("org-1", {"brand_name": "Osman Skincare"})

        with patch(
            "lib.switchboard.call_engine",
            AsyncMock(side_effect=["Milo has the campaign brief.", "Sleyz has the DM brief."]),
        ):
            result = await handle_squad_owner_message(
                org_id="org-1",
                text="@Milo draft hooks and @Sleyz draft the sales follow-up.",
                repo=repo,
            )

        self.assertEqual(result["routed_to"], ["milo", "sleyz"])
        self.assertEqual([run["agent_slug"] for run in repo.agent_runs], ["milo", "sleyz"])

    async def test_mutual_agent_mentions_halt_at_handoff_cap_with_safety_message(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import MAX_HANDOFF_HOPS, run_agent

        repo = InMemoryRepository()
        repo.seed_brand_passport("org-1", {"brand_name": "Osman Skincare"})

        async def looping_engine(system_prompt, user_input, tools=None, **kwargs):
            if "Act as Sleyz" in user_input:
                return "@Milo this needs your campaign angle."
            return "@Sleyz this needs your sales angle."

        with patch("lib.switchboard.call_engine", new=looping_engine), patch('lib.switchboard.classify_output',AsyncMock(return_value='internal_recommendation')):
            await run_agent(
                org_id="org-1",
                agent_slug="milo",
                text="Start a loop test",
                triggered_by="owner",
                repo=repo,
            )

        self.assertEqual(len(repo.agent_runs), MAX_HANDOFF_HOPS + 1)
        self.assertTrue(
            any(
                f"halted after {MAX_HANDOFF_HOPS} hops" in message["content"]
                for message in repo.squad_messages
            )
        )

    async def test_context_assembly_failure_posts_visible_squad_failure(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import handle_direct_agent_message

        repo = InMemoryRepository()

        async def broken_context(org_id, agent_slug, repo=None):
            raise RuntimeError("context exploded")

        with patch("lib.switchboard.assemble_context", new=broken_context):
            with self.assertRaisesRegex(RuntimeError, "context exploded"):
                await handle_direct_agent_message(
                    org_id="org-1",
                    agent_slug="milo",
                    text="This should fail visibly",
                    repo=repo,
                )

        self.assertEqual(repo.agent_runs[0]["status"], "failed")
        self.assertTrue(
            any(
                "Failed Preparing agent context" in message["content"]
                and "context exploded" in message["content"]
                for message in repo.squad_messages
            )
        )

    async def test_vea_request_routes_to_approved_scripts_without_script_generation(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import handle_direct_agent_message

        repo = InMemoryRepository()
        repo.seed_brand_passport("org-1", {"brand_name": "Osman Skincare"})

        with patch(
            "lib.switchboard.call_engine",
            AsyncMock(side_effect=RuntimeError("groq unavailable")),
        ) as engine:
            result = await handle_direct_agent_message(
                org_id="org-1", agent_slug="vea", text="Render a video", repo=repo,
            )

        engine.assert_not_awaited()
        self.assertEqual(repo.agent_runs[0]["status"], "completed")
        self.assertIn('approved Milo script', result['response'])
        self.assertEqual(repo.drafts, [])

    async def test_hitl_edit_requires_real_content_and_completes_linked_run(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import resolve_hitl

        repo = InMemoryRepository()
        run_id = await repo.create_agent_run("org-1", "vea", "owner", "Render video")
        await repo.update_agent_run(run_id, {"status": "awaiting_hitl"})
        draft = await repo.create_draft(
            org_id="org-1",
            agent_slug="vea",
            inbound_text="Render video",
            draft_content="Original draft",
        )
        await repo.insert_squad_message(
            org_id="org-1",
            sender_slug="vea",
            content="Video ready",
            related_run_id=run_id,
            hitl_draft_id=draft["id"],
        )

        draft = await repo.transition_draft('org-1', draft['id'], 'ready', draft['revision'], 'ready', edited_content=draft['draft_content'])
        with self.assertRaisesRegex(ValueError, "final_content"):
            await resolve_hitl(
                draft_id=draft["id"],
                action="edit",
                edited_content="  ",
                repo=repo,
            )

        updated = await resolve_hitl(
            draft_id=draft["id"],
            action="edit",
            edited_content="Use this edited script instead.",
            repo=repo,
        )

        self.assertEqual(updated["status"], "EDITED")
        self.assertEqual(updated["final_content"], "Use this edited script instead.")
        self.assertEqual(repo.agent_runs[0]["status"], "completed")
        self.assertIsNotNone(repo.agent_runs[0]["completed_at"])

    async def test_hitl_approve_completes_run_and_reject_fails_run(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import resolve_hitl

        repo = InMemoryRepository()
        approve_run_id = await repo.create_agent_run("org-1", "vea", "owner", "Approve me")
        reject_run_id = await repo.create_agent_run("org-1", "vea", "owner", "Reject me")
        await repo.update_agent_run(approve_run_id, {"status": "awaiting_hitl"})
        await repo.update_agent_run(reject_run_id, {"status": "awaiting_hitl"})
        approve_draft = await repo.create_draft("org-1", "vea", "Approve me", "Approved draft")
        reject_draft = await repo.create_draft("org-1", "vea", "Reject me", "Rejected draft")
        await repo.insert_squad_message(
            "org-1",
            "vea",
            "Approve ready",
            related_run_id=approve_run_id,
            hitl_draft_id=approve_draft["id"],
        )
        await repo.insert_squad_message(
            "org-1",
            "vea",
            "Reject ready",
            related_run_id=reject_run_id,
            hitl_draft_id=reject_draft["id"],
        )

        for d in (approve_draft, reject_draft):
            await repo.transition_draft('org-1', d['id'], 'ready', d['revision'], d['id'], edited_content=d['draft_content'])
        await resolve_hitl(draft_id=approve_draft["id"], action="approve", repo=repo)
        await resolve_hitl(draft_id=reject_draft["id"], action="reject", repo=repo)

        self.assertEqual(repo.agent_runs[0]["status"], "completed")
        self.assertEqual(repo.agent_runs[1]["status"], "failed")


class SupabaseConfigTests(unittest.TestCase):
    def test_supabase_client_requires_service_key_without_anon_fallback(self):
        import db

        db._client = None
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-key-is-not-enough",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "SUPABASE_SERVICE_KEY"):
                db.get_supabase()


if __name__ == "__main__":
    unittest.main()
