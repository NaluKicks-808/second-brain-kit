"""find_rank.py - the keyword ranking behind find.py. Standard library only.

    import find_rank
    terms = find_rank.usable_terms(["who", "runs", "the", "building", "Lisbon?"])  # -> runs, building, lisbon
    order = find_rank.bm25_order([(rel, text), ...], terms, n_files)               # indices, best first

BM25 with k1 1.2 and b 0.75 over substring counts of each term; a term found in the
file's H1 title or its path adds 2 x idf. The rarer a term is across the files searched, the
more it counts; repeated mentions add less and less; a long file is not favoured for being
long. No model, no index, nothing to install, so it runs anywhere and in any scheduled job.
Plain mention counts let the longest ledgers win; this does not.

System pages (underscore files and log.md: the ledger, the features list, postmortems, the log)
are long by design, so length normalisation buries them, and sessions do search for rows inside
them. find.py lists them in a block of their own ranked by raw hits; `is_system` decides which.
`ARTICLE_UNDERSCORE` names any underscore page that is really an article, so it competes with
the articles (empty by default).
"""
import math
import re

K1, B, TITLE_BOOST = 1.2, 0.75, 2.0

# A small English stoplist.
STOPWORDS = frozenset(
    "the a an and or of in on for to with at by from is was his her its it as that this "
    "what how who why when vs not".split())
MIN_LEN = 3
SHORT = 2          # a term this short is matched as a whole word, never inside another word
_EDGE = re.compile(r"^[^\w'&-]+|[^\w'&-]+$")   # \w is Unicode: "café" keeps its é
ARTICLE_UNDERSCORE = frozenset()


def usable_terms(raw_terms):
    """The search terms find.py ranks with, from its command-line words.

    Each argument is one term, lowercased; a quoted multi-word argument stays one phrase.
    Surrounding punctuation is trimmed ("lisbon?" -> "lisbon"; letters outside ASCII are letters).
    Stopwords and words under three letters are dropped, unless that would leave nothing (so `find.py the` still searches for "the") - except that a
    two-letter word typed with a capital ("AI", "QA") is an acronym and is kept; it is matched
    as a whole word (see `count`). Duplicates collapse, first one wins.
    """
    cleaned, acronyms = [], set()
    for raw in raw_terms:
        t = " ".join(raw.split())
        if not t:
            continue
        if " " not in t:
            t = _EDGE.sub("", t) or t
        if len(t) == SHORT and any(c.isupper() for c in t):
            acronyms.add(t.lower())
        cleaned.append(t.lower())
    cleaned = list(dict.fromkeys(cleaned))
    kept = [t for t in cleaned if " " in t or t not in STOPWORDS and
            (len(t) >= MIN_LEN or t in acronyms)]
    return kept or cleaned


_SHORT_RE = {}


def _short_re(term):
    r = _SHORT_RE.get(term)
    if r is None:
        r = _SHORT_RE[term] = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)")
    return r


def count(low, term):
    """Occurrences of a term in lowercased text: a substring count, 
    except a term of two letters or fewer, which counts only as a whole word ("ai" in "said"
    is not a hit)."""
    if len(term) <= SHORT:
        return len(_short_re(term).findall(low))
    return low.count(term)


def contains(low, term):
    return bool(_short_re(term).search(low)) if len(term) <= SHORT else term in low


def pattern(terms):
    """One regex that finds any term in a line, with the same whole-word rule for short terms."""
    parts = [(r"(?<!\w)" + re.escape(t) + r"(?!\w)") if len(t) <= SHORT else re.escape(t) for t in terms]
    return re.compile("|".join(parts), re.I)


def hits(low, terms):
    """Raw substring hits of the terms in already-lowercased text (the number find.py prints)."""
    return sum(count(low, t) for t in terms)


def title_of(text, rel):
    """The H1 title plus the path, lowercased: where a term earns the title boost."""
    m = re.search(r"^# (.+)$", text, re.M)
    return ((m.group(1) if m else "") + " " + rel).lower()


def bm25_scores(docs, terms, n_files, lows=None):
    """BM25 + title boost for every doc that mentions a term. docs = [(rel, text)].

    Returns {doc index: score} for the docs with at least one hit. `n_files` is how many files
    were searched in all (the idf's N). The average length is over the matching docs.
    `lows` (the texts already lowercased) saves a benchmark re-lowering the corpus per query.
    """
    if lows is None:
        lows = [t.lower() for _, t in docs]
    found = [i for i, low in enumerate(lows) if any(contains(low, w) for w in terms)]
    if not found:
        return {}
    n_files = max(n_files, 1)
    lens = {i: max(1, len(lows[i].split())) for i in found}
    avg = sum(lens.values()) / len(found)
    df = {w: sum(1 for i in found if contains(lows[i], w)) for w in terms}
    out = {}
    for i in found:
        low = lows[i]
        ttl = title_of(docs[i][1], docs[i][0])
        s = 0.0
        for w in terms:
            tf = count(low, w)
            if not tf:
                continue
            idf = math.log(1 + (n_files - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * (tf * (K1 + 1)) / (tf + K1 * (1 - B + B * lens[i] / avg))
            if contains(ttl, w):
                s += idf * TITLE_BOOST
        out[i] = s
    return out


def bm25_order(docs, terms, n_files, lows=None):
    """Indices of the docs that mention a term, best first; ties keep input order."""
    sc = bm25_scores(docs, terms, n_files, lows)
    return sorted(sc, key=lambda i: (-sc[i], i))


def is_system(rel):
    """Underscore files (except the story bank) and log.md: the ledgers find.py lists apart."""
    base = rel.replace("\\", "/").rsplit("/", 1)[-1]
    if base in ARTICLE_UNDERSCORE:
        return False
    return base.startswith("_") or base == "log.md"
