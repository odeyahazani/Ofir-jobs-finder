import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
from collector.probe import ats_references, page_evidence, report
from collector.sources import SourceError
from collector.store import connect, seed


class ProbeTests(unittest.TestCase):
    def test_reports_only_supported_public_board_paths_without_tokens(self):
        document = '''<iframe src="https://www.comeet.com/jobs/example/AB.001/?token=private"></iframe>
        <a href="https://job-boards.greenhouse.io/example/jobs/123?secret=private">Jobs</a>
        <a href="https://evil.example/jobs/example/AB.001">Other</a>'''
        self.assertEqual(ats_references(document), ['https://job-boards.greenhouse.io/example', 'https://www.comeet.com/jobs/example/AB.001'])

    def test_evidence_includes_visible_jobs_and_removes_scripts_credentials_and_query_values(self):
        document = '<h2>מהנדס בדיקות</h2><div class="career-positions">Open positions</div><script>private_script_token</script><iframe src="https://jobs.example.com/board?token=private_query_token"></iframe><a href="https://user:private_password@jobs.example.com">Bad</a>'
        evidence = page_evidence(document, 'https://example.com/careers')
        self.assertIn('מהנדס בדיקות', evidence['text'])
        self.assertIn('career-positions', evidence['layout_markers'])
        self.assertIn({'tag': 'iframe', 'url': 'https://jobs.example.com/board', 'query_keys': ['token']}, evidence['resources'])
        self.assertNotIn('private_', str(evidence))

    def test_probe_reports_blocked_sources_separately_and_never_changes_monitoring(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / 'probe.sqlite'); seed(db)
            before = '\n'.join(db.iterdump())
            def factory(company):
                client = MagicMock()
                if company['name'] == 'Camtek': client.get.side_effect = SourceError('blocked', 'HTTP 403')
                else: client.get.return_value = '<html>No structured records here</html>'
                return client
            output = io.StringIO()
            with contextlib.redirect_stdout(output): report(db, factory, output=Path(folder) / "review.json")
            self.assertTrue((Path(folder) / "review.json").is_file())
            self.assertEqual(before, '\n'.join(db.iterdump()))
            self.assertIn('"status": "blocked"', output.getvalue())
            self.assertIn('"jobposting_records_on_page": 0', output.getvalue())
            self.assertNotIn('"status": "empty"', output.getvalue())
            db.close()
