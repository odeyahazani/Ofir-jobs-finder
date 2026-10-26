import contextlib
import io
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest

from collector.matching import assess, exclude, VERSION
from collector.matching_review import preview, rescore
from collector.store import connect, seed, save_job
from collector import cli

LAB = 'Description\nJunior optical integration engineer. Calibration, laboratory measurements, structured experiments, MATLAB and Python, image processing and physical models.\nRequirements\nBSc in electrical engineering or physics.\n0-1 years of experience.'
COMPANY = {'notes': 'Medical imaging and optical sensors'}


class MatchingTests(unittest.TestCase):
    def match(self, requirements='', title='Junior Integration Engineer', location='Haifa, Israel', body=LAB):
        return assess(title, body + '\n' + requirements, location, COMPANY)

    def test_research_projects_supply_specific_evidence_without_industry_tenure(self):
        result = self.match()
        self.assertEqual(result['match_category'], 'priority')
        self.assertEqual(result['match_version'], VERSION)
        self.assertEqual(sum(result['breakdown'].values()), result['score'])
        self.assertEqual(result['match_details']['experience_basis'], 'academic_and_project_only')
        matlab = next(e for e in result['match_details']['evidence'] if e['capability'] == 'matlab')
        self.assertEqual(matlab['evidence_ids'], ['sfdi', 'ct'])
        self.assertTrue(all('פרויקט' in e for e in matlab['profile_evidence']))
        self.assertIn('MATLAB', matlab['job_quote'])

    def test_camtek_research_fit_is_separate_from_semiconductor_knowledge(self):
        result = self.match(title='Application Development Engineer', location='Migdal Haemek', body=Path('tests/fixtures/camtek-application.txt').read_text())
        self.assertGreaterEqual(result['score'], 70)
        self.assertEqual(result['match_category'], 'review')
        self.assertTrue(result['eligible'])
        self.assertIsNone(result['match_details']['mandatory_years'])
        self.assertTrue(any('מוליכים למחצה' in check for check in result['match_details']['checks']))
        self.assertTrue(any('נסיעות לחו״ל' in r for r in result['reasons']))
        self.assertFalse(any('Python' in check for check in result['match_details']['checks']))

    def test_real_requirement_examples_do_not_become_priority_through_high_score(self):
        cases = [
            ('מהנדס/ת בקרה', '3-5 years of controls experience required.'),
            ('Validation Engineer- Quantum Control Systems', '3+ years of professional Python experience MUST.'),
            ('VLSI Verification Engineer', '1-2 years of verification experience.\nSystemVerilog, UVM and VCS required.'),
            ('Failure Analysis and Quality Control Team Leader', '2 years experience.'),
        ]
        for title, requirements in cases:
            with self.subTest(title=title):
                result = self.match(requirements, title=title)
                self.assertGreaterEqual(result['score'], 60)
                self.assertEqual(result['match_category'], 'gap')
                self.assertFalse(result['eligible'])

    def test_two_years_is_review_and_not_industrial_credit_from_two_projects(self):
        result = self.match('2+ years of experience in integration.')
        self.assertEqual(result['match_category'], 'review')
        self.assertTrue(result['eligible'])
        self.assertIn('אינם שקולים', ' '.join(result['gaps']))

    def test_three_years_is_hard_gap_even_with_explicit_junior_title(self):
        self.assertEqual(self.match('At least 3 years experience.')['match_category'], 'gap')
        self.assertEqual(self.match(body=LAB.replace('Description\n', 'Description\nAt least 3 years of experience in Python required.\n'))['match_category'], 'gap')

    def test_unsupported_core_tools_are_gaps_but_optional_tools_are_not(self):
        for requirement in ['SystemVerilog / UVM', 'PCB design', 'Zemax', 'ISO 13485', 'IEC 60601']:
            with self.subTest(requirement=requirement):
                self.assertEqual(self.match(requirement)['match_category'], 'gap')
                self.assertEqual(self.match(requirement + ' is an advantage.')['match_category'], 'priority')

    def test_optional_section_and_alternative_academic_degree(self):
        result = self.match('BSc or MSc in Physics.\nPreferred Qualifications\nPhD\n5 years of experience\nUVM')
        self.assertEqual(result['match_category'], 'priority')
        self.assertTrue(any(req['optional'] for req in result['match_details']['requirements']))
        self.assertEqual(self.match('MSc in Physics.')['match_category'], 'gap')

    def test_degree_abbreviations_preserve_real_alternatives_and_original_quotes(self):
        degree_lines = [
            'B.Sc. או M.Sc. בהנדסת חשמל, הנדסת מכונות או תחום רלוונטי',
            'B.Sc. Or M.Sc. in Electrical Engineering.',
            'B.Sc. / M.Sc. in Physics.',
            "Bachelor's or Master's degree in Physics.",
            'M.Sc. או B.Sc. בפיזיקה',
        ]
        for degree in degree_lines:
            with self.subTest(degree=degree):
                result = self.match(degree)
                self.assertEqual(result['match_category'], 'priority')
                self.assertNotIn('תואר מתקדם נדרש כחובה', result['match_details']['blockers'])
        result = self.match(degree_lines[0] + '\n3–5 שנות ניסיון בהנדסת בקרה או בפיתוח אלגוריתמי בקרה')
        self.assertEqual(result['match_category'], 'gap')
        self.assertFalse(any('תואר מתקדם' in item for item in result['match_details']['blockers']))
        self.assertEqual(result['match_details']['mandatory_years'], 3)

    def test_advanced_degree_required_or_both_degrees_is_not_softened(self):
        for requirement in [
            'M.Sc./PhD in Electrical Engineering, Computer Science, Physics, or a related field. – Must',
            'Both a B.Sc. and M.Sc. are required.',
            "Bachelor's and Master's degree required.",
            'Ph.D. in Physics required.',
            "Bachelor's in Physics or EE, Master's degree required.",
        ]:
            with self.subTest(requirement=requirement):
                result = self.match(requirement)
                self.assertIn('תואר מתקדם נדרש כחובה', result['match_details']['blockers'])
                self.assertTrue(any(item['quote'] == requirement for item in result['match_details']['requirements']))

    def test_optional_degree_does_not_cancel_a_following_numbered_tenure(self):
        result = self.match('M.Sc. preferred. 3 years of professional experience required.')
        self.assertEqual(result['match_category'], 'gap')
        self.assertEqual(result['match_details']['mandatory_years'], 3)
        self.assertNotIn('תואר מתקדם נדרש כחובה', result['match_details']['blockers'])

    def test_required_and_preferred_requirements_remain_separate(self):
        for requirement in ['4 years of experience required.\nMATLAB preferred.', '4 years experience required, MATLAB preferred.', '4 years experience, MATLAB preferred.']:
            with self.subTest(requirement=requirement):
                self.assertEqual(self.match(requirement)['match_category'], 'gap')
        self.assertEqual(self.match('5 years experience, preferred.')['match_category'], 'priority')

    def test_academic_cpp_and_project_python_are_not_professional_expertise(self):
        for requirement in ['Proficiency in C++.', 'Advanced Python expertise.', 'Hands-on experience with machine learning.']:
            with self.subTest(requirement=requirement):
                self.assertEqual(self.match(requirement)['match_category'], 'review')

    def test_title_and_company_buzzwords_do_not_create_engineering_fit(self):
        result = self.match(title='Office Administrator', body='Description\nWe are a global leader in optical integration, laboratory experiments, Python and MATLAB.\nManage meeting rooms and office supplies.\nRequirements\nOrganizational skills.')
        self.assertEqual(result['match_category'], 'gap')
        self.assertEqual(result['breakdown']['professional'], 0)
        self.assertFalse(result['match_details']['evidence'])

    def test_software_service_mechanical_and_senior_roles_have_gaps(self):
        for title in ['Senior Optical Engineer', 'Field Service Engineer', 'Backend Engineer', 'Mechanical Practical Engineer']:
            with self.subTest(title=title):
                self.assertEqual(self.match(title=title)['match_category'], 'gap')

    def test_location_is_only_from_posting_and_mixed_locations_are_not_local(self):
        for location in ['Remote', 'Haifa or Berlin', 'Worldwide, including Israel', 'Israel / US', 'Haifaville']:
            with self.subTest(location=location):
                result = self.match(location=location)
                self.assertFalse(result['eligible'])
                self.assertNotEqual(result['match_category'], 'priority')
        self.assertTrue(self.match(location='Rehovot')['eligible'])

    def test_commute_unknown_does_not_create_a_fictitious_travel_estimate(self):
        result = self.match()
        self.assertIn('טרם אומת', result['gaps'][-1])
        self.assertNotIn('location', result['breakdown'])

    def test_headerless_requirements_and_unknown_tenure_are_review(self):
        result = self.match(body='Optical integration, calibration, measurements and MATLAB.', title='Integration Engineer')
        self.assertEqual(result['match_category'], 'review')
        self.assertTrue(any('סעיף דרישות' in gap for gap in result['gaps']))
        result = self.match(body=LAB.replace('Requirements', 'Preferred qualifications'))
        self.assertEqual(result['match_category'], 'review')

    def test_extractor_restriction_cannot_hide_known_hard_requirement(self):
        result = exclude(self.match('4 years of experience required.'), 'דרישות המשרה לא חולצו', uncertain=True)
        self.assertEqual(result['match_category'], 'gap')
        self.assertEqual(result['match_details']['category'], 'gap')


