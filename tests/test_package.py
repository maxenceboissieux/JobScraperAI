from jobscraper import JobOffer, SearchCriteria, __version__


def test_package_exports_are_importable() -> None:
    assert __version__ == "1.0.0"
    assert JobOffer.__name__ == "JobOffer"
    assert SearchCriteria(location="France").location == "France"
