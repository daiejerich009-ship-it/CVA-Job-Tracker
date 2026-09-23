import unittest

from job_tracker import process_jobs, score_job, canonical_url


class JobTrackerTests(unittest.TestCase):
    def test_non_voice_entry_level_ph_job_passes(self):
        passed, score, matched, reason = score_job(
            "Junior Virtual Assistant - Non-Voice",
            "Work from home in the Philippines. No experience required. Training provided. Email and chat support.",
            "Philippines - Remote",
        )
        self.assertTrue(passed)
        self.assertGreater(score, 0)
        self.assertIn("virtual assistant", matched)
        self.assertTrue(reason)

    def test_call_center_is_rejected(self):
        passed, *_ = score_job(
            "Virtual Assistant",
            "Join our call center team. You will handle inbound calls and phone support.",
            "Philippines",
        )
        self.assertFalse(passed)

    def test_multiple_year_requirement_is_rejected(self):
        passed, *_ = score_job(
            "Virtual Assistant",
            "Remote Philippines role. Requires 2 years of experience in virtual assistance.",
            "Philippines",
        )
        self.assertFalse(passed)

    def test_single_experience_preference_is_not_automatically_rejected(self):
        passed, *_ = score_job(
            "Entry-Level Virtual Assistant",
            "Experience in customer service is preferred. Training provided. Remote Philippines.",
            "Philippines",
        )
        self.assertTrue(passed)

    def test_foreign_only_location_is_rejected(self):
        passed, *_ = score_job(
            "Entry-Level Virtual Assistant",
            "Training provided. Remote role for US residents only.",
            "United States only",
        )
        self.assertFalse(passed)

    def test_duplicate_job_ids_are_removed(self):
        raw = [
            {
                "source": "Test",
                "source_id": "123",
                "title": "Non-Voice Virtual Assistant",
                "company": "Example Co",
                "location": "Philippines",
                "work_type": "remote",
                "description": "Entry level, training provided, chat support.",
                "url": "https://example.com/job/123",
            },
            {
                "source": "Test",
                "source_id": "123",
                "title": "Non-Voice Virtual Assistant",
                "company": "Example Co",
                "location": "Philippines",
                "work_type": "remote",
                "description": "Entry level, training provided, chat support.",
                "url": "https://example.com/job/123",
            },
        ]
        # URL validation would hit the network, so test dedupe using a patched function.
        import job_tracker
        old = job_tracker.validate_application_url
        try:
            job_tracker.validate_application_url = lambda url, source: (True, canonical_url(url))
            df = process_jobs(raw)
        finally:
            job_tracker.validate_application_url = old
        self.assertEqual(len(df), 1)

    def test_canonical_url_rejects_non_http(self):
        self.assertEqual(canonical_url("javascript:alert(1)"), "")
        self.assertEqual(canonical_url("https://example.com/a#section"), "https://example.com/a")


if __name__ == "__main__":
    unittest.main()
