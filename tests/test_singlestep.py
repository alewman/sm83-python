"""Rung 1: SingleStepTests sm83, 498 files x 1,000 cases (validation.md).

Emulator-derived: a detector with high volume, not a judge. The quick sample runs the first
20 cases of every file; the full gate is marked ``slow``.
"""

import pytest

from tests.sst_runner import CORPUS, corpus_files, run_file

pytestmark = pytest.mark.skipif(
    not CORPUS.is_dir(), reason="run scripts/fetch_references.py to fetch the corpus"
)

FILES = corpus_files()


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_sample(path):
    failures = run_file(path, limit=20)
    assert not failures, "\n".join(failures[:10])


@pytest.mark.slow
@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_full(path):
    failures = run_file(path)
    assert not failures, f"{len(failures)} disagreements\n" + "\n".join(failures[:10])
