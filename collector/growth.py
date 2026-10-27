"""Select a small number of relevant, supported sources for gradual onboarding."""
import re


def new_sources(db, limit=1):
    if limit < 0 or limit > 5:
        raise ValueError("Expand by 0 to 5 sources at a time")
    ranked = []
    for row in db.execute("SELECT * FROM companies WHERE enabled=0 AND last_checked IS NULL AND career_url<>'' AND NOT EXISTS(SELECT 1 FROM company_monitor_controls m WHERE m.company_id=companies.id AND m.opted_out=1)"):
        company = dict(row)
        notes = company["notes"].lower()
        supported = (company["ats_hint"] == "Greenhouse" and company["ats_identifier"] and re.search(r"https://(job-boards(\.eu)?|boards)\.greenhouse\.io/", company["career_url"])) or (company["ats_hint"] == "Comeet" and re.search(r"https://www\.comeet\.(com|co)/jobs/", company["career_url"]))
        supported = supported or (company["name"] == "Camtek" and company["career_url"].rstrip("/") == "https://www.camtek.com/careers/open-positions")
        if not supported:
            continue
        ofir = bool(re.search(r"ofir|אופיר", notes))
        if not ofir and re.search(r"בעיקר אודיה|strong odeya|odeya target", notes):
            continue
        domain = bool(re.search(r"medical|medtech|optic|photon|sensor|semiconductor|defense|robotic|physics|quantum|hardware|electronic", notes))
        if not (ofir or domain):
            continue
        score = int(ofir) * 5 + int(domain) * 4 + int(bool(re.search(r"קיסריה|בנימינה|אור עקיבא|חיפה|יקנעם|נתניה", company["location_hint"])))
        ranked.append((-score, company["name"].casefold(), company["id"]))
    return [item[2] for item in sorted(ranked)[:limit]]
