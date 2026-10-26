"""Evidence-based deterministic matching. Professional fit is independent of readiness and availability."""
import json
import re
from pathlib import Path
from .location import in_israel

PROFILE = json.loads((Path(__file__).resolve().parent.parent / 'data/candidate-profile.json').read_text())
VERSION = PROFILE['version']
SENIOR = r'\b(senior|sr\.?|lead|leader|principal|staff|director|manager|head of)\b|בכיר|מנהל|ראש צוות'
OPTIONAL = r'preferred|advantage|nice.to.have|a plus|יתרון|רצוי|not required|not mandatory|לא נדרש|אין צורך'
HEAD_REQUIREMENTS = r'^(?:requirements|qualifications|required qualifications|what you bring|what we.re looking for|experiences, knowledge, skills and abilities|דרישות(?: התפקיד)?)[\s:]*$'
HEAD_OPTIONAL = r'^(?:preferred qualifications|nice to have|great to have|advantages?|יתרונות)[\s:]*$'
HEAD_DUTIES = r'^(?:description|responsibilities|position responsibilities|key responsibilities|what you.ll do|about the role|role overview|תיאור(?: התפקיד)?|תחומי אחריות)[\s:]*$'
ROLE = r'integrat|validat|verific|test(?:ing)? engineer|experimental|laboratory|research engineer|r&d engineer|systems? engineer|application development engineer|electrical engineer|electronics? engineer|hardware engineer|rf engineer|control engineer|optic|physicist|characterization|metrology|algorithm|אינטגרציה|ולידציה|מהנדס.{0,12}בדיקות|מערכות|אופט|פיזיק|אלגורית|בקרה'
FUNCTIONS = [r'integrat|אינטגרציה', r'calibrat|validat|characteriz|כיול|ולידציה', r'experiment|research|scientific|ניסוי|מחקר', r'test|measurement|בדיק|מדיד', r'optic|imaging|signal|image|אופט|תמונ|אותות', r'physical model|data analys|analytic tools|מידול|ניתוח נתונ']
DOMAINS = [r'medical|biomedical|tissue|רפואי|רקמות', r'optic|photon|imaging|sensor|אופט|דימות|חיישנ', r'physical|physics|quantum|semiconductor|פיזיק|מוליכים למחצה']
BACHELOR = r'\b(?:bachelor(?:[’\x27]s)?(?: degree)?|b\.?sc\.?|תואר ראשון)\b'
ADVANCED_DEGREE = r'\b(?:ph\.?d\.?|doctorate|m\.?sc\.?|master[’\x27]?s(?: degree)?|תואר שני)\b'
# Degree abbreviations are part of their requirement, including before Hebrew "or".
CLAUSE_BOUNDARY = r'[;•]|(?<![BMbm]\.[Ss][Cc]\.)(?<![BMbm][Ss][Cc]\.)(?<![Pp][Hh]\.[Dd]\.)(?<![Pp][Hh][Dd]\.)(?<=[.!?])\s+(?=[A-Zא-ת0-9])'


def sections(description):
    duties, requirements = [], []
    mode, has_requirements = 'duties', False
    for raw in description.splitlines():
        line = raw.strip().strip('•- ').strip()
        if not line: continue
        if re.match(HEAD_OPTIONAL, line, re.I): mode = 'optional'; continue
        if re.match(HEAD_REQUIREMENTS, line, re.I): mode, has_requirements = 'required', True; continue
        if re.match(HEAD_DUTIES, line, re.I): mode = 'duties'; continue
        if mode == 'duties': duties.append(line)
        else: requirements.append((line, mode == 'optional'))
    # Remove recognizable corporate boilerplate from positive task evidence only.
    duties = [line for line in duties if not re.search(r'global leader|world.s leading|founded in|about (?:the company|us)|we are a .{0,35}(?:company|startup)', line, re.I)]
    # A headerless source is ambiguous. An optional-only section is not a complete requirements section.
    if not has_requirements: requirements = [(line, False) for line in duties] + requirements
    else:
        # Explicit tenure in the introduction still applies even if a later section has other requirements.
        requirements += [(line, False) for line in duties if re.search(r'\d+\s*(?:[-–]\s*\d+)?\s*\+?\s*(?:years?|yrs?|שנות ניסיון)', line, re.I)]
    return '\n'.join(duties), requirements, has_requirements


