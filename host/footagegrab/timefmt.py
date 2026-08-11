"""Time parsing and formatting shared by naming, section args, and the router."""


def parse_time(value):
    """Accept seconds (int/float/str) or clock strings like '1:18' / '01:02:03.5'.

    Returns seconds as float. Raises ValueError on anything unparseable or negative.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a time: {value!r}")
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise ValueError(f"negative time: {value!r}")
        return seconds

    text = str(value).strip()
    if not text:
        raise ValueError("empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"not a time: {value!r}")
    seconds = 0.0
    for part in parts:
        part = part.strip()
        if not part:
            raise ValueError(f"not a time: {value!r}")
        try:
            n = float(part)
        except ValueError:
            raise ValueError(f"not a time: {value!r}") from None
        if n < 0:
            raise ValueError(f"negative time: {value!r}")
        seconds = seconds * 60 + n
    return seconds


def fmt_clock(seconds):
    """Display form: 78.4 -> '1:18', 3723 -> '1:02:03'."""
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_file(seconds):
    """Filename-safe form: 78.4 -> '01.18', 3723 -> '1.02.03' (no colons)."""
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}.{m:02d}.{s:02d}"
    return f"{m:02d}.{s:02d}"


def fmt_section(seconds):
    """yt-dlp --download-sections form: plain seconds, one decimal, no trailing zero."""
    seconds = max(0.0, float(seconds))
    text = f"{seconds:.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text
