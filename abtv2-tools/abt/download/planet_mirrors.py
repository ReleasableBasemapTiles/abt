"""
planet_mirrors.py

Synchronous port of openmaptiles-tools' download-osm multi-mirror discovery
strategy (https://github.com/openmaptiles/openmaptiles-tools/blob/master/bin/download-osm),
adapted to this project's conventions -- `requests` + a `ThreadPoolExecutor`
instead of `aiohttp`/`asyncio`, since nothing else in this codebase uses
asyncio.

planet-latest.osm.pbf (80+ GB) is mirrored at a handful of well-known public
hosts. Rather than trusting any single one, `discover_planet_sources` queries
all of them concurrently, cross-validates their reported MD5 hashes,
timestamps, and file sizes to agree on exactly one current file, and returns
every URL serving it. The caller hands all of those URLs to aria2c at once
(see downloader.py's DownloadAria2), which downloads different byte ranges
from different mirrors in parallel -- aggregating their bandwidth instead of
being capped by any single one of them.

Checksum verification is mandatory: if the mirrors can't be reconciled into
one trustworthy hash, discover_planet_sources raises rather than returning
an unverified guess.
"""

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from ..utils.logger import get_logger

USER_AGENT = "abt-planet-downloader/1.0 (+https://github.com/ReleaseableBasemapTiles/abt)"

_PLANET_FILE_RE = re.compile(r'^planet-(\d{6}|latest)\.osm\.pbf(\.md5)?$')
_MD5_RE = re.compile(r'^[a-fA-F0-9]{32}$')
_REQUEST_TIMEOUT = 30


@dataclass
class PlanetSource:
    """One mirror's copy of a specific planet file, plus whatever metadata
    (hash, size, publish date) could be loaded for it."""
    name: str
    url: str
    mirror_country: str
    is_primary: bool = False
    timestamp: Optional[datetime] = None
    url_hash: Optional[str] = None
    hash: Optional[str] = None
    file_len: Optional[int] = None

    def __post_init__(self) -> None:
        if self.url_hash is None:
            self.url_hash = self.url + '.md5'

    def __str__(self) -> str:
        size = f"{self.file_len / 1024.0 / 1024:,.1f} MB" if self.file_len else "unknown size"
        return f"{self.name} from {self.url} ({self.mirror_country}, {size})"


class Mirror:
    """A mirror that serves a single, fixed planet-latest.osm.pbf URL."""

    def __init__(self, country: str, url: str, is_primary: bool = False):
        self.country = country
        self.url = url
        self.is_primary = is_primary

    def list_sources(self, session: requests.Session) -> List[PlanetSource]:
        return [PlanetSource(name='planet-latest.osm.pbf', url=self.url,
                              mirror_country=self.country, is_primary=self.is_primary)]


class MirrorMult(Mirror):
    """A mirror exposing a directory listing of several dated planet files
    (plus usually a 'latest' one) -- e.g. an Apache/nginx autoindex page."""

    def list_sources(self, session: requests.Session) -> List[PlanetSource]:
        html = _fetch_text(session, self.url)
        soup = BeautifulSoup(html, 'html.parser')
        items = sorted(
            (a.text.strip(), a['href'].strip())
            for a in soup.find_all('a') if 'href' in a.attrs
        )

        by_date: Dict[str, PlanetSource] = {}
        for name, href in items:
            m = _PLANET_FILE_RE.match(name)
            if not m:
                continue
            date, is_md5 = m.group(1), bool(m.group(2))
            url = href if '/' in href else (self.url + href)
            if not is_md5:
                if date not in by_date:
                    by_date[date] = PlanetSource(
                        name=name, url=url, mirror_country=self.country,
                        is_primary=self.is_primary,
                        timestamp=None if date == 'latest' else datetime.strptime(date, '%y%m%d'),
                    )
            elif date in by_date:
                by_date[date].url_hash = url

        # Keep the 2 most recent dated files, plus "latest" (usually a
        # symlink/copy of one of them, but treated as its own source until
        # its hash is loaded and it can be deduped against the newest dated
        # file -- see _load_mirror_sources).
        latest = by_date.pop('latest', None)
        result = [by_date[d] for d in sorted(by_date, reverse=True)[:2]]
        if latest:
            result.insert(0, latest)
        return result


