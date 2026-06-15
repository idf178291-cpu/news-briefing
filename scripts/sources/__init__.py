from .base import BaseSource, ArticleLink, Article, BriefingItem
from .stats_gov import StatsGovSource
from .mof_gov import MofGovSource
from .pbc_gov import PbcGovSource
from .nfra_gov import NfraGovSource
from .csrc_gov import CsrcGovSource

ALL_SOURCES = [NfraGovSource, PbcGovSource, MofGovSource, CsrcGovSource, StatsGovSource]


def get_sources(slugs: list[str] | None = None) -> list[BaseSource]:
    """Return instantiated sources, optionally filtered by slug list."""
    if slugs is None:
        return [cls() for cls in ALL_SOURCES]
    slug_set = set(slugs)
    return [cls() for cls in ALL_SOURCES if cls.slug in slug_set]