class MatchingDataTests(unittest.TestCase):
    def test_old_sqlite_schema_upgrades_without_touching_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.sqlite'
            old = sqlite3.connect(path)
            schema = Path('data/schema.sql').read_text().replace(
                ",\n match_category TEXT DEFAULT 'unassessed', match_version TEXT DEFAULT '', match_details TEXT DEFAULT '{}'", '')
            old.executescript(schema)
            self.assertNotIn('match_category', [row[1] for row in old.execute('PRAGMA table_info(jobs)')])
            old.close()
            upgraded = connect(path)
            self.assertIn('match_details', [row[1] for row in upgraded.execute('PRAGMA table_info(jobs)')])
            upgraded.close()

    def test_preview_is_read_only_and_rescore_preserves_source_feedback_and_events(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / 'review.sqlite')
            seed(db)
            company = db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
            job = {'source_id': 'profile-test', 'title': 'Junior Integration Engineer', 'description': LAB, 'location': 'Haifa, Israel', 'url': 'https://example.com/profile-test', 'status': 'open'}
            with db:
                save_job(db, company['id'], job, assess(job['title'], job['description'], job['location'], company))
                db.execute("UPDATE jobs SET score=40,match_version='',match_category='unassessed',match_details='{}',last_verified_at='2024-01-01T00:00:00+00:00',fit='yes',familiar=1,application_status='applied',personal_note='keep note',user_updated_at='2026-01-01'")
            before = '\n'.join(db.iterdump())
            with contextlib.redirect_stdout(io.StringIO()):
                preview(db, Path(folder) / 'report.json')
            self.assertEqual('\n'.join(db.iterdump()), before)
            old = dict(db.execute('SELECT * FROM jobs').fetchone())
            events = [tuple(row) for row in db.execute('SELECT * FROM job_events')]
            with contextlib.redirect_stdout(io.StringIO()): rescore(db)
            updated = dict(db.execute('SELECT * FROM jobs').fetchone())
            changed = {key for key in old if old[key] != updated[key]}
            self.assertLessEqual(changed, {'score', 'breakdown', 'reasons', 'gaps', 'experience', 'eligible', 'exclusion_reason', 'match_category', 'match_version', 'match_details'})
            self.assertEqual(updated['match_category'], 'priority')
            self.assertEqual(events, [tuple(row) for row in db.execute('SELECT * FROM job_events')])
            self.assertEqual(updated['last_verified_at'], old['last_verified_at'])
            self.assertEqual(updated['personal_note'], 'keep note')
            self.assertEqual(json.loads(updated['match_details'])['version'], VERSION)
            db.close()

    def test_digest_excludes_high_score_review_and_gap_records(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / 'digest.sqlite'); seed(db)
            company = db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
            with db:
                for category in ['priority', 'review', 'gap']:
                    job = {'source_id': category, 'title': 'Junior Integration Engineer '+category, 'description': LAB, 'location': 'Haifa, Israel', 'url': 'https://example.com/'+category, 'status': 'open'}
                    assessment = assess(job['title'], job['description'], job['location'], company)
                    assessment.update(match_category=category, score=90)
                    save_job(db, company['id'], job, assessment)
            output = io.StringIO()
            with contextlib.redirect_stdout(output): cli.digest(db)
            self.assertIn('Engineer priority', output.getvalue())
            self.assertNotIn('Engineer review', output.getvalue())
            self.assertNotIn('Engineer gap', output.getvalue())
            db.close()
