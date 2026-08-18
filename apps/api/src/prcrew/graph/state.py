import operator
from typing import Annotated, TypedDict

from prcrew.models import Finding, NodeError, PRContext, VerifiedFinding


def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}

class ReviewState(TypedDict, total=False):
    pr_context: PRContext
    findings: Annotated[dict[str, list[Finding]], merge_dicts]
    errors: Annotated[list[NodeError], operator.add]
    verified: list[VerifiedFinding]
    review: str