# The sources order matters for the primary-exclusion logic below (GB is the
# canonical osm.org mirror; please avoid adding load to it unnecessarily).
PLANET_MIRRORS: List[Mirror] = [
    MirrorMult('GB', 'https://planet.openstreetmap.org/pbf/', is_primary=True),
    Mirror('DE', 'https://download.bbbike.org/osm/planet/planet-latest.osm.pbf'),
    MirrorMult('DE', 'https://ftp.spline.de/pub/openstreetmap/pbf/'),
    MirrorMult('DE', 'https://ftp5.gwdg.de/pub/misc/openstreetmap/planet.openstreetmap.org/pbf/'),
    # https://planet.passportcontrol.net/pbf/ redirects to a broken SSL cert
    # when used from some locations -- see
    # https://twitter.com/IchikawaYukko/status/1261541590566223872
    MirrorMult('JP', 'https://planet.passportcontrol.net/pbf/'),
    MirrorMult('DE', 'https://ftp.fau.de/osm-planet/pbf/'),
    Mirror('NL', 'https://ftp.nluug.nl/maps/planet.openstreetmap.org/pbf/planet-latest.osm.pbf'),
    Mirror('NL', 'https://ftp.snt.utwente.nl/pub/misc/openstreetmap/planet-latest.osm.pbf'),
    MirrorMult('TW', 'https://free.nchc.org.tw/osm.planet/pbf/'),
    Mirror('US', 'https://ftp.osuosl.org/pub/openstreetmap/pbf/planet-latest.osm.pbf'),
    MirrorMult('US', 'https://ftpmirror.your.org/pub/openstreetmap/pbf/'),
]


def _fetch_text(session: requests.Session, url: str) -> str:
    resp = session.get(url, timeout=_REQUEST_TIMEOUT)
    if resp.status_code >= 400:
        raise ValueError(f'Received status={resp.status_code} for {url}')
    return resp.text


