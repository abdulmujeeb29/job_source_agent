from evaluation.newest_report import build_report


def batch():
    sample = {"urls": [f"https://www.linkedin.com/jobs/view/{5000000000+i}/" for i in range(20)]}
    runs = {i: {"status": "failed", "finished_at": "2026-09-17T00:00:00Z"} for i in range(1, 21)}
    reviews = {str(i): {"accepted": False, "listing_verified": False,
                        "reviewer": "Fixture reviewer", "at": "2026-09-17T00:01:00Z"} for i in range(1, 21)}
    return sample, runs, reviews


def test_unverified_ats_fallback_is_not_counted_as_resolved():
    sample, runs, reviews = batch()
    runs[1].update(status="succeeded", jobs_url="https://company.example/careers",
                   ats_resolution={"status": "unverified"})
    reviews["1"].update(accepted=True, listing_verified=True)
    report = build_report(sample, runs, reviews)
    assert "Final destination resolved: 0/20 (0%)" in report
    assert "Company-listing verified (broader criterion): **1/20 (5%)" in report


def test_already_hosted_ats_and_explicit_company_board_are_distinguished():
    sample, runs, reviews = batch()
    runs[1].update(status="succeeded", jobs_url="https://jobs.ashbyhq.com/example", ats_resolution={})
    runs[2].update(status="succeeded", jobs_url="https://company.example/jobs",
                   ats_resolution={"status": "company_hosted"})
    for i in ("1", "2"):
        reviews[i].update(accepted=True, listing_verified=True)
    report = build_report(sample, runs, reviews)
    assert "Final destination resolved: 2/20 (10%)" in report
    assert "ATS-hosted final boards: 1" in report
    assert "ATS-designated company-hosted collections: 1" in report


def test_no_final_rate_until_every_input_is_reviewed_and_finished():
    sample, runs, reviews = batch()
    reviews["20"]["accepted"] = None
    assert "Preliminary" in build_report(sample, runs, reviews)
    reviews["20"]["accepted"] = False
    runs[20].pop("finished_at")
    assert "Preliminary" in build_report(sample, runs, reviews)
