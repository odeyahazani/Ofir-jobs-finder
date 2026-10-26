import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from collector.audit import report
from collector.store import connect, seed, save_job
from collector.scoring import assess


class AuditTests(unittest.TestCase):
    def test_report_distinguishes_score_gates_and_preserves_all_data(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / 'audit.sqlite')
            seed(db)
            company = db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
            job = {'source_id': 'audit-fixture', 'title': 'TEST ONLY Integration Engineer', 'description': 'Integration calibration testing, MATLAB.', 'location': 'Haifa, Israel', 'url': 'https://example.com/audit', 'status': 'open'}
            with db: save_job(db, company['id'], job, assess(job['title'], job['description'], job['location'], company))
            before = '\n'.join(db.iterdump())
            output = io.StringIO()
            with contextlib.redirect_stdout(output): report(db)
            self.assertEqual('\n'.join(db.iterdump()), before)
            self.assertIn('Total: 138; monitoring enabled: 8', output.getvalue())
            self.assertIn('Israeli location rule: 1 -> eligible: 1 -> score >=70: 0', output.getvalue())
            self.assertIn('No source requests', output.getvalue())
            db.close()
