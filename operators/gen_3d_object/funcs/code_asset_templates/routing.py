"""How a subject is assembled, and which route that implies.

The axis is **assembly topology**, not adjectives. A rifle and a suit of
armour are both hard-surfaced and route differently, for a structural reason no
adjective captures: the rifle's parts sit beside each other in one coordinate
system, while the armour's parts sit on a host that must exist and be measured
first.

:data:`COMPOSED`
    Parts sit beside each other, joined by adjacency. A rifle is a receiver
    plus a barrel plus a magazine; a car is a body plus four wheels. Nothing
    has to exist first, so the whole thing is describable — the `code` route.

:data:`NESTED`
    Layers sit *on a host* that must exist and be measured before they can be
    placed. Armour on a body. The host's surface is the deliverable and a torso
    is not arithmetic over primitives, so the host is generated and the layers
    are stated — the hybrid route.

:data:`SURFACE`
    No assembly at all. A face, a tree, hair. The surface is the whole point,
    so a spec is the wrong tool.

A strategy is registered by the package that can also *build* what it claims,
so each package owns the vocabulary for its own domain. `human_template` knows
the word "pauldron" because it ships the plate that goes there, the landmarks
to measure it against, and the fitting code to place it. Adding a domain is
therefore registering a package, not extending a shared list:

    routing.register("submarine", claim)
    suits_code_asset("submarine")     # -> code, claimed_by="submarine"
    routing.unregister("submarine")
    suits_code_asset("submarine")     # -> ambiguous, claimed_by=None

`register` refuses a duplicate name unless `replace=True`, because two
strategies on one name make the route depend on import order.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

#: Parts beside each other, joined by adjacency. Fully describable: `code`.
COMPOSED = "composed"

#: Layers on a host that must be measured first. Host generated, layers
#: stated: the hybrid route.
NESTED = "nested"

#: One inseparable surface, no assembly to describe: `generate`.
SURFACE = "surface"

TOPOLOGIES = (COMPOSED, NESTED, SURFACE)

#: What each topology implies about the route. The mapping is here, once,
#: rather than in each strategy: a strategy reports what it *sees*, and what
#: that means for the pipeline is a decision for the operator.
#:
#: ``NESTED`` reports ``generate`` rather than a route of its own because the
#: caller's next action is to generate something — the host. The division of
#: labour is in the reason and in :attr:`Claim.topology`, so a caller that
#: understands hybrid builds can read it without a new route name breaking
#: every caller that only knows the three.
ROUTE_FOR_TOPOLOGY: dict[str, tuple[bool, str]] = {
    COMPOSED: (True, "code"),
    NESTED: (False, "generate"),
    SURFACE: (False, "generate"),
}

#: Strength tiers. A structural observation outranks counted evidence, because
#: the two are not the same kind of claim: "this needs a host to exist first"
#: is a fact about assembly, while "three of my words appear" is a guess that
#: happens to be quantified. Counting them against each other is what sent
#: "female knight in plate armour" to `code` at 0.9 confidence — one word,
#: "armour", outvoting the knight wearing it.
EVIDENCE = 0
STRUCTURAL = 1


@dataclass(frozen=True)
class Claim:
    """One strategy's answer for one subject.

    ``strength`` is only compared against claims in the same ``tier``, and only
    to decide *which* claim wins — never converted into a confidence directly,
    since how many words matched is not how sure anyone should be.
    """

    topology: str
    strength: float
    reason: str
    evidence: tuple[str, ...] = ()
    tier: int = EVIDENCE
    #: Where the caller goes next: the module that can build this. A claim that
    #: routes to `generate` may leave it empty.
    builder: str = ""
    #: Anything a strategy wants to hand back — measured landmarks, a suggested
    #: part list, the slot a piece belongs in. Ignored by the router.
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.topology not in TOPOLOGIES:
            raise ValueError(
                f"unknown topology {self.topology!r}; expected one of "
                f"{', '.join(TOPOLOGIES)}. A strategy reports how a subject is "
                "assembled, and the route follows from that."
            )


#: A strategy: given a subject and its asset type, claim it or decline.
#:
#: Declining is a real answer and is why this returns ``None`` rather than a
#: zero-strength claim. `human_template` declines "knight helmet" — a wearer
#: word plus an item word describes the item — and that has to leave the field
#: clear for another strategy rather than compete weakly with it.
Strategy = Callable[[str, str], "Claim | None"]

_STRATEGIES: dict[str, Strategy] = {}


def register(name: str, strategy: Strategy, *, replace: bool = False) -> None:
    """Add a strategy under ``name``.

    Refuses a duplicate unless ``replace``, because two strategies silently
    claiming the same domain is a routing bug that presents as an unstable
    route — whichever registered last wins, and registration order depends on
    import order.
    """

    if name in _STRATEGIES and not replace:
        raise ValueError(
            f"a strategy named {name!r} is already registered. Pass "
            "replace=True to override it deliberately, or pick another name: "
            "two strategies on one name makes the route depend on import order."
        )
    _STRATEGIES[name] = strategy


def unregister(name: str) -> None:
    """Remove a strategy. Mainly for tests, which must not leak into each other."""

    _STRATEGIES.pop(name, None)


def registered() -> tuple[str, ...]:
    """Names of the registered strategies, in registration order."""

    return tuple(_STRATEGIES)


def words(text: str) -> set[str]:
    """Whole words of ``text``, lowercased.

    Provided here so every strategy matches the same way. Substring matching is
    what made "man" match inside "human" and reported a face as somebody
    wearing kit — a confident wrong answer, which is the worst kind.
    """

    return set(re.findall(r"[a-z]+", text.lower()))


def claims(subject: str, asset_type: str = "prop") -> list[tuple[str, Claim]]:
    """Every strategy's claim on ``subject``, strongest first.

    A strategy that raises is a bug in that strategy, and it must not decide
    the route by crashing the router — but it must not be silently ignored
    either, so the exception is re-raised with the strategy named.
    """

    found: list[tuple[str, Claim]] = []
    for name, strategy in _STRATEGIES.items():
        try:
            claim = strategy(subject, asset_type)
        except Exception as exc:  # noqa: BLE001 - re-raised with attribution
            raise RuntimeError(
                f"routing strategy {name!r} failed on {subject!r}: {exc}"
            ) from exc
        if claim is not None:
            found.append((name, claim))
    found.sort(key=lambda pair: (pair[1].tier, pair[1].strength), reverse=True)
    return found


#: How close two same-tier claims have to be to count as undecided. Kept from
#: the counting version, where it was the rule that stopped one organic word
#: from vetoing two hard-surface ones: a "stone golem creature" genuinely reads
#: both ways and saying so is more use than picking.
PARITY = 2.0


def resolve(
    subject: str,
    asset_type: str = "prop",
    *,
    strategies: Iterable[tuple[str, Strategy]] | None = None,
) -> dict[str, Any]:
    """Decide the route for ``subject``.

    Returns ``{"suitable", "confidence", "route", "reason", "topology",
    "claimed_by", "builder", "detail", "competing"}``.

    ``strategies`` overrides the registry for one call, which is how a caller
    routes against its own taxonomy without touching global state — and how a
    test asserts a strategy's effect without leaking a registration.

    Two same-tier claims within :data:`PARITY` of each other return
    ``ambiguous``. Declining to guess is a result: a procedurally "described"
    face costs a correction loop to discover what one honest answer avoids.
    """

    if strategies is None:
        found = claims(subject, asset_type)
    else:
        saved = dict(_STRATEGIES)
        try:
            _STRATEGIES.clear()
            for name, strategy in strategies:
                _STRATEGIES[name] = strategy
            found = claims(subject, asset_type)
        finally:
            _STRATEGIES.clear()
            _STRATEGIES.update(saved)

    if not found:
        return {
            "suitable": False,
            "confidence": 0.3,
            "route": "ambiguous",
            "topology": None,
            "claimed_by": None,
            "builder": "",
            "detail": {},
            "competing": [],
            "reason": (
                f"{subject!r} matches no registered strategy. Prefer a spec "
                "when the object can be written down as boxes and cylinders, "
                "and generation when it cannot. A domain that comes up often "
                "should register a strategy rather than be guessed at here."
            ),
        }

    name, best = found[0]
    rivals = [(other, claim) for other, claim in found[1:]
              if claim.tier == best.tier]

    # Undecided, when the strongest two are in the same tier and close. Only
    # within a tier: a structural claim is not being outvoted by word counts.
    if rivals and abs(best.strength - rivals[0][1].strength) < PARITY:
        rival_name, rival = rivals[0]
        return {
            "suitable": False,
            "confidence": 0.5,
            "route": "ambiguous",
            "topology": None,
            "claimed_by": None,
            "builder": "",
            "detail": {},
            "competing": [(name, best.topology), (rival_name, rival.topology)],
            "reason": (
                f"{subject!r} reads two ways — {name} sees {best.topology} "
                f"({', '.join(best.evidence) or 'no specific words'}) and "
                f"{rival_name} sees {rival.topology} "
                f"({', '.join(rival.evidence) or 'no specific words'}). "
                "Decide from the shot: a spec if the silhouette carries it, "
                "generation if the surface does."
            ),
        }

    suitable, route = ROUTE_FOR_TOPOLOGY[best.topology]

    # Confidence reflects whether anything argued back, not how many words
    # matched. A lone claim on a clear subject is 0.9; a claim that beat a
    # rival is 0.7, because the rival saw something real.
    confidence = 0.9 if not rivals else 0.7
    if best.tier == STRUCTURAL:
        # A structural claim is not weakened by evidence-tier disagreement:
        # a knight in plate is a knight however hard-surfaced the plate is.
        confidence = 0.85

    return {
        "suitable": suitable,
        "confidence": confidence,
        "route": route,
        "topology": best.topology,
        "claimed_by": name,
        "builder": best.builder,
        "detail": dict(best.detail),
        "competing": [(other, claim.topology) for other, claim in found[1:]],
        "reason": best.reason,
    }
