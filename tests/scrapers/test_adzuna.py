from urllib.parse import parse_qs, urlparse

import pytest

from jobscraper.models.job import ContractType, SearchCriteria
from jobscraper.scrapers.adzuna import AdzunaScraper


@pytest.fixture
def scraper() -> AdzunaScraper:
    return AdzunaScraper({"app_id": "id", "app_key": "key"})


@pytest.mark.parametrize(
    ("contracts", "expected"),
    [
        ([ContractType.CDI], ["permanent"]),
        ([ContractType.CDD], ["contract"]),
        (
            [ContractType.CDD, ContractType.INTERIM, ContractType.FREELANCE],
            ["contract"],
        ),
        (
            [ContractType.CDD, ContractType.CDI, ContractType.FREELANCE],
            ["contract", "permanent"],
        ),
        ([ContractType.STAGE, ContractType.ALTERNANCE], []),
        ([], [None]),
    ],
)
def test_contract_filter_families_preserve_supported_first_seen_order(
    scraper: AdzunaScraper,
    contracts: list[ContractType],
    expected: list[str | None],
) -> None:
    assert scraper._contract_filter_families(
        SearchCriteria(contract_types=contracts)
    ) == expected


@pytest.mark.parametrize(
    ("family", "expected_key"),
    [("permanent", "permanent"), ("contract", "contract")],
)
def test_build_search_url_uses_supported_contract_flag(
    scraper: AdzunaScraper, family: str, expected_key: str
) -> None:
    criteria = SearchCriteria(
        title="Développeur React & Next.js",
        contract_types=[ContractType.CDI, ContractType.CDD],
    )
    query = parse_qs(
        urlparse(
            scraper._build_search_url(criteria, 1, 50, contract_filter=family)
        ).query
    )

    assert query[expected_key] == ["1"]
    assert query["what"] == ["Développeur React & Next.js"]
    assert "contract_type" not in query
    assert "full_time" not in query
    assert not ({"permanent", "contract"} <= query.keys())
