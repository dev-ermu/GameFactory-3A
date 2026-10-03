"""Measure a T-pose figure's landmarks from its own vertices.

The piece that was missing from `humanoid.py`. That template stated where the
knee was, and its body was a stack of lathes fitted to those numbers — so the
landmarks were true by construction and true of nothing else. A generated body
has landmarks of its own, and fitting armour to it means reading them.

Why a T-pose specifically: every limb lies along a known axis, so a landmark
is a change in the *cross-section* along one direction rather than something
requiring a skeleton. The arms run along x, the legs and spine along y, and
that is what makes the measurements below simple enough to trust:

    shoulder height   where the x-span jumps as the arms begin
    shoulder x        where the arm band's *depth* collapses to arm-thickness
    arm axis          the y of the outstretched arm's centre
    wrist             the narrowest cross-section inboard of the hand, where
                      the hand is found by its own widening
    crotch            the lowest y at which two separate leg clusters exist
    knee              the local minimum of leg cross-section between crotch
                      and ankle
    waist             the narrowest x-span of the torso above the crotch

None of these needs the mesh to be anything in particular beyond a T-pose,
which is the point: the same code measures any figure a generator returns, and
`fit_report` states what it found so a wrong reading is visible rather than
silently wearing armour in the wrong place.
"""

from typing import Any, Sequence

Vec3 = tuple[float, float, float]


def _slices(positions: Sequence[Vec3], count: int = 64
            ) -> list[dict[str, Any]]:
    """Horizontal slices of a figure, each with its extents and population."""
    low = min(point[1] for point in positions)
    high = max(point[1] for point in positions)
    step = (high - low) / count
    out: list[dict[str, Any]] = []
    for index in range(count):
        floor = low + index * step
        band = [p for p in positions if floor <= p[1] < floor + step]
        if not band:
            out.append({"y": floor + step / 2, "n": 0,
                        "x_span": 0.0, "z_span": 0.0,
                        "x_low": 0.0, "x_high": 0.0})
            continue
        out.append({
            "y": floor + step / 2,
            "n": len(band),
            "x_span": max(p[0] for p in band) - min(p[0] for p in band),
            "z_span": max(p[2] for p in band) - min(p[2] for p in band),
            "x_low": min(p[0] for p in band),
            "x_high": max(p[0] for p in band),
        })
    return out


def _leg_split(positions: Sequence[Vec3], y: float, tolerance: float
               ) -> float | None:
    """Gap between the two legs at height ``y``, or None if they are joined.

    Measured as the widest run of empty x between the leftmost and rightmost
    material. Two legs read as two clusters with a gap; a pelvis reads as one.
    """
    band = [p for p in positions if abs(p[1] - y) < tolerance]
    if len(band) < 12:
        return None
    xs = sorted(p[0] for p in band)
    widest = 0.0
    for first, second in zip(xs, xs[1:]):
        widest = max(widest, second - first)
    return widest


def _arm_profile(positions: Sequence[Vec3], arm_y: float, span: float,
                 reach: float, steps: int = 48) -> list[tuple[float, float, float]]:
    """Cross-sections along the outstretched arm: (fraction of reach, z-depth, area).

    Sampled by x, since on a T-pose that is the direction the arm runs. Both
    the shoulder and the wrist are read off this one profile, so the two
    landmarks cannot disagree about where the arm is.
    """
    band = [p for p in positions if abs(p[1] - arm_y) < span * 0.045]
    out: list[tuple[float, float, float]] = []
    for step in range(steps + 1):
        here = reach * step / steps
        column = [p for p in band if abs(abs(p[0]) - here) < reach * 0.035]
        if len(column) < 5:
            continue
        depth = max(p[2] for p in column) - min(p[2] for p in column)
        thick = max(p[1] for p in column) - min(p[1] for p in column)
        out.append((step / steps, depth / span, thick * depth / (span * span)))
    return out


