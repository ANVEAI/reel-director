"""Paid-generation budget: per-reel and daily caps plus the approvals ledger (v4 media contract).

Every paid clip (Veo, Higgsfield) moves through events appended to ONE local JSONL ledger (event-sourced state):
  quote    exact request spec + USD estimate; no money moves, nothing is sent to the provider
  approve  the creator approved THIS quote (Studio button / `python -m reel_director.media.budget approve <id>`);
           the per-reel cap, the daily cap and the paid-clips-per-reel limit are checked here
  reject   the creator declined it
  submit   the provider is about to spend: approval + caps re-checked, the money is counted from this moment
  operation  the provider's job id, so an interrupted run resumes polling instead of paying twice
  settle   terminal outcome: charged=True (completed), None (unknown, still counted) or False (refunded/never accepted)

Fail-closed rules: an unreadable ledger line raises LedgerError (never under-count spend); a quote without a USD
price cannot be approved; one approval buys exactly one submission; approvals expire after `approval_ttl_s`.
The ledger lives on the local disk ($REEL_DIRECTOR_CACHE, default ~/.cache/reel-director), never on the external
media drive, so an unmounted drive can't reset today's spend.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .base import ApprovalRequired as _BaseApprovalRequired

PER_REEL_USD = 5.0          # contract default
DAILY_USD = 20.0            # contract default (global, all reels, local calendar day)
MAX_PAID_CLIPS_PER_REEL = 1  # director default: <= 1 paid clip per reel
APPROVAL_TTL_S = 24 * 3600


class BudgetError(RuntimeError):
    """Base class: nothing was spent."""


class LedgerError(BudgetError):
    pass


class ApprovalRequired(BudgetError, _BaseApprovalRequired):
    """The quote exists but the creator has not approved it (or the approval expired / was used).
    Also a base.ApprovalRequired, so the resolver's existing `except ApprovalRequired` catches it."""


class BudgetExceeded(BudgetError):
    pass


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_id_for(provider: str, model: str, spec: Mapping, reel: str, clip: str) -> str:
    """Deterministic: the same reel/clip/spec always maps to the same quote (and so to one approval)."""
    return hashlib.sha256(canonical([provider, model, dict(spec), reel, clip]).encode()).hexdigest()[:20]


def default_ledger_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("REEL_DIRECTOR_PAID_LEDGER"):
        return Path(env["REEL_DIRECTOR_PAID_LEDGER"]).expanduser()
    base = Path(env.get("REEL_DIRECTOR_CACHE") or Path.home() / ".cache" / "reel-director").expanduser()
    return base / "media" / "paid-ledger.jsonl"


def local_day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


@dataclass(frozen=True)
class Quote:
    request_id: str
    provider: str
    model: str
    reel: str
    clip: str
    seconds: float
    usd: float | None          # None = no price known -> cannot be approved
    spec: dict = field(default_factory=dict)
    basis: str = ""            # where the price comes from (catalog SKU / provider estimate endpoint)


@dataclass
class _Row:                    # derived per-request state, rebuilt from the events on every read
    quote: Quote
    state: str = "quoted"      # quoted | approved | rejected | submitted | settled
    approved_at: float | None = None
    approved_by: str | None = None
    submitted_at: float | None = None
    operation: str | None = None
    outcome: str | None = None
    charged: bool | None = None
    output: str | None = None
    usd_actual: float | None = None


