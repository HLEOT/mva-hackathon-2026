"""Private worker entrypoint; its parent captures all detailed errors locally."""
from __future__ import annotations

import argparse
import errno
import traceback
import urllib.error
from pathlib import Path

from mva_track1.common import Track1Error, atomic_write_json, utc_now


def retryable_failure(exc: BaseException) -> bool:
    """Recognise transient transport failures even behind a safe error wrapper.

    Do not inspect exception messages: they can contain private URLs or tokens.
    An explicit 4xx response (except rate limiting) needs intervention, not more
    identical attempts. A bounded identity set handles cyclic exception chains.
    """
    transport_types: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)
    try:
        from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout
        transport_types += (RequestsConnectionError, Timeout)
    except ImportError:
        pass
    try:
        from httpx import TransportError
        transport_types += (TransportError,)
    except ImportError:
        pass
    transient_errno = {errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNREFUSED,
                       errno.ECONNABORTED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPIPE}
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited and len(visited) < 64:
        visited.add(id(current))
        status = getattr(current, "code", None) if isinstance(current, urllib.error.HTTPError) else None
        response = getattr(current, "response", None)
        if response is not None:
            status = getattr(response, "status_code", status)
        if isinstance(status, int):
            return status == 429 or 500 <= status <= 599
        if isinstance(current, transport_types):
            return True
        if isinstance(current, OSError) and current.errno in transient_errno:
            return True
        if isinstance(current, urllib.error.URLError) and isinstance(current.reason, BaseException):
            current = current.reason
        else:
            current = current.__cause__ or current.__context__
    return False


def execute(name: str) -> None:
    if name == "model":
        from .local import prepare
        prepare()
    elif name == "public_evidence":
        from mva_track2.evidence import prepare
        prepare()
    elif name in {"phenotype", "finalists"}:
        from . import review
        getattr(review, name)()
    elif name == "validate_reads":
        from .read_evidence import validate_reads
        validate_reads()
    elif name in {"prioritise", "download_reads", "provenance"}:
        from . import scientific
        getattr(scientific, name)()
    elif name == "track2":
        from mva_track2.analysis import analyse
        analyse()
    elif name == "package":
        from .delivery import package
        package()
    else:
        raise Track1Error("Unknown worker stage")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        execute(args.stage)
    except Exception as exc:
        traceback.print_exc()  # Parent redirects this to an owner-only log.
        retryable = retryable_failure(exc)
        atomic_write_json(args.receipt, {"status":"failed", "error_category":type(exc).__name__,
                                        "retryable":retryable,"finished_at":utc_now()})
        return 1
    atomic_write_json(args.receipt, {"status":"complete","finished_at":utc_now()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