def clauses(requirements):
    for line, optional_section in requirements:
        for sentence in re.split(CLAUSE_BOUNDARY, line):
            # A separate preferred skill must not soften a required tenure in the same sentence.
            parts = re.split(r',\s*', sentence) if ',' in sentence and re.search(OPTIONAL, sentence, re.I) else [sentence]
            grouped = []
            for part in parts:
                if grouped and re.fullmatch(r'(?:preferred|an? advantage|a plus|יתרון|רצוי)[.!]?', part.strip(), re.I):
                    grouped[-1] += ', ' + part
                else:
                    grouped.append(part)
            for clause in grouped:
                if clause.strip(): yield clause.strip(), optional_section or bool(re.search(OPTIONAL, clause, re.I))


def assess(title, description, location, company):
    duties, requirements, has_requirements = sections(description)
    pairs = list(clauses(requirements))
    positive = title + '\n' + duties
    skill_text = positive + '\n' + '\n'.join(line for line, _ in pairs)
    family = bool(re.search(ROLE, title, re.I))
    function_hits = [pattern for pattern in FUNCTIONS if re.search(pattern, positive, re.I)]
    professional = min(45, (20 if family else 0) + 5 * len(function_hits))
    evidence = []
    for capability in PROFILE['capabilities']:
        match = re.search(capability['pattern'], skill_text, re.I)
        if match:
            evidence.append({'capability': capability['id'], 'label': capability['label'], 'level': capability['level'],
                             'evidence_ids': capability['evidence'], 'profile_evidence': [PROFILE['evidence'][id] for id in capability['evidence']],
                             'job_quote': next((line.strip()[:500] for line in (duties + '\n' + '\n'.join(line for line, _ in pairs) + '\n' + title).splitlines() if re.search(capability['pattern'], line, re.I)), ''), 'points': capability['points']})
    technical = min(35, sum(item['points'] for item in evidence))
    # Company sector is context only. It cannot establish task suitability or remove a requirement gap.
    domain_text = skill_text + '\n' + dict(company).get('notes', '')
    sector = min(20, sum(7 for pattern in DOMAINS if re.search(pattern, domain_text, re.I)))
    score = professional + technical + sector
    gaps, blockers, checks = [], [], []
    if re.search(SENIOR, title, re.I): blockers.append('תפקיד בכיר או ניהולי')
    if re.search(r'\bstudent\b|משרת סטודנט', title, re.I): blockers.append('משרת סטודנט — אופיר כבר בוגר')
    if re.search(r'field service|customer support|technical support|customer success|support engineer|service technician|טכנאי שירות|שירות שטח', title, re.I): blockers.append('עיקר התפקיד הוא שירות או תמיכה')
    if re.search(r'\b(?:backend|frontend|full.stack|devops|site reliability|data scientist|data analyst|machine learning engineer|deep learning engineer|recruiter|accountant|sales|buyer|warehouse|backoffice|back.office|order admin)\b|קניין|מחסנא|אחזקה|מלחימ|עובד.{0,4}יצור', title, re.I): blockers.append('תפקיד מחוץ למיקוד ההנדסי־ניסויי')
    if re.search(r'mechanical (?:design |practical )?engineer|מהנדס מכונות', title, re.I): blockers.append('תפקיד שממוקד בהנדסת מכונות ולא במסלול ההשכלה שסופק')
    if not family and len(function_hits) < 2: blockers.append('לא זוהו מספיק משימות הנדסיות־ניסויות בתפקיד עצמו')
    if score < 40: blockers.append('לא זוהה חיבור מקצועי מספיק לרקע המתועד')
    years = []
    requirement_checks = []
    for clause, optional in pairs:
        numbers = []
        if re.search(r'experience|expertise|minimum|at least|hands.on|years?\s+in\s+(?:hardware|software|engineering|verification|validation|failure analysis)|ניסיון', clause, re.I):
            matches = re.findall(r'(?<!\w)\+?(\d{1,2})\s*(?:[-–]\s*\d+)?\s*\+?\s*(?:years?|yrs?)(?:[’\x27]s?)?|(?<!\w)(\d{1,2})\s*(?:[-–]\s*\d+)?\s*\+?\s*שנות ניסיון', clause, re.I)
            numbers = [int(value) for match in matches for value in match if value]
        if numbers:
            minimum = max(numbers)
            requirement_checks.append({'kind': 'experience', 'quote': clause[:500], 'optional': optional, 'minimum_years': minimum})
            if not optional: years.append(minimum)
        if optional: continue
        if re.search(r'(industrial|industry) experience.{0,70}(must|required|mandatory)|(must|required|mandatory).{0,70}(industrial|industry) experience', clause, re.I):
            blockers.append('ניסיון תעשייתי מפורש כתנאי חובה — אינו מתועד בפרופיל')
            requirement_checks.append({'kind': 'unsupported_requirement', 'quote': clause[:500], 'label': 'ניסיון תעשייתי חובה', 'optional': False})
        either = r'.{0,60}?(?:\bor\b|\bאו\b|/)\s*(?:an?\s+)?'
        degree_alternative = re.search(BACHELOR + either + ADVANCED_DEGREE + '|' + ADVANCED_DEGREE + either + BACHELOR, clause, re.I)
        if re.search(ADVANCED_DEGREE, clause, re.I) and not degree_alternative:
            blockers.append('תואר מתקדם נדרש כחובה')
            requirement_checks.append({'kind': 'unsupported_requirement', 'quote': clause[:500], 'label': 'תואר מתקדם', 'optional': False})
        critical = [name for name, pattern in [('SystemVerilog/UVM', r'systemverilog|\buvm\b'), ('כלי סימולציית VLSI', r'\bvcs\b|xcelium|questa'), ('תכנון PCB עצמאי', r'pcb.{0,35}(design|layout)|board design'), ('Zemax', r'zemax'), ('ניסיון רגולטורי', r'iso\s*13485|iec\s*60601')]
                    if re.search(pattern, clause, re.I)]
        for skill in critical:
            reason = f'דרישה מרכזית שאינה מתועדת: {skill}'
            blockers.append(reason)
            requirement_checks.append({'kind': 'unsupported_requirement', 'quote': clause[:500], 'label': skill, 'optional': False})
        if re.search(r'semiconductor (?:fabrication|manufacturing)|inspection workflows|תהליכי ייצור.{0,20}מוליכים', clause, re.I):
            checks.append('היכרות עם תהליכי ייצור ובדיקה של מוליכים למחצה אינה מתועדת — יש לברר')
            requirement_checks.append({'kind': 'knowledge_to_check', 'quote': clause[:500], 'optional': False})
        if re.search(r'c\+\+', clause, re.I):
            checks.append('C++ מתועד ברמה אקדמית בלבד; יש לברר את עומק הפיתוח הנדרש')
            requirement_checks.append({'kind': 'knowledge_to_check', 'quote': clause[:500], 'label': 'C++ אקדמי', 'optional': False})
        if re.search(r'fpga|firmware|embedded', clause, re.I):
            checks.append('לא מתועדת מומחיות ב־FPGA או Firmware; יש לברר אם זה תנאי חובה או ידע שניתן ללמוד')
            requirement_checks.append({'kind': 'knowledge_to_check', 'quote': clause[:500], 'label': 'FPGA / Firmware', 'optional': False})
        if re.search(r'(?:experience|expert|proficien|hands.on).{0,45}(?:machine learning|deep learning)|(?:machine learning|deep learning).{0,45}(?:experience|expert|proficien)', clause, re.I):
            checks.append('למידת מכונה מתועדת כלימוד עצמי בלבד; לא מתועד ניסיון מקצועי בתחום')
            requirement_checks.append({'kind': 'knowledge_to_check', 'quote': clause[:500], 'label': 'למידת מכונה', 'optional': False})
        if re.search(r'(?:expert|advanced|strong|proficien).{0,35}python|python.{0,35}(?:expert|advanced|proficien)', clause, re.I) and not re.search(r'matlab.{0,15}(?:or|או).{0,15}python|python.{0,15}(?:or|או).{0,15}matlab', clause, re.I):
            checks.append('Python מתועד לבקרה ולניתוח בפרויקט; עומק פיתוח התוכנה הנדרש דורש בירור')
            requirement_checks.append({'kind': 'knowledge_to_check', 'quote': clause[:500], 'label': 'עומק הפיתוח ב־Python', 'optional': False})
    minimum = max(years, default=None)
    if minimum is not None and minimum >= 3:
        blockers.append(f'דרישת ניסיון של {minimum} שנים ומעלה — לא מתועד ניסיון הנדסי תעשייתי')
    elif minimum:
        checks.append(f'נדרשות לפחות {minimum} שנות ניסיון; שני פרויקטים אינם שקולים לשנות ניסיון מקצועי')
    entry = bool(re.search(r'\bjunior\b|entry.level|new graduates?|recent graduates?|no (?:prior )?experience|ללא ניסיון|בוגר', title + '\n' + duties, re.I))
    research = any(item['capability'] == 'research' for item in evidence)
    if minimum is None and not entry and not research:
        checks.append('רמת הניסיון אינה מפורשת; אין להסיק שמדובר במשרת כניסה')
    if not has_requirements:
        checks.append('לא זוהה סעיף דרישות מובחן; יש לבדוק את שלמות הדרישות במקור')
    israel = in_israel(location)
    if not israel: checks.append('מיקום בישראל לא אומת')
    gaps.extend(blockers + checks)
    gaps.append('זמן הנסיעה מפרדס חנה ברכב ובתחבורה ציבורית טרם אומת')
    reasons = [f'{item["label"]} — ' + ', '.join(PROFILE['evidence_titles'][id] for id in item['evidence_ids']) for item in evidence]
    if re.search(r'travel|נסיעות', description, re.I): reasons.append('נסיעות לחו״ל מתאימות להעדפה שנמסרה; יש לבדוק שעיקר התפקיד אינו שירות באתר לקוח')
    category = 'gap' if blockers or score < 40 else 'review' if checks or score < 70 else 'priority'
    eligible = not blockers and israel
    details = {'version': VERSION, 'category': category, 'evidence': evidence, 'requirements': requirement_checks,
               'blockers': list(dict.fromkeys(blockers)), 'checks': list(dict.fromkeys(checks)), 'location_in_israel': israel,
               'experience_basis': 'academic_and_project_only', 'mandatory_years': minimum}
    return {'score': score, 'breakdown': {'professional': professional, 'technical': technical, 'sector': sector},
            'reasons': list(dict.fromkeys(reasons)), 'gaps': list(dict.fromkeys(gaps)),
            'experience': f'לפחות {minimum} שנות ניסיון' if minimum is not None else 'רמת כניסה מפורשת' if entry else 'לא צוין בבירור',
            'eligible': eligible, 'exclusion_reason': blockers[0] if blockers else None if israel else 'מיקום בישראל לא אומת',
            'match_category': category, 'match_version': VERSION, 'match_details': details}


def exclude(assessment, reason, *, uncertain=False):
    # A source/publication policy may add a restriction, never erase an existing requirement gap.
    category = 'gap' if not uncertain or assessment['match_category'] == 'gap' else 'review'
    assessment.update(eligible=False, match_category=category, exclusion_reason=reason)
    assessment['match_details']['category'] = category
    target = 'checks' if uncertain else 'blockers'
    if reason not in assessment['match_details'][target]: assessment['match_details'][target].append(reason)
    if reason not in assessment['gaps']: assessment['gaps'].append(reason)
    return assessment
