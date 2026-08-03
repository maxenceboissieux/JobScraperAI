"""Persistence repositories for job aggregation entities."""

from jobscraper.repositories.jobs import JobRepository
from jobscraper.repositories.saved_searches import SavedSearchRepository
from jobscraper.repositories.sync_runs import SyncRunRepository

__all__ = ["JobRepository", "SavedSearchRepository", "SyncRunRepository"]
