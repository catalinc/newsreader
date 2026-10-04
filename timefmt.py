from datetime import UTC, datetime


def time_ago(then: datetime, now: datetime | None = None) -> str:
    """Describe how long ago `then` was, e.g. "3 days ago" or "a year ago"."""
    seconds = ((now or datetime.now(UTC)) - then).total_seconds()
    if seconds < 45:
        return "just now"

    minutes = round(seconds / 60)
    if minutes < 45:
        return "a minute ago" if minutes <= 1 else f"{minutes} minutes ago"

    hours = round(seconds / 3600)
    if hours < 22:
        return "an hour ago" if hours <= 1 else f"{hours} hours ago"

    days = round(seconds / 86400)
    if days <= 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return "a week ago" if weeks == 1 else f"{weeks} weeks ago"
    if days < 365:
        months = min(days // 30, 11)
        return "a month ago" if months == 1 else f"{months} months ago"

    years = days // 365
    return "a year ago" if years == 1 else f"{years} years ago"
