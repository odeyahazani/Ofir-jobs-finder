import unittest
from unittest.mock import MagicMock
from collector.camtek import parse_job, collect_camtek, BOARD
from collector.sources import SourceError
from collector.scoring import assess

URL = BOARD + 'TEST.001/'
DOCUMENT = '''<nav>Not a job</nav><main><a>Back to Careers</a><h1>TEST ONLY Integration Engineer</h1><p>R&amp;D</p><p>Migdal Haemek</p><p>Full-time</p><h2>Description</h2><p>Junior engineering integration and optical laboratory testing with Python and MATLAB, electronic sensors, experiments and measurements.</p><h2>Requirements</h2><p>Electrical engineering degree. 0-1 years of experience. Practical laboratory work.</p><button>Apply Now</button></main><footer>Cookie policy and unrelated careers</footer>'''


class CamtekTests(unittest.TestCase):
    def test_actual_posting_location_and_requirements_are_isolated_from_navigation(self):
        job = parse_job(DOCUMENT, URL)
        self.assertEqual(job['location'], 'Migdal Haemek')
        self.assertIsNone(job['published_at'])
        self.assertNotIn('Cookie policy', job['description'])
        self.assertNotIn('Not a job', job['description'])
        self.assertTrue(assess(job['title'], job['description'], job['location'], {'notes': 'semiconductor optics'})['eligible'])

    def test_cosmetic_marker_case_spacing_and_punctuation_are_accepted(self):
        document = DOCUMENT.replace('Back to Careers', 'BACK  TO Careers').replace('Description', 'Description:').replace('Requirements', 'REQUIREMENTS:').replace('Apply Now', 'Apply\u00a0Now')
        self.assertEqual(parse_job(document, URL)['source_id'], 'TEST.001')

    def test_partial_scan_keeps_valid_jobs_and_reports_failed_url(self):
        other = BOARD + 'TEST.002/'
        client = MagicMock()
        client.get.side_effect = [f'<a href="{URL}">First</a><a href="{other}">Second</a>', '<html>Unexpected job layout</html>', DOCUMENT]
        with self.assertRaises(SourceError) as caught:
            collect_camtek({'career_url': BOARD}, client)
        self.assertEqual(len(caught.exception.partial_jobs), 1)
        self.assertIn(URL, caught.exception.message)
        self.assertIn('description', caught.exception.message)
        self.assertEqual(client.get.call_count, 3)

    def test_no_distinct_requirements_section_is_retained_only_for_review(self):
        job = parse_job(DOCUMENT.replace('<h2>Requirements</h2>', ''), URL)
        self.assertEqual(job['status'], 'unverified')
        self.assertTrue(job['requirements_unconfirmed'])
        self.assertIn('Electrical engineering degree', job['description'])

    def test_missing_work_model_stays_unknown_without_losing_location(self):
        job = parse_job(DOCUMENT.replace('<p>Full-time</p>', ''), URL)
        self.assertEqual(job['location'], 'Migdal Haemek')
        self.assertEqual(job['work_model'], 'לא צוין')

    def test_foreign_location_is_not_replaced_with_the_company_address(self):
        job = parse_job(DOCUMENT.replace('Migdal Haemek', 'Bergisch Gladbach'), URL)
        self.assertEqual(job['location'], 'Bergisch Gladbach')
        self.assertFalse(assess(job['title'], job['description'], job['location'], {'notes': 'semiconductor optics'})['eligible'])

    def test_missing_markers_metadata_or_wrong_host_are_not_verified(self):
        for document, url in [(DOCUMENT.replace('Apply Now', 'Closed'), URL), (DOCUMENT, URL.replace('www.camtek.com', 'evil.example'))]:
            with self.assertRaises(SourceError): parse_job(document, url)

    def test_ambiguous_metadata_is_preserved_without_guessing_location(self):
        for document in [DOCUMENT.replace('<p>R&amp;D</p>', ''), DOCUMENT.replace('<p>Migdal Haemek</p>', ''), DOCUMENT.replace('<p>Migdal Haemek</p><p>Full-time</p>', '')]:
            job = parse_job(document, URL)
            self.assertEqual(job['location'], 'מיקום לא ידוע')
            self.assertEqual(job['status'], 'unverified')
            self.assertFalse(assess(job['title'], job['description'], job['location'], {'notes': 'semiconductor optics'})['eligible'])
            self.assertIn('Electrical engineering degree', job['description'])

    def test_only_observed_detail_links_are_fetched_once(self):
        client = MagicMock()
        client.get.side_effect = [f'<a href="{URL}">Job</a><a href="{URL}">Again</a><a href="https://evil.example/careers/open-positions/OTHER/">Other</a>', DOCUMENT]
        jobs = collect_camtek({'career_url': BOARD}, client)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(client.get.call_count, 2)
        self.assertEqual(client.get.call_args.args[0], URL)

    def test_empty_listing_is_unsupported_not_proof_of_zero_jobs(self):
        client = MagicMock(); client.get.return_value = '<html>Careers loading</html>'
        with self.assertRaises(SourceError): collect_camtek({'career_url': BOARD}, client)
