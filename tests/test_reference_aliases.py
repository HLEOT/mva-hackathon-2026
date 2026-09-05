import json
import pytest

from mva_track1.common import Track1Error
from mva_track1.workflow_tasks import _reference_check


def vcf(path, length=100):
    path.write_text('##fileformat=VCFv4.2\n' + f'##contig=<ID=1,length={length}>\n' +
                    '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTH\n' +
                    '1\t5\t.\tA\tG\t30\tPASS\t.\tGT\t0/1\n')


def test_common_aliases_are_mapped_without_liftover(tmp_path):
    source, fai, output, aliases = [tmp_path / x for x in ['synthetic.vcf', 'synthetic.fai', 'check.json', 'aliases.tsv']]
    vcf(source)
    fai.write_text('chr1\t100\t0\t60\t61\n')
    _reference_check(source, fai, output, aliases)
    assert aliases.read_text() == '1\tchr1\n'
    assert json.loads(output.read_text())['matched_primary_contigs'] == 1
    vcf(source, 99)
    with pytest.raises(Track1Error, match='Length mismatches'):
        _reference_check(source, fai, output, aliases)
