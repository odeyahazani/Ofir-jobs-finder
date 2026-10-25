"""Explainable conservative first-pass scoring, never an industrial-experience claim."""
import re
from datetime import datetime, timezone, timedelta

SENIOR = r"\b(senior|sr\.?|lead|leader|principal|staff|director|manager|head of)\b|בכיר|מנהל|ראש צוות"
ROLE = r"integrat|validat|verific|test|experiment|laborator|optical|optics|photon|imag(?:e|ing)|signal|sensor|measurement|hardware|electronic|electrical|physic|system|r&d|research|algorithm|אינטגרציה|ולידציה|בדיקות|אלקטרו|אופטיקה|פיזיק|מעבדה|מערכות"
SOFTWARE_ONLY = r"\b(backend|frontend|front.end|back.end|full.stack|devops|site reliability|data analyst|data scientist|recruiter|accountant|sales)\b"


def assess(title, description, location, company):
    text = (title + "\n" + description).lower()
    duties = description.lower()
    reasons, gaps = [], []
    exclude = None
    if re.search(SENIOR, title, re.I):
        exclude = "תפקיד בכיר או ניהולי"
    if re.search(r"field service|customer support|technical support|service technician|טכנאי שירות|שירות שטח", title, re.I):
        exclude = "עיקר התפקיד הוא שירות או תמיכה"
    if re.search(SOFTWARE_ONLY, title, re.I):
        exclude = "תפקיד שאינו תואם את מסלול ההנדסה המעשי"

    # Evaluate clauses separately: preferred experience must not cancel a different mandatory requirement.
    mandatory_years, preferred_years = [], []
    clauses = re.split(r"[\n;•]|(?<=[.!?])\s+", duties)
    for clause in clauses:
        matches = re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?\s*\+?\s*(?:years?|yrs?)(?:['’]s?)?", clause) if re.search(r"experience|expertise|minimum|at least|hands.on", clause) else []
        matches += re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?\s*\+?\s*שנות ניסיון", clause)
        for low, _ in matches:
            # A stated minimum is treated as required unless the local clause explicitly says otherwise.
            target = preferred_years if re.search(r"preferred|advantage|nice.to.have|a plus|יתרון|רצוי", clause) else mandatory_years
            target.append(int(low))
    years = max(mandatory_years, default=None)
    if years is not None and years > 3:
        exclude = "דרישת ניסיון של יותר משלוש שנים"
    if re.search(r"(?:must|required|mandatory).{0,70}(?:industrial|industry).{0,30}experience|(?:industrial|industry).{0,30}experience.{0,70}(?:must|required|mandatory)", duties):
        exclude = "ניסיון תעשייתי מפורש כתנאי חובה — דורש בחינה ידנית"
    if re.search(r"(?:ph\.?d|doctorate|msc|m\.sc|master'?s).{0,35}(?:required|mandatory)|(?:required|mandatory).{0,35}(?:ph\.?d|doctorate|master'?s)|תואר שני חובה", duties):
        exclude = "תואר מתקדם נדרש כחובה"
    if re.search(r"\bstudent\b|משרת סטודנט", title, re.I):
        exclude = "משרת סטודנט — אופיר כבר בוגר"
    if re.search(r"mechanical (?:design )?engineer|מהנדס מכונות", title, re.I):
        exclude = "תפקיד שממוקד בהנדסת מכונות ולא במסלול ההשכלה שסופק"

    role_hits = re.findall(ROLE, text, re.I)
    if not role_hits:
        exclude = exclude or "לא נמצאה התאמה לתחומי התפקיד"
    professional = min(30, 10 + len(set(role_hits)) * 4) if role_hits else 0
    entry = bool(re.search(r"junior|entry.level|graduate|no (?:prior )?experience|ללא ניסיון|בוגר", text))
    experience = 25 if entry and (years is None or years <= 1) else 22 if years is not None and years <= 1 else 18 if years == 2 else 12 if years == 3 else 10
    if years is None and not entry:
        gaps.append("דרישת הניסיון אינה ברורה; אין להסיק שהמשרה מתאימה לבוגר")
    elif years is not None and years >= 2:
        gaps.append(f"נדרשות לפחות {years} שנות ניסיון; לאופיר ניסיון אקדמי ולא תעשייתי")
    skills = {"Python": r"python", "MATLAB": r"matlab", "עיבוד אותות/תמונה": r"signal processing|image processing|עיבוד אות|עיבוד תמונ", "מערכות ניסוי ומדידה": r"lab|calibrat|measurement|experiment|מעבד|מדיד|כיול", "אופטיקה ופיזיקה": r"optic|photon|physic|אופט|פיזיק"}
    matched = [name for name, pattern in skills.items() if re.search(pattern, text)]
    technical = min(20, len(matched) * 4)
    if matched:
        reasons.append("חפיפה לרקע האקדמי והמעשי: " + ", ".join(matched))
    if re.search(r"integrat|validat|test|experiment|אינטגרציה|בדיקות", text):
        reasons.append("התפקיד כולל פעילות מערכתית, ניסויית או בדיקות")
    sector = 10 if re.search(r"medical|medtech|biomedical|healthcare|imaging|מכשור רפואי|medical", company["notes"].lower()) else 8 if re.search(r"optic|photon|sensor|semiconductor|defense|physics|robotic", company["notes"].lower()) else 3
    # No travel-time estimate is inferred from the company's address.
    geo = 5 if re.search(r"israel|haifa|caesarea|netanya|yokne|herzliya|tel.aviv|חיפה|קיסריה|נתניה|יקנעם|ישראל|הרצליה|תל אביב|בנימינה|אור עקיבא", location, re.I) else 0
    if not geo:
        exclude = exclude or "מיקום בישראל לא אומת"
    gaps.append("זמן נסיעה ברכב ובתחבורה ציבורית טרם נבדק")
    if re.search(r"\bc\+\+|\bfpga\b|\bpcb\b|\bvhdl\b|\bverilog\b", text):
        gaps.append("מוזכרים כלי חומרה או שפות שלא נכללו בכישורים שסופקו; נדרשת בדיקה")
    breakdown = {"professional": professional, "experience": experience, "technical": technical, "sector": sector, "location": geo, "growth": 0}
    gaps.append("אפשרויות ההתפתחות לא אומתו")
    return {"score": sum(breakdown.values()), "breakdown": breakdown, "reasons": reasons,
            "gaps": gaps, "experience": f"לפחות {years} שנות ניסיון" if years is not None else "רמת כניסה" if entry else "לא צוין בבירור",
            "eligible": not bool(exclude), "exclusion_reason": exclude}


def within_age_limit(value):
    if not value:
        return True
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - timedelta(days=183) <= published <= datetime.now(timezone.utc) + timedelta(days=1)
    except ValueError:
        return True  # retained as unknown by adapters; never relabelled as today's publication
