from enum import Enum


class PositionStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