def _load_source_metadata(session: requests.Session, source: PlanetSource, logger: logging.Logger) -> None:
    """Fills in `source.hash`/`source.file_len` in place. Failures are
    logged, not raised -- one source's metadata being unavailable shouldn't
    stop discovery; it's just excluded from consideration later."""
    try:
        text = _fetch_text(session, source.url_hash).strip()
        if not text:
            raise ValueError("Empty response body")
        candidate = text.split()[0]
        if not _MD5_RE.match(candidate):
            raise ValueError(f"Invalid md5 hash '{candidate}'")
        source.hash = candidate
    except Exception as ex:
        logger.warning(f"Unable to load md5 hash for {source} ({source.url_hash}): {ex}")

    try:
        resp = session.head(source.url, timeout=_REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400:
            raise ValueError(f'Status={resp.status_code} for HEAD request')
        if 'Content-Length' in resp.headers:
            source.file_len = int(resp.headers['Content-Length'])
    except Exception as ex:
        logger.warning(f"Unable to load content length for {source}: {ex}")


def _load_mirror_sources(mirror: Mirror, session: requests.Session, logger: logging.Logger) -> List[PlanetSource]:
    """Lists and loads metadata for one mirror's sources. Returns [] (logged,
    not raised) if the mirror is unreachable or unparseable -- a single flaky
    mirror shouldn't sink discovery as long as others succeed."""
    try:
        sources = mirror.list_sources(session)
        if not sources:
            raise ValueError('No sources found')
        for source in sources:
            _load_source_metadata(session, source, logger)
        if len(sources) > 1 and sources[0].hash and sources[0].hash == sources[1].hash:
            del sources[0]  # "latest" turned out identical to the newest dated file
        return sources
    except Exception as ex:
        logger.warning(f"Unable to use {mirror.country} mirror {mirror.url}: {ex}")
        return []


def _attr_to_hash(sources_by_hash: Dict[str, List[PlanetSource]], attr_name: str) -> Optional[Dict]:
    """Returns {attr_value: hash} if every source's `attr_name` maps to
    exactly one hash; returns None the moment any value is claimed by two
    different hashes -- i.e. the mirrors disagree and neither can be trusted.
    """
    attr_to_hash: Dict = {}
    for sources in sources_by_hash.values():
        for source in sources:
            value = getattr(source, attr_name)
            if value is None:
                continue
            if value not in attr_to_hash:
                attr_to_hash[value] = source.hash
            elif attr_to_hash[value] != source.hash:
                return None
    return attr_to_hash


def discover_planet_sources(
    log_dir: Path,
    force_latest: bool = False,
    use_primary: bool = False,
) -> Tuple[List[str], str]:
    """Queries every known planet mirror concurrently, reconciles their
    reported MD5 hashes/timestamps/sizes, and returns every URL serving
    whichever file is both current and widely mirrored, plus its MD5.

    `force_latest` skips the "wait for wider propagation" heuristic below.
    `use_primary` allows including the canonical osm.org mirror even when
    enough secondary mirrors make that unnecessary (please avoid setting
    this to reduce load on the primary server).

    Raises RuntimeError if the mirrors can't be reconciled into a single
    trustworthy hash. Checksum verification is mandatory for planet
    downloads -- there is intentionally no fallback to an unverified
    download.
    """
    logger = get_logger(name="planet", directory=log_dir, process_stage="download")
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    logger.info(f"Querying {len(PLANET_MIRRORS)} known planet mirrors...")
    sources_by_mirror: List[List[PlanetSource]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(PLANET_MIRRORS))) as pool:
        futures = [pool.submit(_load_mirror_sources, m, session, logger) for m in PLANET_MIRRORS]
        for future in as_completed(futures):
            sources_by_mirror.append(future.result())

    sources_by_hash: Dict[str, List[PlanetSource]] = defaultdict(list)
    unhashed: List[PlanetSource] = []
    for sources in sources_by_mirror:
        for source in sources:
            if source.hash:
                sources_by_hash[source.hash].append(source)
            else:
                unhashed.append(source)

    if not sources_by_hash:
        raise RuntimeError(
            f"Unable to determine planet.osm.pbf's checksum from any of the "
            f"{len(PLANET_MIRRORS)} known mirrors (see PLANET_MIRRORS in "
            f"abt/download/planet_mirrors.py). Check network access, or "
            f"that the mirrors are still reachable/unchanged."
        )

    ts_to_hash = _attr_to_hash(sources_by_hash, 'timestamp')
    if ts_to_hash is None:
        raise RuntimeError(
            "Planet mirrors disagree: two mirrors report the same publish "
            "date with different MD5 checksums. Refusing to guess which is "
            "correct -- checksum verification is mandatory for planet "
            "downloads."
        )

    # Sources without their own md5 (e.g. a mirror whose .md5 sidecar 404s)
    # can still be used if their file length uniquely identifies one of the
    # already-confirmed hashes.
    len_to_hash = _attr_to_hash(sources_by_hash, 'file_len')
    for source in unhashed:
        if len_to_hash and source.file_len in len_to_hash:
            source.hash = len_to_hash[source.file_len]
            sources_by_hash[source.hash].append(source)
        else:
            logger.warning(f"Ignoring {source}: no md5, and file length doesn't "
                            f"uniquely match a confirmed hash")

    for sources in sources_by_hash.values():
        sources.sort(key=lambda s: (s.timestamp or datetime.max, s.file_len or (1 << 63)))

    stats = sorted(
        (
            (sources[0].timestamp or datetime.max, len(sources), hsh)
            for hsh, sources in sources_by_hash.items()
        ),
        reverse=True,
    )

    logger.info("Latest available planet files:")
    for ts, count, hsh in stats:
        date_str = f"{ts:%Y-%m-%d}" if ts < datetime.max else "unknown date"
        logger.info(f"  {date_str}  mirrors={count}  md5={hsh}")

    # If the newest file is mirrored by meaningfully fewer sources than the
    # second-newest (< ~2/3 as many), it likely hasn't propagated widely
    # yet -- prefer the previous, more widely-available file instead.
    if not force_latest and len(stats) > 1 and stats[0][1] * 1.5 < stats[1][1]:
        _, _, winning_hash = stats[1]
    else:
        _, _, winning_hash = stats[0]

    src_list = sources_by_hash[winning_hash]
    if len(src_list) > 2 and not use_primary:
        without_primary = [s for s in src_list if not s.is_primary]
        if without_primary:
            src_list = without_primary

    ts = next((s.timestamp for s in src_list if s.timestamp), None)
    logger.info(
        f"Will download planet published {f'{ts:%Y-%m-%d}' if ts else '(unknown date)'}, "
        f"md5={winning_hash}, from {len(src_list)} source(s): "
        + ", ".join(f"{s.mirror_country}:{s.url}" for s in src_list)
    )

    return [s.url for s in src_list], winning_hash
