import pytest

from evaluation.report import build_report
from evaluation.sample import sample_records


def test_sample_is_reproducible_unique_and_excludes_development():
    rows = [{"linkedinUrl": f"https://www.linkedin.com/jobs/view/{5000000000+i}/"} for i in range(50)]
    rows += rows[:4] + [{"linkedinUrl": "https://www.linkedin.com/jobs/view/4427787182/"}]
    sample = sample_records(rows)
    assert sample_records(list(reversed(rows))) == sample
    assert len(sample["urls"]) == len(set(sample["urls"])) == 20
    assert len(sample["pool"]) == 50


def test_small_pool_fails_instead_of_replacement_sampling():
    with pytest.raises(ValueError):
        sample_records([])


def test_report_keeps_failures_in_denominator_and_requires_review():
    sample = {"urls": [f"https://www.linkedin.com/jobs/view/{5000000000+i}/" for i in range(20)]}
    runs = {i: {"status": "succeeded" if i < 16 else "failed"} for i in range(1, 21)}
    assert "Preliminary" in build_report(sample, runs, {})
    review = {str(i): {"accepted": i < 16, "reviewer": "Tester", "at": "2026-09-16", "notes": "Reviewed"} for i in range(1, 21)}
    report = build_report(sample, runs, review)
    assert "15/20 (75%)" in report
    assert "failed" in report
    post = build_report(sample, runs, review, kind="post-fix")
    assert "not held out" in post
    assert "15/20 (75%)" in post
