"""Shared helpers: name normalisation, slugs, quarter maths."""
import re
import unicodedata
from datetime import date

# ---------------------------------------------------------------- quarters

def fy_quarter_start(fy: int, q: int) -> date:
    """First day of federal fiscal-year quarter (FY starts 1 Oct of fy-1)."""
    m = 10 + 3 * (q - 1)
    y = fy - 1
    if m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


def fy_quarter_end(fy: int, q: int) -> date:
    """Last day of a fiscal-year quarter."""
    nfy, nq = (fy, q + 1) if q < 4 else (fy + 1, 1)
    nxt = fy_quarter_start(nfy, nq)
    return date.fromordinal(nxt.toordinal() - 1)


def qindex(fy: int, q: int) -> int:
    return fy * 4 + (q - 1)


def qfrom_index(i: int):
    return i // 4, i % 4 + 1

# ---------------------------------------------------------------- text

_ws = re.compile(r"\s+")


def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def slugify(s: str, maxlen: int = 80) -> str:
    s = ascii_fold(s).lower().replace("&", " and ").replace("+", " plus ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > maxlen:
        s = s[:maxlen].rsplit("-", 1)[0]
    return s or "x"


# Legal-form suffixes and filler stripped when building the employer key.
_EMP_SUFFIX = {
    "LLC", "L L C", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY",
    "LTD", "LIMITED", "LP", "L P", "LLP", "L L P", "PLLC", "PC", "P C", "PA", "PLC",
    "GMBH", "AG", "SA", "NA", "N A", "USA", "US", "U S", "U S A",
}
_EMP_SUFFIX_RE = re.compile(
    r"(?:\s+(?:" + "|".join(sorted((re.escape(s) for s in _EMP_SUFFIX), key=len, reverse=True)) + r"))+$"
)
_DISPLAY_SUFFIX_RE = re.compile(
    r"[\s,]+(?:L\.?\s?L\.?\s?C\.?|INC\.?|INCORPORATED|CORP\.?|CORPORATION|LTD\.?|LIMITED|L\.?L\.?P\.?|L\.?P\.?|P\.?L\.?L\.?C\.?|P\.?C\.?|N\.A\.?)\s*$",
    re.I,
)


def employer_key(name: str) -> str:
    """Upper-case, punctuation-free, legal suffixes removed. 'Google LLC' and
    'GOOGLE, L.L.C.' both become 'GOOGLE'."""
    s = ascii_fold(name or "").upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"\bD/?B/?A\b.*$", "", s)          # drop 'dba ...'
    s = re.sub(r"[.'`]", "", s)                    # L.L.C. -> LLC, Macy's -> MACYS
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = _ws.sub(" ", s).strip()
    s = re.sub(r"^THE\s+", "", s)
    prev = None
    while prev != s:                                # strip stacked suffixes ("CO INC")
        prev = s
        s = _EMP_SUFFIX_RE.sub("", s).strip()
    return s


_SMALL = {"and", "of", "the", "for", "in", "at", "on", "by", "to", "a", "an", "de"}
_KEEP_UPPER = {"IBM", "USA", "US", "LLC", "IT", "AI", "UI", "UX", "QA", "HR", "CEO", "CFO", "CTO",
               "VP", "SAP", "AWS", "NYU", "UCLA", "MIT", "KPMG", "EY", "PWC", "JP", "II", "III",
               "IV", "SQL", "ETL", "BI", "ML", "NYC", "SDE", "SRE", "ERP", "CRM", "HCL", "TCS",
               "EPAM", "LTI", "UBS", "BNY", "DXC", "NTT", "CGI", "ADP", "GE", "AT&T", "ATT",
               "R&D", "PHD", "MD", "RN", "DBA", "GIS", "SOC", "IOS", "API", "CAD", "PLC", "HVAC",
               "ASIC", "FPGA", "SOX", "SEO", "NLP", "AR", "VR", "DO", "LPN", "CPA", "SVP", "AVP"}


def smart_title(s: str) -> str:
    """Title-case an ALL CAPS string but keep acronyms."""
    s = _ws.sub(" ", (s or "").strip())
    if not s:
        return s
    if not (s.isupper() or s.islower()):
        return s  # already mixed case, trust it
    out = []
    for i, w in enumerate(s.split(" ")):
        core = w.strip("(),.-/")
        if core.upper() in _KEEP_UPPER:
            out.append(w.upper())
        elif i > 0 and w.lower() in _SMALL:
            out.append(w.lower())
        elif "." in core and len(core) <= 5 and core.replace(".", "").isalpha():
            out.append(w.upper())
        elif any(ch.isdigit() for ch in core) and any(ch.isalpha() for ch in core):
            out.append(w.upper())
        else:
            out.append("/".join("-".join(p[:1].upper() + p[1:].lower() for p in seg.split("-"))
                                for seg in w.split("/")))
    return " ".join(out)


def employer_display(raw: str) -> str:
    s = _ws.sub(" ", (raw or "").strip()).strip(" ,")
    s = re.sub(r"[\s,]*\b(?:d\s?/\s?b\s?/\s?a|dba)\b.*$", "", s, flags=re.I).strip(" ,") or s
    prev = None
    while prev != s:
        prev = s
        s = _DISPLAY_SUFFIX_RE.sub("", s).strip(" ,")
    return smart_title(s) or smart_title(raw)


_LEVEL_RE = re.compile(r"(?:[\s,/-]+(?:I{1,3}|IV|V|VI{0,3}|[1-6]|L[1-6]|LEVEL\s*[1-6IV]+))+$")


def title_key(title: str) -> str:
    """Normalised job title: lower-case, no parentheses, req ids or trailing level numbers."""
    s = ascii_fold(title or "").upper()
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)      # (SDE II), [12345]
    s = re.sub(r"\s[-–#]\s*\w*\d{3,}\w*\s*$", " ", s)  # '- REQ12345'
    s = re.sub(r"\bSR\b\.?", "SENIOR", s)
    s = re.sub(r"\bJR\b\.?", "JUNIOR", s)
    s = re.sub(r"\bENGR\b\.?", "ENGINEER", s)
    s = re.sub(r"\bDEV\b\.?", "DEVELOPER", s)
    s = re.sub(r"\bMGR\b\.?", "MANAGER", s)
    s = re.sub(r"\bASSOC\b\.?", "ASSOCIATE", s)
    s = re.sub(r"\bASST\b\.?", "ASSISTANT", s)
    s = re.sub(r"[^A-Z0-9+#&/ ]+", " ", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = _ws.sub(" ", s).strip(" /-")
    prev = None
    while prev != s:
        prev = s
        s = _LEVEL_RE.sub("", s).strip(" /-,")
    return s


def city_key(city: str, state: str):
    c = _ws.sub(" ", ascii_fold(city or "").upper().replace(".", "").strip(" ,"))
    c = re.sub(r"^ST\s", "SAINT ", c)
    c = re.sub(r"^FT\s", "FORT ", c)
    c = re.sub(r",.*$", "", c).strip()
    st = (state or "").strip().upper()[:2]
    if not c or not st:
        return None
    return c, st


US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "MP": "Northern Mariana Islands",
    "AS": "American Samoa",
}