class Budget:
    def __init__(self, ledger: Path | str | None = None, *, per_reel_usd: float = PER_REEL_USD,
                 daily_usd: float = DAILY_USD, max_paid_clips_per_reel: int = MAX_PAID_CLIPS_PER_REEL,
                 approval_ttl_s: float = APPROVAL_TTL_S, clock: Callable[[], float] = time.time,
                 day: Callable[[float], str] = local_day):
        self.ledger = Path(ledger).expanduser() if ledger else default_ledger_path()
        self.per_reel_usd, self.daily_usd = float(per_reel_usd), float(daily_usd)
        self.max_paid_clips_per_reel = int(max_paid_clips_per_reel)
        self.approval_ttl_s = float(approval_ttl_s)
        self.clock, self.day = clock, day

    @classmethod
    def from_settings(cls, settings: Mapping | None = None, env: Mapping[str, str] | None = None, **kw) -> "Budget":
        """settings['media']['paid'] = {per_reel_usd, daily_usd, max_clips_per_reel}; env REEL_DIRECTOR_PAID_* wins."""
        env = os.environ if env is None else env
        p = dict(((settings or {}).get("media") or {}).get("paid") or {})
        pick = lambda e, k, d: float(env.get(e) or p.get(k) or d)  # noqa: E731
        return cls(kw.pop("ledger", None) or default_ledger_path(env),
                   per_reel_usd=pick("REEL_DIRECTOR_PAID_PER_REEL_USD", "per_reel_usd", PER_REEL_USD),
                   daily_usd=pick("REEL_DIRECTOR_PAID_DAILY_USD", "daily_usd", DAILY_USD),
                   max_paid_clips_per_reel=int(pick("REEL_DIRECTOR_PAID_MAX_CLIPS", "max_clips_per_reel",
                                                    MAX_PAID_CLIPS_PER_REEL)), **kw)

    # ---- ledger I/O ----------------------------------------------------------------------------------------
    @contextmanager
    def _locked(self) -> Iterator[None]:
        """One writer at a time (Studio server + CLI); the check and the append happen under the same lock."""
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger.with_suffix(".lock"), "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def events(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        out = []
        for n, line in enumerate(self.ledger.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError as e:
                raise LedgerError(f"{self.ledger}:{n} is not JSON ({e}); refusing to guess the spend") from e
            if not isinstance(ev, dict) or "event" not in ev or "request_id" not in ev:
                raise LedgerError(f"{self.ledger}:{n} is not a ledger event")
            out.append(ev)
        return out

    def _append(self, event: str, request_id: str, **data: Any) -> dict:
        ev = {"ts": round(self.clock(), 3), "event": event, "request_id": request_id, **data}
        with self.ledger.open("a") as f:
            f.write(canonical(ev) + "\n")
        return ev

    def _rows(self) -> dict[str, _Row]:
        rows: dict[str, _Row] = {}
        for ev in self.events():
            rid, kind = ev["request_id"], ev["event"]
            if kind == "quote":                               # a re-quote replaces the price only before approval
                if rid not in rows or rows[rid].state == "quoted":
                    rows[rid] = _Row(Quote(**ev["quote"]))
                continue
            r = rows.get(rid)
            if r is None:
                raise LedgerError(f"ledger event {kind} for unknown quote {rid}")
            if kind == "approve":
                r.state, r.approved_at, r.approved_by = "approved", ev["ts"], ev.get("by")
            elif kind == "reject":
                r.state = "rejected"
            elif kind == "submit":
                r.state, r.submitted_at = "submitted", ev["ts"]
            elif kind == "operation":
                r.operation = ev.get("operation")
            elif kind == "settle":
                r.state, r.outcome, r.charged = "settled", ev.get("outcome"), ev.get("charged")
                r.output, r.usd_actual = ev.get("output"), ev.get("usd_actual")
        return rows

    # ---- accounting ----------------------------------------------------------------------------------------
    def _live_approval(self, r: _Row, now: float) -> bool:
        return r.state == "approved" and r.approved_at is not None and now - r.approved_at <= self.approval_ttl_s

    @staticmethod
    def _cost(r: _Row) -> float:
        if r.state == "settled" and r.charged is False:
            return 0.0                                        # refunded / never accepted
        return float(r.usd_actual if r.usd_actual is not None else (r.quote.usd or 0.0))

    def _spent(self, rows: dict[str, _Row], *, day: str | None = None, reel: str | None = None) -> float:
        return round(sum(self._cost(r) for r in rows.values() if r.submitted_at is not None
                         and (day is None or self.day(r.submitted_at) == day)
                         and (reel is None or r.quote.reel == reel)), 4)

    def _reserved(self, rows: dict[str, _Row], now: float, *, reel: str | None = None,
                  exclude: str | None = None) -> float:
        return round(sum(r.quote.usd or 0.0 for rid, r in rows.items() if rid != exclude
                         and self._live_approval(r, now) and (reel is None or r.quote.reel == reel)), 4)

    def _paid_clips(self, rows: dict[str, _Row], reel: str, now: float, exclude: str) -> int:
        return sum(1 for rid, r in rows.items() if rid != exclude and r.quote.reel == reel and (
            self._live_approval(r, now) or (r.submitted_at is not None and self._cost(r) > 0)))

    def _check_caps(self, rows: dict[str, _Row], q: Quote, now: float, *, include_reserved: bool) -> None:
        """Daily cap: always, across everything. Per-reel cap and paid-clip count: per reel id. A quote with no reel
        id (select.pick does not pass one yet) is its own reel here, so one unscoped clip can't lock every future
        reel out; its per-reel limits are then enforced by mediaplan.approve (media.json) before fetch."""
        if q.usd is None:
            raise BudgetError(f"{q.provider} quote {q.request_id} has no price; it cannot be approved")
        today, scoped = self.day(now), bool(q.reel)
        res_day = self._reserved(rows, now, exclude=q.request_id) if include_reserved else 0.0
        res_reel = self._reserved(rows, now, reel=q.reel, exclude=q.request_id) if include_reserved and scoped else 0.0
        day_total = self._spent(rows, day=today) + res_day + q.usd
        reel_total = (self._spent(rows, reel=q.reel) + res_reel if scoped else 0.0) + q.usd
        if reel_total > self.per_reel_usd + 1e-9:
            raise BudgetExceeded(f"reel {q.reel!r}: ${reel_total:.2f} would exceed the per-reel cap "
                                 f"${self.per_reel_usd:.2f}")
        if day_total > self.daily_usd + 1e-9:
            raise BudgetExceeded(f"today ({today}): ${day_total:.2f} would exceed the daily cap ${self.daily_usd:.2f}")
        if include_reserved and scoped and \
                self._paid_clips(rows, q.reel, now, q.request_id) >= self.max_paid_clips_per_reel:
            raise BudgetExceeded(f"reel {q.reel!r} already has {self.max_paid_clips_per_reel} paid clip(s); "
                                 "raise media.paid.max_clips_per_reel to allow more")

    # ---- lifecycle -----------------------------------------------------------------------------------------
    def quote(self, provider: str, model: str, spec: Mapping, *, usd: float | None, seconds: float,
              reel: str, clip: str, basis: str = "") -> Quote:
        rid = request_id_for(provider, model, spec, reel, clip)
        q = Quote(rid, provider, model, reel, clip, float(seconds),
                  None if usd is None else round(float(usd), 4), json.loads(canonical(dict(spec))), basis)
        with self._locked():
            rows = self._rows()
            if rid in rows:
                old = rows[rid].quote
                if old.usd == q.usd or rows[rid].state != "quoted":
                    return old                                 # idempotent; an approved price never changes
            self._append("quote", rid, quote=asdict(q))
        return q

    def get(self, request_id: str) -> Quote:
        row = self._rows().get(request_id)
        if row is None:
            raise ApprovalRequired(f"no quote {request_id} in {self.ledger}")
        return row.quote

    def state(self, request_id: str) -> dict:
        r = self._rows().get(request_id)
        if r is None:
            return {"request_id": request_id, "state": "unknown"}
        now = self.clock()
        st = "expired" if r.state == "approved" and not self._live_approval(r, now) else r.state
        return {"request_id": request_id, "state": st, "operation": r.operation, "outcome": r.outcome,
                "charged": r.charged, "output": r.output, "usd": r.quote.usd, "approved_by": r.approved_by}

    def approve(self, request_id: str, by: str = "creator") -> Quote:
        with self._locked():
            rows, now = self._rows(), self.clock()
            r = rows.get(request_id)
            if r is None:
                raise ApprovalRequired(f"no quote {request_id}")
            if r.state not in ("quoted", "approved", "rejected"):
                raise BudgetError(f"quote {request_id} is already {r.state}; a new generation needs a new quote")
            self._check_caps(rows, r.quote, now, include_reserved=True)
            self._append("approve", request_id, by=by, usd=r.quote.usd)
            return r.quote

    def reject(self, request_id: str, by: str = "creator") -> None:
        with self._locked():
            r = self._rows().get(request_id)
            if r is None or r.state not in ("quoted", "approved"):
                raise BudgetError(f"quote {request_id} cannot be rejected (state {r.state if r else 'unknown'})")
            self._append("reject", request_id, by=by)

    def begin(self, request_id: str) -> Quote:
        """The last gate before money moves. Exactly once per approval; caps re-checked against real spend."""
        with self._locked():
            rows, now = self._rows(), self.clock()
            r = rows.get(request_id)
            if r is None:
                raise ApprovalRequired(f"no quote {request_id}")
            if r.state != "approved":
                raise ApprovalRequired(f"quote {request_id} is {r.state}, not approved: approve it in Studio or run "
                                       f"`python -m reel_director.media.budget approve {request_id}`")
            if not self._live_approval(r, now):
                raise ApprovalRequired(f"approval for {request_id} expired; approve it again")
            self._check_caps(rows, r.quote, now, include_reserved=False)
            self._append("submit", request_id, usd=r.quote.usd)
            return r.quote

    def note_operation(self, request_id: str, operation: str) -> None:
        with self._locked():
            self._append("operation", request_id, operation=operation)

    def settle(self, request_id: str, outcome: str, *, charged: bool | None, output: str | None = None,
               usd_actual: float | None = None, detail: str | None = None) -> None:
        with self._locked():
            r = self._rows().get(request_id)
            if r is None or r.submitted_at is None:
                raise LedgerError(f"settle for {request_id} which was never submitted")
            self._append("settle", request_id, outcome=outcome, charged=charged, output=output,
                         usd_actual=usd_actual, detail=detail)

    # ---- views (Studio / CLI) ------------------------------------------------------------------------------
    def pending(self, reel: str | None = None) -> list[Quote]:
        return [r.quote for r in self._rows().values() if r.state == "quoted" and (reel is None or r.quote.reel == reel)]

    def summary(self, reel: str | None = None) -> dict:
        rows, now = self._rows(), self.clock()
        today = self.day(now)
        out = {"ledger": str(self.ledger), "day": today, "daily_cap_usd": self.daily_usd,
               "per_reel_cap_usd": self.per_reel_usd, "max_paid_clips_per_reel": self.max_paid_clips_per_reel,
               "spent_today_usd": self._spent(rows, day=today), "reserved_usd": self._reserved(rows, now),
               "pending": [asdict(q) for q in self.pending(reel)]}
        out["remaining_today_usd"] = round(max(0.0, self.daily_usd - out["spent_today_usd"] - out["reserved_usd"]), 4)
        if reel is not None:
            out.update(reel=reel, spent_reel_usd=self._spent(rows, reel=reel),
                       reserved_reel_usd=self._reserved(rows, now, reel=reel))
        return out


class SubmitRejected(RuntimeError):
    """The provider refused the request before accepting it (HTTP 4xx): nothing was charged."""


class GenerationFailed(RuntimeError):
    def __init__(self, message: str, *, outcome: str = "failed", charged: bool | None = None):
        super().__init__(message)
        self.outcome, self.charged = outcome, charged


class GenerationTimeout(RuntimeError):
    """Still running at the deadline; the job id is in the ledger, so the next fetch resumes polling for free."""


def run_paid(budget: Budget, request_id: str, *, submit: Callable[[], str], wait: Callable[[str], Any],
             finish: Callable[[Any], Path], approved_by: str | None = None) -> Path:
    """The single gated path every paid provider uses: begin (approval + caps) -> submit -> record the job id ->
    wait -> finish (download + cache) -> settle. Never submits twice for one approval; resumes a recorded job.
    approved_by: the caller passed approved=True (Studio approval): a still-open quote is approved now, caps
    enforced exactly as `approve` does. It never overrides a rejection or reuses a spent approval."""
    st = budget.state(request_id)
    if approved_by and st["state"] in ("quoted", "expired"):
        budget.approve(request_id, by=approved_by)
        st = budget.state(request_id)
    if st["state"] == "settled" and st["outcome"] == "completed":
        if st["output"] and Path(st["output"]).exists():
            return Path(st["output"])
        raise BudgetError(f"{request_id} was already generated and paid for, but its file {st['output']} is gone "
                          "(external drive unmounted?); paying again needs a new quote (attempt + 1)")
    if st["state"] == "submitted":
        op = st["operation"]
        if not op:
            raise LedgerError(f"{request_id} was submitted but no job id was recorded (network failure?); check the "
                              "provider console before paying again; it is counted as spent until settled")
    else:
        budget.begin(request_id)
        try:
            op = submit()
        except SubmitRejected as e:
            budget.settle(request_id, "rejected", charged=False, detail=str(e)[:500])
            raise
        budget.note_operation(request_id, op)
    try:
        result = wait(op)
    except GenerationFailed as e:
        budget.settle(request_id, e.outcome, charged=e.charged, detail=str(e)[:500])
        raise
    out = Path(finish(result))
    budget.settle(request_id, "completed", charged=True, output=str(out))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reel_director.media.budget",
                                 description="Paid B-roll generation ledger: list, approve or reject quotes.")
    ap.add_argument("--ledger", help="ledger path (default $REEL_DIRECTOR_CACHE/media/paid-ledger.jsonl)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary"); s.add_argument("--reel")  # noqa: E702
    for name in ("approve", "reject", "show"):
        p = sub.add_parser(name); p.add_argument("request_id")  # noqa: E702
        if name != "show":
            p.add_argument("--by", default="founder")
    a = ap.parse_args(argv)
    b = Budget.from_settings(None, ledger=a.ledger)
    try:
        if a.cmd == "summary":
            print(json.dumps(b.summary(a.reel), indent=2))
        elif a.cmd == "show":
            print(json.dumps({**b.state(a.request_id), "quote": asdict(b.get(a.request_id))}, indent=2))
        elif a.cmd == "approve":
            q = b.approve(a.request_id, by=a.by)
            print(f"approved {q.request_id}: {q.provider} {q.model} {q.seconds:g}s ${q.usd:.2f} (reel {q.reel!r})")
        else:
            b.reject(a.request_id, by=a.by)
            print(f"rejected {a.request_id}")
    except BudgetError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
