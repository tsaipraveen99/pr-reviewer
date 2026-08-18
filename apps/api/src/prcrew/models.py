from typing import Literal

from pydantic import BaseModel

Severity = Literal["critical", "major", "minor", "info"]

class PRContext(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str
    linked_issue: str | None = None
    diff: str
    changed_files: int
    changed_lines: int

class Finding(BaseModel):
    id: str = ""
    agent: str
    file: str
    line: int | None = None
    severity: Severity
    claim: str
    evidence: str

class VerifiedFinding(Finding):
    verdict: Literal["confirmed", "rejected"]
    reason: str

class NodeError(BaseModel):
    node: str
    message: str
