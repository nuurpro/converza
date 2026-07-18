import json
import unittest
from unittest.mock import AsyncMock, Mock, patch


class MarketingCalendarRulesTests(unittest.TestCase):
    def test_platform_overreach_is_deterministic_and_auditable(self):
        from lib.marketing_calendar import check_platform_overreach

        selected = ["instagram_reels", "tiktok", "youtube_shorts"]
        first = check_platform_overreach(selected, "new")
        second = check_platform_overreach(selected, "new")

        self.assertEqual(first, second)
        self.assertTrue(first["blocked"])
        self.assertEqual(first["recommended"], ["instagram_reels", "youtube_shorts"])
        self.assertIn("three platforms", first["message"])
        self.assertIsNone(check_platform_overreach(selected[:2], "new"))

    def test_literacy_level_uses_inspectable_signals(self):
        from lib.marketing_calendar import derive_literacy_level

        self.assertEqual(
            derive_literacy_level(
                {
                    "overrode_platform_limit": False,
                    "has_tracked_metrics_before": False,
                    "current_process": "whatever feels right",
                }
            ),
            "new",
        )
        self.assertEqual(
            derive_literacy_level(
                {
                    "overrode_platform_limit": False,
                    "has_tracked_metrics_before": True,
                    "current_process": "monthly content calendar",
                }
            ),
            "some_experience",
        )
        self.assertEqual(
            derive_literacy_level(
                {
                    "overrode_platform_limit": True,
                    "has_tracked_metrics_before": True,
                    "current_process": "weekly experiments with tracked CPA and ROAS",
                }
            ),
            "experienced",
        )

    def test_hours_drive_video_count_and_plan_density(self):
        from lib.marketing_calendar import calculate_resource_commitment

        low = calculate_resource_commitment(1, 14)
        normal = calculate_resource_commitment(5, 14)

        self.assertEqual(low["target_video_count"], 2)
        self.assertEqual(normal["target_video_count"], 10)
        self.assertTrue(low["regenerate_lighter_plan"])
        self.assertFalse(normal["regenerate_lighter_plan"])

    def test_skeleton_requires_every_day_and_unique_themes(self):
        from lib.marketing_calendar import parse_calendar_skeleton

        raw = json.dumps(
            {
                "days": [
                    {"day_number": day, "theme": f"Theme {day}"}
                    for day in range(1, 15)
                ]
            }
        )
        days = parse_calendar_skeleton(raw, 14)

        self.assertEqual(len(days), 14)
        self.assertEqual(days[0]["status"], "skeleton")
        self.assertEqual(days[-1]["day_number"], 14)

        with self.assertRaisesRegex(ValueError, "exactly 14"):
            parse_calendar_skeleton(json.dumps({"days": days[:3]}), 14)

    def test_detail_must_repeat_its_skeleton_theme(self):
        from lib.marketing_calendar import parse_day_detail

        detail = parse_day_detail(
            json.dumps(
                {
                    "theme": "Product demo",
                    "script": "0-3s: Show the product. 3-10s: Demonstrate the result.",
                }
            ),
            expected_theme="Product demo",
        )
        self.assertEqual(detail["theme"], "Product demo")

        with self.assertRaisesRegex(ValueError, "does not match"):
            parse_day_detail(
                json.dumps({"theme": "Founder story", "script": "Tell the origin story."}),
                expected_theme="Product demo",
            )

    def test_calendar_rejects_unsupported_social_proof_and_fake_contact_details(self):
        from lib.marketing_calendar import validate_calendar_skeleton, validate_day_detail

        passport = {"brand_name": "Atlas Dental", "core_offer": "Emergency consultations"}
        with self.assertRaisesRegex(ValueError, "unsupported proof"):
            validate_calendar_skeleton(
                [{"day_number": 1, "theme": "Patient success story"}],
                passport,
            )

        with self.assertRaisesRegex(ValueError, "contact detail"):
            validate_day_detail(
                {"theme": "Emergency dental tips", "script": "Call 123-456-7890 or visit www.fake.example today."},
                passport,
            )

        with self.assertRaisesRegex(ValueError, "unsupported claim"):
            validate_day_detail(
                {
                    "theme": "Same-day FAQ",
                    "script": "Hey, I'm Alex. There is no wait, no appointment needed, and your pain is gone.",
                },
                passport,
            )
        with self.assertRaisesRegex(ValueError, "unsupported claim"):
            validate_day_detail(
                {
                    "theme": "Emergency consultation",
                    "script": "We evaluate your pain, provide relief, and treat you today.",
                },
                passport,
            )
        with self.assertRaisesRegex(ValueError, "unsupported claim"):
            validate_day_detail(
                {
                    "theme": "Emergency consultation",
                    "script": "We treat you right away and start treatment in minutes. Your trusted clinic fixes it fast.",
                },
                passport,
            )
        with self.assertRaisesRegex(ValueError, "unsupported claim"):
            validate_day_detail(
                {
                    "theme": "Same-day help",
                    "script": "We ease your pain with a quick visit so you feel better in hours.",
                },
                passport,
            )


class MarketingCalendarEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_call_pattern_uses_brand_and_exact_day_theme(self):
        from lib.marketing_calendar import generate_calendar_skeleton, generate_day_detail

        skeleton_json = json.dumps(
            {
                "days": [
                    {"day_number": day, "theme": f"Theme {day}"}
                    for day in range(1, 15)
                ]
            }
        )
        detail_json = json.dumps(
            {"theme": "Theme 3", "script": "0-3s: Hook. 3-12s: Demonstrate. 12-15s: CTA."}
        )
        engine = AsyncMock(side_effect=[skeleton_json, detail_json])
        passport = {
            "brand_name": "Osman Skincare",
            "core_offer": "Barrier repair serum",
            "target_audience": "Women with dry skin",
            "tone": "confident, friendly",
        }

        days = await generate_calendar_skeleton(
            passport=passport,
            duration_days=14,
            platforms=["instagram_reels"],
            target_video_count=4,
            engine=engine,
        )
        detail = await generate_day_detail(
            passport=passport,
            day=days[2],
            platforms=["instagram_reels"],
            engine=engine,
        )

        self.assertEqual(engine.await_count, 2)
        self.assertIn("exactly 14", engine.await_args_list[0].args[1])
        self.assertIn("Theme 3", engine.await_args_list[1].args[1])
        self.assertEqual(engine.await_args_list[1].kwargs["max_tokens"], 1800)
        self.assertEqual(detail["script"], "0-3s: Hook. 3-12s: Demonstrate. 12-15s: CTA.")

    async def test_unsafe_detail_gets_one_bounded_correction_retry(self):
        from lib.marketing_calendar import generate_day_detail

        engine = AsyncMock(
            side_effect=[
                json.dumps(
                    {
                        "theme": "Same-day FAQ",
                        "script": "Hey, I'm Alex. No appointment needed and no wait.",
                    }
                ),
                json.dumps(
                    {
                        "theme": "Same-day FAQ",
                        "script": "0-3s: Tooth pain today? 3-12s: Explain the consultation. 12-15s: Send us a message.",
                    }
                ),
            ]
        )
        detail = await generate_day_detail(
            passport={"brand_name": "Atlas Dental", "core_offer": "Same-day consultation"},
            day={"day_number": 2, "theme": "Same-day FAQ"},
            platforms=["instagram_reels"],
            engine=engine,
        )

        self.assertEqual(engine.await_count, 2)
        self.assertIn("previous output was rejected", engine.await_args_list[1].args[1])
        self.assertNotIn("Alex", detail["script"])


class MarketingCalendarRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_platform_block_happens_before_database_or_engine_work(self):
        import main
        from fastapi import HTTPException

        request = main.MarketingCalendarInterviewRequest(
            org_id="org-1",
            target_audience="E-commerce founders",
            tone=["direct"],
            core_offer="A managed campaign",
            platforms=["instagram_reels", "youtube_shorts", "tiktok"],
            hours_per_week=3,
            has_tracked_metrics_before=False,
            current_process="whatever feels right",
        )
        with patch.object(main, "_assert_user_owns_org") as ownership:
            with self.assertRaises(HTTPException) as blocked:
                await main.complete_marketing_calendar_interview(
                    request,
                    main.AuthContext(user_id="user-1"),
                )

        ownership.assert_called_once_with("user-1", "org-1")
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertTrue(blocked.exception.detail["blocked"])

    async def test_day_approval_reuses_existing_vea_switchboard_path(self):
        import main

        calendar = {
            "id": "calendar-1",
            "org_id": "org-1",
            "days": [
                {
                    "day_number": 3,
                    "theme": "Product demo",
                    "status": "draft",
                    "script": "0-3s hook. 3-12s product demonstration. 12-15s CTA.",
                }
            ],
        }
        draft = {
            "id": "draft-1",
            "draft_content": "15s video ready.\n\nPreview URL: http://worker/video.mp4",
        }

        class FakeCalendarRepo:
            def __init__(self):
                self.calendar = calendar
                self.updates = []

            def get_by_id(self, _calendar_id):
                return self.calendar

            def update_day(self, current, day_number, updates):
                self.updates.append((day_number, updates))
                self.calendar = {
                    **current,
                    "days": [
                        {**day, **updates} if day["day_number"] == day_number else day
                        for day in current["days"]
                    ],
                }
                return self.calendar

            def find_render_for_run(self, run_id):
                self.asserted_run_id = run_id
                return draft

        repo = FakeCalendarRepo()
        switchboard_repo = object()
        vea = AsyncMock(return_value={"run_id": "run-1", "agent_slug": "vea", "response": ""})
        with (
            patch.object(main, "_assert_user_owns_org") as ownership,
            patch.object(main, "get_marketing_calendar_repo", return_value=repo),
            patch.object(main, "get_switchboard_repo", return_value=switchboard_repo),
            patch.object(main, "handle_direct_agent_message", vea),
        ):
            result = await main.approve_marketing_calendar_day(
                "calendar-1",
                3,
                main.MarketingCalendarActionRequest(org_id="org-1"),
                main.AuthContext(user_id="user-1"),
            )

        ownership.assert_called_once_with("user-1", "org-1")
        vea.assert_awaited_once()
        self.assertEqual(vea.await_args.kwargs["agent_slug"], "vea")
        self.assertIs(vea.await_args.kwargs["repo"], switchboard_repo)
        self.assertEqual(repo.updates[0][1]["status"], "rendering")
        self.assertEqual(result["day"]["status"], "awaiting_hitl")
        self.assertEqual(result["day"]["video_url"], "http://worker/video.mp4")
        self.assertEqual(result["day"]["hitl_draft_id"], "draft-1")

    def test_hitl_decision_syncs_calendar_day_without_claiming_publish(self):
        import main

        repo = Mock()
        with patch.object(main, "get_marketing_calendar_repo", return_value=repo):
            main._sync_calendar_hitl("draft-1", "approve")
            main._sync_calendar_hitl("draft-2", "reject")

        approved = repo.update_day_by_draft.call_args_list[0].args[1]
        rejected = repo.update_day_by_draft.call_args_list[1].args[1]
        self.assertEqual(approved["status"], "completed")
        self.assertEqual(rejected["status"], "failed")
        self.assertNotIn("published", approved.values())


if __name__ == "__main__":
    unittest.main()
