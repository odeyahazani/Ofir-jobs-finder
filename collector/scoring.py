"""Profile matching entry point and publication window shared by collectors."""
from datetime import datetime, timezone, timedelta


def assess(title, description, location, company):
    from .matching import assess as profile_assess
    return profile_assess(title, description, location, company)


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
