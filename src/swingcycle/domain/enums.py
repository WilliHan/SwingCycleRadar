from enum import Enum


class Action(str, Enum):
    WAIT = "WAIT"
    READY = "READY"
    ENTRY = "ENTRY"
    ADD = "ADD"
    TAKE_PROFIT_PARTIAL = "TAKE_PROFIT_PARTIAL"
    EXIT = "EXIT"
    STOP = "STOP"
    RESET = "RESET"


class Gate(str, Enum):
    PASS = "PASS"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"


class DowState(str, Enum):
    DOWNTREND = "DOWNTREND"
    REVERSAL_CANDIDATE = "REVERSAL_CANDIDATE"
    UPTREND = "UPTREND"
    RANGE = "RANGE"


class CycleState(str, Enum):
    DOWNTREND = "DOWNTREND"
    BOTTOMING = "BOTTOMING"
    REVERSAL = "REVERSAL"
    UPTREND = "UPTREND"
    PULLBACK = "PULLBACK"
    REACCELERATION = "REACCELERATION"
    LATE_STAGE = "LATE_STAGE"
    DOWNTREND_TRANSITION = "DOWNTREND_TRANSITION"


class TradePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"
    RESET = "RESET"


class EntryType(str, Enum):
    REVERSAL = "REVERSAL"
    PULLBACK = "PULLBACK"


class DataSource(str, Enum):
    KRX_DIRECT = "KRX_DIRECT"
    PYKRX = "PYKRX"