def measure_figure(source: str, *, trim: Sequence[float] | None = None
                   ) -> dict[str, Any]:
    """Landmarks of a T-pose figure, in the placed asset's own metres.

    Returns the same keys `templates/humanoid.LANDMARKS` uses, so a kit
    written against a stated body fits a generated one unchanged — plus
    ``measured_from`` and ``confidence`` notes, because a landmark read off a
    mesh can be wrong and a caller needs to be able to tell.

    Heights are fractions of the figure's own height, then multiplied by the
    height the caller is placing it at. That keeps the reading independent of
    the source file's arbitrary scale.
    """

    from models.common.glb_writer import load_mesh_asset

    asset = load_mesh_asset(source, trim)
    positions = asset["positions"]
    low = min(point[1] for point in positions)
    high = max(point[1] for point in positions)
    span = high - low
    if span <= 0:
        raise ValueError(f"{source}: the figure has no height")

    slices = _slices(positions)
    populated = [entry for entry in slices if entry["n"] >= 8]
    if len(populated) < 12:
        raise ValueError(
            f"{source}: too sparse to measure ({len(populated)} usable slices). "
            "This wants a single figure, not a scene."
        )

    def fraction(y: float) -> float:
        return (y - low) / span

    # --- arms: the slices whose x-span is far above the body's own width ---
    # The median, not a lower quantile. A lower one was tried to stop dense
    # arms dragging the threshold up, and it broke the opposite way: the
    # measure of "the body's own width" has to be a width the body actually
    # has, and a third-quantile slice on a figure with legs is a shin.
    spans = sorted(entry["x_span"] for entry in populated)
    typical = spans[len(spans) // 2]
    arm_slices = [entry for entry in populated
                  if entry["x_span"] > typical * 2.2]
    if not arm_slices:
        raise ValueError(
            f"{source}: no slice is more than twice the body's width, so this "
            "is not a T-pose. Arms out horizontally is what makes the limbs "
            "measurable without a skeleton."
        )
    arm_y = sum(entry["y"] for entry in arm_slices) / len(arm_slices)
    half_span = max(entry["x_span"] for entry in arm_slices) / 2.0

    # --- shoulder and wrist, both from one profile along the arm ------------
    # A torso is deep front-to-back and an arm is not, so where the arm band's
    # z-depth collapses is where the torso ends. That is a threefold change
    # (0.13 H to 0.04 H here), which is why it is used instead of the previous
    # "widest torso just under the arms": that read shoulder_x as 0.103 m on a
    # 1.72 m figure, a 0.21 m shoulder width, because a slice below the arms
    # crosses the chest and not the joint.
    profile = _arm_profile(positions, arm_y, span, half_span)
    shoulder_x = typical / 2.0
    wrist_fraction = 0.86
    if len(profile) >= 12:
        torso_depth = max(depth for _, depth, _ in profile[:6])
        arm_depth = min(depth for _, depth, _ in profile)
        if torso_depth > arm_depth * 1.6:
            threshold = (torso_depth + arm_depth) / 2.0
            crossing = next((f for f, depth, _ in profile if depth < threshold),
                            None)
            if crossing is not None:
                shoulder_x = crossing * half_span

        # The wrist is the narrowest cross-section outboard of mid-arm, by
        # *area*. Not by height alone: fingers are flatter than a wrist, so on
        # the decimated body that read the fingertips (0.95 of reach) and put
        # a gauntlet past the end of the arm. The high-poly body only escaped
        # it by 0.0242 against 0.0247. Area separates them cleanly — a hand is
        # wider than a wrist even when it is thinner.
        outboard = [entry for entry in profile if entry[0] > 0.25]
        if outboard:
            wrist_fraction = min(outboard, key=lambda entry: entry[2])[0]

    # --- crotch: highest height at which the legs are still separate -------
    # Highest, not lowest. Legs are separate from the ankles up, so scanning
    # upward for the first split finds the ankles — measured 0.305 of height
    # where a crotch is near 0.48. One slice above the crotch the pelvis joins
    # them, which is what makes the topmost split the landmark.
    tolerance = span * 0.012
    crotch_y = low + span * 0.48
    for entry in reversed(populated):
        if not 0.30 < fraction(entry["y"]) < 0.60:
            continue
        gap = _leg_split(positions, entry["y"], tolerance)
        # 3% of height, not 1.2%: at the looser threshold the dip either side
        # of a single leg counts as two legs.
        if gap is not None and gap > span * 0.03:
            crotch_y = entry["y"]
            break

    # --- knee: narrowest leg cross-section between crotch and ankle --------
    leg_slices = [entry for entry in populated
                  if low + span * 0.06 < entry["y"] < crotch_y - span * 0.06]
    knee_y = low + span * 0.28
    if len(leg_slices) >= 5:
        # Between a quarter and a half of the way up: a knee on a standing
        # figure sits near 0.28, and widening this window lets the ankle or the
        # thigh win on cross-section alone.
        middle = [entry for entry in leg_slices
                  if 0.20 < fraction(entry["y"]) < 0.42]
        if middle:
            knee_y = min(middle, key=lambda entry: entry["x_span"])["y"]

    # --- waist: narrowest torso in the band a waist can occupy ------------
    # Bounded rather than "narrowest below the arms", which lands on the
    # ribcage: the chest above a waist is narrower than the bust, so an
    # unbounded search finds the wrong pinch. Measured 1.169 m on a 1.72 m
    # figure that way, where a waist is near 1.07.
    waist_y = crotch_y + span * 0.10
    upper = min(arm_y - span * 0.10, low + span * 0.68)
    torso = [entry for entry in populated
             if crotch_y + span * 0.05 < entry["y"] < upper
             and entry["x_span"] < typical * 2.2]
    if torso:
        waist_y = min(torso, key=lambda entry: entry["x_span"])["y"]

    # --- head: where the neck's cross-section pinches above the arms -------
    neck_y = arm_y + span * 0.03
    neck_bottom = neck_y
    above = [entry for entry in populated if entry["y"] > arm_y + span * 0.01]
    if len(above) >= 4:
        coarse = min(above[:max(3, len(above) // 3)],
                     key=lambda entry: entry["x_span"])
        # Re-scanned finely around the coarse hit. A neck narrows over a couple
        # of centimetres and the 64 slices the rest of this uses are 2.7 cm
        # apart on a 1.72 m figure, so the coarse pinch landed 0.022 m low, on
        # the top of the trapezius where the body is 0.276 m wide against the
        # neck's 0.177 m. A collar sized to the wrong one of those is visibly
        # sunk into the shoulders. Not a finer global scan: at 128 slices the
        # thin bands break the waist and crotch readings, which need enough
        # vertices per slice to be stable.
        fine = _slices(
            [p for p in positions
             if abs(p[1] - coarse["y"]) < span * 0.06], count=24,
        )
        candidates = [entry for entry in fine if entry["n"] >= 8]
        neck_y = (min(candidates, key=lambda entry: entry["x_span"])["y"]
                  if candidates else coarse["y"])
        # How far down the neck stays neck-width, so a collar can be as tall
        # as the column it wraps and no taller. Walked down the *fine* slices:
        # against the coarse ones the first slice below the pinch is already
        # 2.7 cm away and into the shoulders, so the column measured zero
        # height and the spec validator refused a plate with a zero extent.
        neck_span = min((entry["x_span"] for entry in candidates),
                        default=coarse["x_span"])
        limit = neck_span * 1.35
        neck_bottom = neck_y
        for entry in reversed([e for e in candidates if e["y"] < neck_y]):
            if entry["x_span"] > limit:
                break
            neck_bottom = entry["y"]
        if neck_bottom >= neck_y - span * 0.005:
            # Nothing below the pinch is neck-width: the neck is a short
            # column on this figure. Fall back to the fine slice spacing so a
            # collar still has height rather than none.
            neck_bottom = neck_y - span * 0.02

    # Leg x from the widest point of the thigh, halved. A single figure-wide
    # fallback; `leg_profile` below is what a placement should use.
    thigh = [entry for entry in populated
             if 0.42 < fraction(entry["y"]) < 0.52]
    leg_x = (max(entry["x_span"] for entry in thigh) / 4.0
             if thigh else span * 0.055)

    # How far out one leg's centre is, at each height.
    #
    # The same lesson as the centreline below, on the other axis: legs are not a
    # vertical pair of columns. This figure's stand splays them, so the shin
    # centres 0.045 m further out than `leg_x` — which is read at the *thigh* —
    # and greaves placed on that one number sat inboard of the legs entirely.
    # Rendered, it read as four limbs: two plates hanging between two bare legs.
    #
    # Measured per side and averaged, because a mirrored pair is placed by one
    # number and the two legs are not symmetric. Sectioned on the outboard half
    # only, so the crotch — where both legs merge into one span — cannot report
    # a single leg as being on the centreline.
    def leg_profile(bands: int = 20) -> list[tuple[float, float]]:
        step = span / bands
        rows: list[tuple[float, float]] = []
        for index in range(bands):
            floor_y = low + index * step
            # Below the crotch only: above it the legs are one body and a
            # "leg centre" is not a thing that exists.
            if (floor_y - low) / span > 0.50:
                break
            per_side = []
            for side_sign in (-1.0, 1.0):
                side = [point for point in positions
                        if floor_y <= point[1] < floor_y + step
                        and point[0] * side_sign > span * 0.01]
                if len(side) >= 4:
                    per_side.append((min(point[0] for point in side)
                                     + max(point[0] for point in side))
                                    / 2.0 * side_sign)
            if per_side:
                rows.append(((floor_y + step / 2.0 - low) / span,
                             sum(per_side) / len(per_side) / span))
        return rows

    legline = leg_profile()

    # --- where each limb sits front-to-back ---------------------------------
    # A body is not centred on z, and until now nothing measured that, so every
    # placement used 0. On this figure the arm's centreline runs at z = -0.059
    # and the instep's at -0.042, so the arm plates floated 0.06 m in front of
    # the arm and the sabatons sat off the foot. The plates were the right size
    # and on the right landmark; they were in the wrong place because the third
    # axis was assumed instead of read.
    #
    # The median of per-slice centres, not the centre of the whole band. One
    # min/max over a band lets its deepest slice decide: across the arm that is
    # the deltoid, three times the depth of the forearm, and it pulled the
    # reading from -0.059 to -0.047. A limb's axis is the middle of its
    # sections, not the middle of its bounding box.
    #
    # Falls back to the whole band's centre when the mesh is too coarse to
    # section — a primitive limb has vertices only at its two ends, so every
    # bucket in between is empty. Returning 0.0 there was worse than a coarse
    # answer: 0.0 is the assumption this function exists to replace, and it
    # returned it silently.
    def z_centre(chosen, *, along: int) -> float:
        if len(chosen) < 4:
            return 0.0
        step = span * 0.03
        buckets: dict[int, list[float]] = {}
        for point in chosen:
            buckets.setdefault(int(point[along] / step), []).append(point[2])
        centres = sorted((min(zs) + max(zs)) / 2.0
                         for zs in buckets.values() if len(zs) >= 4)
        if len(centres) >= 3:
            return centres[len(centres) // 2] / span
        return ((min(point[2] for point in chosen)
                 + max(point[2] for point in chosen)) / 2.0) / span

    # Along the arm, outboard of the shoulder. Inboard of that the torso is
    # three times deeper and would decide the answer. Sectioned along x,
    # because that is the axis a T-pose arm runs down.
    arm_z = z_centre([point for point in positions
                      if abs(point[0]) > shoulder_x * 1.4
                      and abs(point[1] - arm_y) < span * 0.05], along=0)

    # The ankle and instep: above the sole, below the shin. Widened until it
    # finds material rather than fixed at 3-8% of height — a primitive leg has
    # vertices only where its cylinders end, and on the test fixture that band
    # was empty, so both the depth and the width fell back to defaults without
    # saying so.
    def ankle_band(limit: float) -> list:
        return [point for point in positions
                if low + span * 0.01 < point[1] < low + span * limit]

    instep_band = ankle_band(0.08)
    for wider in (0.12, 0.18, 0.25):
        if len(instep_band) >= 8:
            break
        instep_band = ankle_band(wider)

    foot_z = z_centre(instep_band, along=1)

    # The whole foot, not just the instep: a sabaton has to cover the toes and
    # the ankle, and those are the extremes. Typed sizes put a 0.115 x 0.24 x
    # 0.09 plate on a 0.100 x 0.229 x 0.145 foot — the toes came out through the
    # front and the top of the foot stood above the boot.
    foot_band = [point for point in positions
                 if point[1] < low + span * 0.09]
    if len(foot_band) >= 8:
        per_side = []
        for side_sign in (-1.0, 1.0):
            side = [point for point in foot_band if point[0] * side_sign > 0.0]
            if len(side) < 4:
                continue
            per_side.append((
                min(point[0] for point in side) * side_sign,
                max(point[0] for point in side) * side_sign,
                max(point[2] for point in side) - min(point[2] for point in side),
                max(point[1] for point in side) - low,
                (min(point[2] for point in side)
                 + max(point[2] for point in side)) / 2.0,
            ))
        if per_side:
            # Widened to span both feet's *outermost* reach either side of the
            # mirrored centre, rather than to the average foot's width. A
            # generated body is not symmetric — this one's feet centre at -0.157
            # and +0.179, 0.022 m apart — and a mirrored pair of plates is
            # placed by one number, so a plate sized to the average covers one
            # foot and leaves the other's edge outside it. Sizing to the union
            # is the honest answer for a pair that must be symmetric.
            inner = min(min(row[0], row[1]) for row in per_side)
            outer = max(max(row[0], row[1]) for row in per_side)
            foot_x = (inner + outer) / 2.0 / span
            foot_width = (outer - inner) / span
            # Each foot on its own, as well as the union above.
            #
            # The union is what a *mirrored* pair has to be sized to, and it is
            # 0.121 m here against a 0.098 m foot — 23% of bulk that exists only
            # to absorb the 0.022 m the two feet differ by. Reported per side so
            # a caller can instead place two boots, each slim and each on its own
            # foot, which is what a generated body's asymmetry actually calls
            # for. Neither is wrong; only having the union forced the trade.
            foot_span = max(abs(row[1] - row[0]) for row in per_side) / span
            foot_sides = [
                ((row[0] + row[1]) / 2.0 * sign / span, row[4] / span)
                for row, sign in zip(per_side, (-1.0, 1.0))
            ]
            foot_depth = max(row[2] for row in per_side) / span
            # How high the foot proper is, i.e. where it stops being a foot.
            #
            # NOT `max(y) - low` over the band, which is what this was: the band
            # is defined as the bottom 9% of the figure, so that returned 0.1524
            # against a 0.1548 cutoff — it measured the band, not the foot. A
            # boot sized to it came out 0.152 m tall on a 0.133 m width and
            # rendered as a cube.
            #
            # A foot's section is long and narrow; an ankle's is round. So the
            # foot ends where its depth has fallen towards the leg's, taken here
            # at 40% of the sole's depth — 0.065 m on this figure, which agrees
            # with the independently measured ankle at 0.060 m.
            sole_depth = max(row[2] for row in per_side)
            foot_top = low + span * 0.09
            step = span * 0.008
            level = low + step
            while level < foot_top:
                section = [point for point in foot_band
                           if level <= point[1] < level + step]
                if len(section) >= 4:
                    depth = (max(point[2] for point in section)
                             - min(point[2] for point in section))
                    if depth < sole_depth * 0.40:
                        break
                level += step
            foot_height = (level - low) / span
            foot_z = sum(row[4] for row in per_side) / len(per_side) / span

            # Where each ankle is, and how thick, at the height the foot ends.
            #
            # Needed because a boot's shaft does not sit above the *footprint*.
            # The sole runs forward under the toes, so its centre is 47 mm in
            # front of the ankle on this figure — a shaft placed on the footprint
            # centre stood proud of the shin, and the greave above it hung
            # visibly behind, missing the boot altogether.
            #
            # Also the width: an ankle is 0.056 m across where the sole is
            # 0.101 m. A shaft as wide as the foot is why the boot rendered as a
            # rectangular block from the front — an extrusion has one thickness,
            # so the only way to get a boot's silhouette is to stop extruding at
            # the instep and put the shaft on separately.
            ankle_sides = []
            for point_sign in (-1.0, 1.0):
                ring = [point for point in positions
                        if point[0] * point_sign > 0.0
                        and abs(point[1] - level) < span * 0.012]
                if len(ring) < 4:
                    continue
                xs = [point[0] for point in ring]
                zs = [point[2] for point in ring]
                # x is signed, matching `foot_sides`: the left ankle reports
                # negative. Returning a magnitude here and a signed value there
                # is the kind of inconsistency a caller discovers by placing a
                # boot on the wrong side of the figure.
                ankle_sides.append((
                    (min(xs) + max(xs)) / 2.0 / span,
                    (min(zs) + max(zs)) / 2.0 / span,
                    (max(xs) - min(xs)) / span,
                    (max(zs) - min(zs)) / span,
                ))
        else:
            foot_x = leg_x / span
            foot_width = foot_depth = foot_height = foot_span = 0.0
            foot_sides = []
            ankle_sides = []
    else:
        foot_x = leg_x / span
        foot_width = foot_depth = foot_height = foot_span = 0.0
        foot_sides = []
        ankle_sides = []

    # The torso's depth is not one number. A body leans, and the chest, the
    # waist and the neck sit at different depths — on this figure the chest
    # centres at +0.023 and the neck at -0.067, 0.090 m apart. One `torso_z`
    # measured over the chest and reused for every midline slot put the gorget
    # 0.090 m in front of the throat and the helm 0.057 m in front of the face.
    #
    # So it is sampled as a profile and read back at the height each piece
    # actually occupies. Stored as fractions of height, like every other
    # landmark, so a caller scaling the figure gets scaled depths for free.
    def centreline_profile(bands: int = 24) -> list[tuple[float, float]]:
        step = span / bands
        rows: list[tuple[float, float]] = []
        for index in range(bands):
            floor_y = low + index * step
            slice_points = [point for point in positions
                            if floor_y <= point[1] < floor_y + step
                            and abs(point[0]) < shoulder_x]
            if len(slice_points) < 6:
                continue
            middle = (min(point[2] for point in slice_points)
                      + max(point[2] for point in slice_points)) / 2.0
            rows.append(((floor_y + step / 2.0 - low) / span, middle / span))
        return rows

    centreline = centreline_profile()
    # A single figure-wide fallback, for callers that want one number and for
    # a mesh too sparse to profile.
    torso_z = (sorted(depth for _, depth in centreline)[len(centreline) // 2]
               if centreline else 0.0)


    # Girth at the landmarks a wrapped plate has to clear. A plate is fitted
    # by one factor, so what decides its size is the cross-section it must
    # enclose, not the length it must span — the cuirass was sized from
    # shoulder-to-waist and came out 0.172 m deep around a 0.181 m chest,
    # sunk into the ribcage front and back.
    #
    # Widest over a band, not a single slice. A plate has thickness and is
    # often offset from its landmark, so it covers a range of heights and the
    # body is widest somewhere in that range rather than at the centre: the
    # belt, 0.03 m below the waist, read 0.179 m against a 0.208 m body from a
    # single-slice measurement, and sat inside the figure.
    #
    # Arms excluded from the *width* only. On a T-pose the arms cross the
    # chest's own height, so a width read without excluding them is the
    # wingspan: 1.113 m on a 1.80 m figure whose torso is 0.34 m wide, and a
    # cuirass scaled to that is a barrel. Depth is read from every slice in the
    # band, because an outstretched arm adds nothing front-to-back — excluding
    # arm slices from depth too dropped the measured chest from 0.181 m to
    # 0.106 m, since at chest height on this figure almost every slice has an
    # arm in it, and the cuirass went back to sitting inside the ribcage.
    def girth_at(y: float, reach: float = 0.045) -> tuple[float, float]:
        band = [entry for entry in populated
                if abs(entry["y"] - y) <= reach * span]
        if not band:
            band = [min(populated, key=lambda entry: abs(entry["y"] - y))]
        torso = [entry for entry in band
                 if entry["x_span"] < typical * 2.2]
        if not torso:
            # No arm-free slice in the band: fall back to the nearest one
            # anywhere on the figure rather than to a slice with an arm in it.
            # `or band` was the fallback and it returned the wingspan, 1.088 m,
            # as a chest width — which is the exact reading this exclusion
            # exists to prevent.
            elsewhere = [entry for entry in populated
                         if entry["x_span"] < typical * 2.2]
            torso = ([min(elsewhere, key=lambda entry: abs(entry["y"] - y))]
                     if elsewhere else band)
        return (max(entry["x_span"] for entry in torso) / span,
                max(entry["z_span"] for entry in band) / span)

    chest_y_absolute = low + span * (
        fraction(waist_y) + (fraction(arm_y) - fraction(waist_y)) * 0.55
    )
    chest_width, chest_depth = girth_at(chest_y_absolute)
    waist_width, waist_depth = girth_at(waist_y)
    hip_width, hip_depth = girth_at(crotch_y + span * 0.045)
    # The neck is measured from the vertices directly, over exactly the band a
    # collar occupies. The coarse slices are 2.7 cm apart and a neck is not,
    # so reading it off them mixed in the shoulders — which are four times
    # wider, and a collar sized between the two sits inside the body.
    collar = [p for p in positions if neck_bottom <= p[1] <= neck_y]
    if len(collar) >= 12:
        neck_width = (max(p[0] for p in collar)
                      - min(p[0] for p in collar)) / span
        neck_depth = (max(p[2] for p in collar)
                      - min(p[2] for p in collar)) / span
    else:
        neck_width, neck_depth = girth_at(neck_y, reach=0.012)

    fractions = {
        "ankle_y": 0.035,
        "knee_y": fraction(knee_y),
        "crotch_y": fraction(crotch_y),
        "hip_y": fraction(crotch_y) + 0.045,
        "waist_y": fraction(waist_y),
        # Between the waist and the shoulder, which is where a breastplate's
        # centre goes. Derived rather than measured: the widest point of a
        # chest is not the middle of a cuirass, and the middle is what a
        # placement needs.
        "chest_y": fraction(waist_y) + (fraction(arm_y) - fraction(waist_y)) * 0.55,
        "shoulder_y": fraction(arm_y),
        "neck_y": fraction(neck_y),
        # The midpoint of neck-to-crown, exactly. A helm is scaled to that
        # distance, so its centre has to be that midpoint or it hangs off one
        # end: a `+ 0.02` nudge here put the crown 0.070 m above a 1.72 m
        # figure's own head.
        "head_y": (fraction(neck_y) + 1.0) / 2.0,
        "elbow_y": fraction(arm_y),
    }

    return {
        "source": asset["source"],
        "triangles": asset["triangles"],
        "unit_extent": asset["unit_extent"],
        "fractions": fractions,
        # Lateral distances, as fractions of height, for the same reason.
        "shoulder_x_fraction": shoulder_x / span,
        "leg_x_fraction": leg_x / span,
        "foot_x_fraction": foot_x,
        "arm_reach_fraction": half_span / span,
        "wrist_along_arm": wrist_fraction,
        # The bottom of the neck column, so a collar can be as tall as the
        # column and no taller. Kept out of `fractions` because that table is
        # the anatomical-order check's input and this is a bound, not a joint.
        "neck_bottom_fraction": fraction(neck_bottom),
        # Girths, so a plate can be sized to what it wraps.
        "girth_fractions": {
            "chest_width": chest_width, "chest_depth": chest_depth,
            "waist_width": waist_width, "waist_depth": waist_depth,
            "hip_width": hip_width, "hip_depth": hip_depth,
            "neck_width": neck_width, "neck_depth": neck_depth,
            # The foot's own box, so a sabaton covers the foot rather than a
            # typed guess at one.
            "foot_width": foot_width, "foot_depth": foot_depth,
            "foot_height": foot_height,
            "foot_span": foot_span,
        },
        # Front-to-back centres, so a plate lands on the limb rather than on
        # the centreline the limb is not on.
        "z_fractions": {
            "arm_z": arm_z, "foot_z": foot_z, "torso_z": torso_z,
        },
        # The midline's depth sampled up the figure, as (height, depth) pairs
        # in fractions of height. A single torso depth cannot serve the chest
        # and the throat at once; they are 0.090 m apart here.
        "centreline": centreline,
        "legline": legline,
        "foot_sides": foot_sides,
        "ankle_sides": ankle_sides,
        "measured_from": "vertex cross-sections of a T-pose",
    }


def landmarks_for(source: str, height_metres: float,
                  *, trim: Sequence[float] | None = None) -> dict[str, float]:
    """Landmarks in metres for a figure placed at ``height_metres``.

    Keys match `templates/humanoid.LANDMARKS`, so a kit written against a
    stated body fits a measured one with no changes — which is the property
    that makes the body swappable.
    """

    measured = measure_figure(source, trim=trim)
    out = {
        name: value * height_metres
        for name, value in measured["fractions"].items()
    }
    out["height"] = height_metres
    out["shoulder_x"] = measured["shoulder_x_fraction"] * height_metres
    out["leg_x"] = measured["leg_x_fraction"] * height_metres
    out["foot_x"] = measured["foot_x_fraction"] * height_metres
    out["arm_reach"] = measured["arm_reach_fraction"] * height_metres
    # Along the outstretched arm, which is where a gauntlet goes on a T-pose.
    out["wrist_x"] = out["arm_reach"] * measured["wrist_along_arm"]
    # Midway between the shoulder and the wrist, both of which are measured.
    # Previously `wrist_x * 0.55`, which ignored where the arm actually starts
    # and so put the elbow inside the ribcage on a broad figure.
    out["elbow_x"] = (out["shoulder_x"] + out["wrist_x"]) / 2.0
    out["neck_bottom_y"] = measured["neck_bottom_fraction"] * height_metres
    for name, value in measured["girth_fractions"].items():
        out[name] = value * height_metres
    for name, value in measured["z_fractions"].items():
        out[name] = value * height_metres

    # The centreline in metres, as a flat list of alternating height and depth.
    #
    # Flat, and not a list of pairs or a callable, because this dictionary is
    # documented as landmarks in metres and callers scale or round every value
    # in it: `{k: round(v, 4) for k, v in marks.items()}` is exactly what the
    # knight builder does, and a nested list broke it. A number-shaped payload
    # keeps that contract; :func:`depth_at` is how it is read.
    out["centreline"] = [
        value * height_metres
        for height, depth in measured.get("centreline") or ()
        for value in (height, depth)
    ]
    out["foot_span"] = (measured["girth_fractions"].get("foot_span", 0.0)
                        * height_metres)
    # Flattened, like `centreline`: a landmark dictionary of scalars is what
    # every consumer rounds and serialises, and a nested list of pairs in it is
    # what broke `meta.json` writing once already.
    out["foot_sides"] = [
        value * height_metres
        for x_centre, z_centre in measured.get("foot_sides") or ()
        for value in (x_centre, z_centre)
    ]
    # (x centre, z centre, width, depth) per side, flattened for the same
    # reason: every consumer rounds and serialises this dictionary.
    out["ankle_sides"] = [
        value * height_metres
        for row in measured.get("ankle_sides") or ()
        for value in row
    ]
    out["legline"] = [
        value * height_metres
        for height, lateral in measured.get("legline") or ()
        for value in (height, lateral)
    ]
    return out


def depth_at(landmarks: dict[str, Any], y: float) -> float:
    """How deep the body's midline sits at height ``y``, in metres.

    A body is not flat front-to-back, and one torso depth cannot serve every
    midline slot: on the figure this was measured from, the chest centres at
    +0.023 and the throat at -0.067, so a gorget placed at the chest's depth
    stood 0.090 m in front of the neck it was meant to enclose.

    Falls back to ``torso_z`` for a body measured before the profile existed,
    and to zero for one with neither — a wrong depth is recoverable, a crash on
    a missing key in a placement is not.
    """

    flat = landmarks.get("centreline") or ()
    if len(flat) < 2:
        return float(landmarks.get("torso_z", 0.0))
    pairs = list(zip(flat[0::2], flat[1::2]))
    return float(min(pairs, key=lambda row: abs(row[0] - y))[1])


def leg_x_at(landmarks: dict[str, Any], y: float) -> float:
    """How far out one leg's centre sits at height ``y``, in metres.

    :func:`depth_at`'s counterpart on the lateral axis, and it exists for the
    same reason: a pair of legs is not a pair of vertical columns. On the figure
    this was measured from they splay, so the shin runs 0.045 m further out than
    the thigh — and `leg_x`, which is read at the thigh, put the greaves inboard
    of the legs altogether. Rendered, that read as four limbs: two plates
    hanging between two bare legs.

    Falls back to ``leg_x`` for a body measured before the profile existed, and
    to zero for one with neither.
    """

    flat = landmarks.get("legline") or ()
    if len(flat) < 2:
        return float(landmarks.get("leg_x", 0.0))
    pairs = list(zip(flat[0::2], flat[1::2]))
    return float(min(pairs, key=lambda row: abs(row[0] - y))[1])
