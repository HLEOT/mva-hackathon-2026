"""Retain FastQC screening flags without turning them into causal diagnoses.

Only summary labels are rendered in reports. Archive paths and hashes stay in
private provenance; overrepresented sequences and filenames are never copied
into a public status message. Reading ZIP members does not extract any files.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path

from mva_track1.common import Track1Error, sha256_file

MODULES = {
    "Basic Statistics", "Per base sequence quality", "Per tile sequence quality",
    "Per sequence quality scores", "Per base sequence content", "Per sequence GC content",
    "Per base N content", "Sequence Length Distribution", "Sequence Duplication Levels",
    "Overrepresented sequences", "Adapter Content",
}
STATUSES = {"PASS", "WARN", "FAIL"}


def _prefix(name: str) -> str:
    filename = Path(name).name
    if not re.search(r"\.(?:fastq|fq)(?:\.gz)?$", filename):
        raise Track1Error("QC input inventory must contain FASTQ filenames")
    return re.sub(r"\.(?:fastq|fq)(?:\.gz)?$", "", filename) + "_fastqc"


def read_fastqc_summary(qc_root: Path, expected_fastqs: list[str]) -> dict:
    """Verify one complete pinned-default FastQC report for each input FASTQ.

    The expected module set is the default FastQC 0.12.1 workflow contract.
    Missing/unknown modules stop packaging rather than silently implying PASS.
    CRC, inventory and HTML checks establish artifact integrity, not biological
    suitability; WARN and FAIL are preserved separately from those checks.
    """
    expected = {_prefix(name) for name in expected_fastqs}
    if not expected or len(expected) != len(expected_fastqs):
        raise Track1Error("QC input inventory is empty or has colliding report names")
    directory = qc_root / "fastqc"
    archives = sorted(directory.glob("*_fastqc.zip"))
    htmls = sorted(directory.glob("*_fastqc.html"))
    if {path.stem for path in archives} != expected or {path.stem for path in htmls} != expected:
        raise Track1Error("FastQC output inventory does not match the expected FASTQs")
    multiqc = qc_root / "multiqc_report.html"
    for path in archives + htmls + [multiqc]:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(qc_root.resolve()):
            raise Track1Error("QC artifacts must be regular files inside the private QC directory")
    counts = {module: Counter() for module in sorted(MODULES)}
    versions, records = set(), []
    for path in archives:
        before = path.stat()
        try:
            with zipfile.ZipFile(path) as source:
                # Bound decompression before testing CRCs; no sequence payload
                # from a malformed archive is needed to explain a rejection.
                if sum(item.file_size for item in source.infolist()) > 100_000_000:
                    raise Track1Error("FastQC archive exceeds the expected report-size bound")
                if source.testzip() is not None:
                    raise Track1Error("FastQC archive failed its CRC check")
                summary = [name for name in source.namelist() if name.endswith("/summary.txt")]
                data = [name for name in source.namelist() if name.endswith("/fastqc_data.txt")]
                if len(summary) != 1 or len(data) != 1 or source.getinfo(summary[0]).file_size > 32768:
                    raise Track1Error("FastQC archive has missing or ambiguous summary metadata")
                with source.open(data[0]) as handle:
                    header = handle.readline(100).decode("utf-8").rstrip()
                if header != "##FastQC\t0.12.1":
                    raise Track1Error("FastQC report version differs from the pinned workflow")
                versions.add(header.split("\t", 1)[1])
                observed = set()
                for line in source.read(summary[0]).decode("utf-8").splitlines():
                    fields = line.split("\t", 2)
                    if len(fields) != 3:
                        raise Track1Error("FastQC summary row is malformed")
                    status, module, _filename = fields
                    if status not in STATUSES or module not in MODULES or module in observed:
                        raise Track1Error("FastQC summary contains an invalid or duplicate module")
                    observed.add(module)
                    counts[module][status] += 1
                if observed != MODULES:
                    raise Track1Error("FastQC summary omits a required default module")
        except (zipfile.BadZipFile, UnicodeError) as exc:
            raise Track1Error("FastQC report archive is invalid") from exc
        digest = sha256_file(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise Track1Error("FastQC archive changed during verification")
        records.append({"path": str(path.relative_to(qc_root)), "sha256": digest, "size": after.st_size})
    with multiqc.open("rb") as source:
        source.seek(max(0, multiqc.stat().st_size - 8192))
        if b"</html>" not in source.read().lower():
            raise Track1Error("MultiQC HTML appears incomplete")
    rows = [{"module": module, **{status: counts[module][status] for status in sorted(STATUSES)}}
            for module in sorted(counts)]
    return {"report_count": len(archives), "fastqc_versions": sorted(versions),
            "artifact_integrity_verified": True, "all_modules_passed": not any(row["WARN"] or row["FAIL"] for row in rows),
            "modules": rows, "archives": records, "multiqc_sha256": sha256_file(multiqc)}


def report_section(summary: dict) -> str:
    """Render aggregate caveats, without archive names or sequence content."""
    lines = ["## Raw-read quality-control caveats", "",
        f"FastQC {', '.join(summary['fastqc_versions'])}: {summary['report_count']} input-file reports verified; "
        "archive integrity and the complete MultiQC document were checked. These checks do not imply that every quality module passed.", ""]
    flagged = [row for row in summary["modules"] if row["WARN"] or row["FAIL"]]
    if flagged:
        lines += [f"- {row['module']}: FAIL in {row['FAIL']} reports; WARN in {row['WARN']} reports." for row in flagged]
    else:
        lines.append("All reported FastQC modules passed their screening thresholds; this is not proof of variant validity.")
    lines += ["", "The causes of composition or GC flags are not established by these summaries. "
        "They do not by themselves confirm contamination or invalidate a variant. Library preparation and detailed QC plots "
        "require review; no trimming or read modification was performed solely to remove these flags. "
        "Measured mapping/base-quality, depth, strand and phase checks remain separate evidence gates. "
        "Track 2 hypotheses inherit unresolved technical uncertainty from Track 1.", "",
        "Interpretation references: [FastQC base-content module](https://www.bioinformatics.babraham.ac.uk/projects/fastqc/Help/3%20Analysis%20Modules/4%20Per%20Base%20Sequence%20Content.html) "
        "and [FastQC GC-content module](https://www.bioinformatics.babraham.ac.uk/projects/fastqc/Help/3%20Analysis%20Modules/5%20Per%20Sequence%20GC%20Content.html).", ""]
    return "\n".join(lines)
