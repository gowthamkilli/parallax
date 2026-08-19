"""The fusion layer. This is the technical core of the system.

Four problems, solved in order:

1. TIME SYNCHRONISATION -- what clock accuracy does the mesh actually need?
2. ASSOCIATION          -- which reports describe the same physical event?
3. RANGING              -- where is it, and by which of three independent sources?
4. CONFIDENCE           -- how much should the commander believe the fix?

------------------------------------------------------------------------
1. TIME SYNCHRONISATION: the requirement is 10 ms, not 1 us
------------------------------------------------------------------------
The architecture deliberately keeps TDOA *inside* a node. Each node solves
its own bearing from its own six microphones using its own local clock;
inter-microphone delays are hundreds of microseconds and are measured against
a single crystal, so mesh clock offset cancels completely.

Had we instead treated the whole squad as one giant distributed array, we
would need sub-microsecond alignment across a 1-2 km mesh -- 1 us of clock
error is 0.34 m of apparent path difference, and at a 1 km baseline that is
still a usable bearing, but the sync engineering becomes the project.

Because bearings are computed locally, the mesh clock only has to be good
enough to *associate* events, and association windows are hundreds of
milliseconds to seconds (see below). A 10 ms bound is therefore sufficient,
which plain NTP over the mesh already meets.

We still specify GPS/GNSS PPS discipline (sub-microsecond, typically <100 ns)
because the nodes need GNSS for position anyway and PPS is free once you have
the receiver. The tiering matters for GNSS-denied operation:

    GNSS PPS locked   -> < 1 us      -> everything works, incl. future
                                        cross-node TDOA
    PTP over mesh     -> ~10-100 us  -> everything in this document works
    NTP over mesh     -> ~1-10 ms    -> everything in this document works
    Free-running TCXO -> ~1 ppm      -> 3.6 ms drift per hour; needs a
                                        resync roughly hourly

The design's tolerance to bad sync is a feature, and it exists because of one
architectural choice, not because of clever engineering.

------------------------------------------------------------------------
2. ASSOCIATION: a different window for each pair of physics
------------------------------------------------------------------------
FLASH <-> ACOUSTIC, SAME NODE. Light covers 400 m in 1.3 ns; sound takes
1.17 s. So the muzzle flash is, for our purposes, coincident with the shot
and the acoustic arrival lags it by exactly the propagation time:

    dt = R / c      -> gate: dt in [0, R_max/c]

At the 400 m envelope edge that is a 1.17 s window; at the 3 km mesh
relevance cutoff, 8.75 s. We gate at R_max = 1200 m -> 3.5 s, wide enough to
catch shots beyond the design envelope without opening the door to unrelated
events. A negative dt is physically impossible and rejects the pairing
outright.

SHOCKWAVE <-> ACOUSTIC, SAME NODE. The crack always arrives before the blast
(it outruns its own gun), bounded by the crack-thump method's own reach
(MAX_CRACK_THUMP_RANGE_M in parallax/ballistics.py), not the flash/acoustic
envelope above -- a shockwave this node can detect at all implies a much
shorter range than the flash/acoustic case ever needs to consider. Critically,
the crack and the blast are EXPECTED to arrive from noticeably different
bearings (the split IS the Mach-angle signal), so unlike every other same-node
pairing this one skips the bearing-agreement check entirely -- see
_compatible.

ACOUSTIC <-> ACOUSTIC, DIFFERENT NODES. Two nodes separated by baseline B
hear the same shot at times differing by at most B/c, achieved when the
shooter is collinear with both:

    |t_1 - t_2| <= B / c + clock_error

For nodes 1 km apart that is 2.92 s. This window is *derived from node
geometry per pair*, not a tuned constant -- a pair of nodes 50 m apart gets a
146 ms window and rejects far more aggressively than a pair 1 km apart. That
is the correct behaviour and a fixed global window cannot produce it.

DOUBLE-COUNTING. The rule that prevents a flash and its own acoustic report
being scored as two threats: association is by *physical event*, not by
report. Reports enter tracks; tracks are what the dashboard counts. A track
carrying an optical and an acoustic report from the same node is one contact
with two modalities and higher confidence -- never two contacts.

------------------------------------------------------------------------
3. RANGING: THREE INDEPENDENT SOURCES, cross-validated, never picked blind
------------------------------------------------------------------------
    (a) FLASH/ACOUSTIC dt, single node       -- R = c * dt. Needs an optical
                                                 channel.
    (b) BALLISTIC CRACK-THUMP, single node   -- R from the shockwave/blast
                                                 bearing split, timing and
                                                 N-wave shape (see
                                                 parallax/ballistics.py). Needs
                                                 a supersonic round and a
                                                 SHOCKWAVE + ACOUSTIC pair.
    (c) TRIANGULATION, >=2 bearings          -- good, if the crossing angle is.
    (d) BEARING ONLY                          -- range is NOT reported. The
                                                 dial shows a ray, not a blob.

The solver is one source of evidence, not the unquestioned truth: whenever
more than one of (a)/(b)/(c) fires for the same track, _combine_range_estimates
cross-validates them (Stage 13/21 territory -- don't silently average an
outlier, and don't silently pick a winner either). If they agree within
``range_disagreement_sigma`` combined sigma they are fused by inverse-variance
weighting; if they disagree, the disagreement is recorded explicitly in the
track's notes and the single tightest estimate is used, never a blend of a
good and a bad one.

Method (a) or (b) is why a single well-instrumented node can range a shot that
no amount of acoustic processing on a 30 cm array alone can: a bare
muzzle-blast bearing carries no range information whatsoever -- amplitude
depends on weapon, calibre, barrel orientation and terrain, so an
amplitude-derived range is a guess dressed as a measurement, and we refuse to
emit one.

Accuracy of (a) is limited by AIR TEMPERATURE, not by electronics. The speed
of sound moves ~0.6 m/s per degree C. Assuming 20 C when it is actually 35 C
is a 2.6% range error -- 9 m at 350 m. Timestamp jitter of 5 ms contributes
1.7 m. So the node feeds its measured air temperature into c, and the
residual temperature uncertainty dominates the error budget. (ESTIMATE:
+/-3 C residual -> +/-0.5% -> +/-1.8 m at 350 m.)

Accuracy of (b) degrades sharply near Mach 1 (see TRANSONIC_MACH_FLOOR in
parallax/ballistics.py) and its miss-distance term is inherently the weakest
of its three outputs (a quarter-power relationship) -- both are surfaced in
the per-node ballistic solve's own notes, not hidden by the fusion layer.

------------------------------------------------------------------------
4. CONFLICTING BEARINGS
------------------------------------------------------------------------
Urban multipath can invert an apparent bearing: a hard facade reflects the
blast and the array bears on the reflection. Three defences, in order:

    (i)   The node self-reports it. Competing GCC-PHAT peaks of similar
          height raise FLAG_MULTIPATH_SUSPECT and inflate the bearing sigma.
    (ii)  Weighted least squares. Every bearing enters triangulation weighted
          by 1/sigma^2, so a self-declared loose bearing cannot drag the fix.
    (iii) Robust outlier rejection. With >=3 bearings we drop the single
          worst-residual bearing and refit; if that collapses the residual,
          the dropped bearing was the reflection. With exactly 2 conflicting
          bearings there is no majority and no way to tell which is lying, so
          we DEGRADE TO BEARING-ONLY on the higher-confidence node and say so
          in the track notes. Reporting a confident wrong position is worse
          than reporting an honest ray.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .ballistics import (
    BallisticObservables,
    DEFAULT_BULLET_LENGTH_M,
    MAX_CRACK_THUMP_RANGE_M,
    solve_crack_thump,
)
from .contact import (
    ContactReport,
    FusedTrack,
    Modality,
    ThreatClass,
    FLAG_MULTIPATH_SUSPECT,
)
from .geometry import (
    LocalFrame,
    bearing_between,
    cep50_from_cov,
    error_ellipse,
    triangulate,
    wrap_deg,
)

NS = 1e-9


def speed_of_sound(temp_c: float = 20.0) -> float:
    """c(T) = 331.3 * sqrt(1 + T/273.15). The dominant term in dt-based range."""
    return 331.3 * math.sqrt(1.0 + temp_c / 273.15)


@dataclass
class NodeState:
    node_id: int
    lat: float
    lon: float
    alt_m: float = 0.0
    enu: np.ndarray = field(default_factory=lambda: np.zeros(2))
    temp_c: float = 20.0
    online: bool = True


@dataclass
class FusionConfig:
    """Mission-profile-tunable fusion parameters. See profiles.py."""

    max_flash_acoustic_range_m: float = 1200.0
    clock_error_s: float = 0.010  # mesh sync bound; see module docstring
    onset_jitter_s: float = 0.005  # acoustic onset detection jitter (ESTIMATE)
    temp_uncertainty_c: float = 3.0
    bearing_gate_sigma: float = 3.0  # bearing must agree within N sigma
    min_confidence_to_alert: float = 0.55
    max_crossing_cep_m: float = 250.0  # beyond this the "fix" is not a fix
    min_crossing_angle_deg: float = 15.0
    mesh_relevance_m: float = 3000.0
    bullet_length_m: float = DEFAULT_BULLET_LENGTH_M  # for the ballistic solver
    range_disagreement_sigma: float = 3.0  # independent range estimates must
        # agree within this many combined sigma to be fused rather than flagged
    modality_weights: dict = field(
        default_factory=lambda: {
            Modality.OPTICAL_IR: 1.0,
            Modality.ACOUSTIC: 0.85,
            Modality.SHOCKWAVE: 0.85,  # NOT hardcoded to imply a gunshot by
                # itself -- it is one physics-supported acoustic modality, and
                # what actually earns confidence is temporal/spatial agreement
                # with the blast and other nodes (see _score's corroboration
                # and _range_from_ballistic_crack_thump's cross-validation).
            Modality.RF_PASSIVE: 0.6,
            Modality.SEISMIC: 0.35,  # confirmation only, never a primary fix
        }
    )


class FusionEngine:
    """Ingest contact reports, emit fused tracks."""

    def __init__(self, nodes: list[NodeState], frame: LocalFrame,
                 config: FusionConfig | None = None):
        self.frame = frame
        self.config = config or FusionConfig()
        self.nodes = {}
        for node in nodes:
            node.enu = frame.to_enu(node.lat, node.lon)
            self.nodes[node.node_id] = node
        self._next_track_id = 1

    # -- public ------------------------------------------------------------
    def process(self, reports: list[ContactReport]) -> list[FusedTrack]:
        """Batch fusion over a set of reports. Returns tracks, newest first."""
        reports = sorted(reports, key=lambda r: r.t_event_ns)
        clusters = self._associate(reports)
        tracks = [self._build_track(c) for c in clusters]
        return sorted(tracks, key=lambda t: t.t_event_ns, reverse=True)

    # -- 2. association ----------------------------------------------------
    def _max_lag_s(self, a: ContactReport, b: ContactReport) -> float:
        """Physically derived association window for a pair of reports."""
        cfg = self.config
        same_node = a.node_id == b.node_id
        optical = {a.modality, b.modality} == {Modality.OPTICAL_IR, Modality.ACOUSTIC}
        shock_thump = {a.modality, b.modality} == {Modality.SHOCKWAVE, Modality.ACOUSTIC}

        if same_node and optical:
            # Flash-to-acoustic: bounded by the max range we will consider.
            c = speed_of_sound(self.nodes[a.node_id].temp_c)
            return cfg.max_flash_acoustic_range_m / c + cfg.clock_error_s

        if same_node and shock_thump:
            # Crack-to-blast: bounded by the crack-thump method's own reach,
            # not the (much larger) flash/acoustic envelope -- a shockwave
            # this node can even detect implies the shot is comfortably
            # inside MAX_CRACK_THUMP_RANGE_M (see parallax/ballistics.py).
            c = speed_of_sound(self.nodes[a.node_id].temp_c)
            return MAX_CRACK_THUMP_RANGE_M / c + cfg.clock_error_s

        if same_node:
            # Same node, any other modality pairing (incl. same-modality
            # re-detects on one blast's onset+tail): both are effectively
            # instantaneous at node scale, so a short fixed window is
            # appropriate here. Only the optical<->acoustic pair above has
            # its own genuine propagation delay to account for.
            return 0.150 + cfg.clock_error_s

        # Different nodes: derived from THEIR baseline, not a global constant.
        node_a, node_b = self.nodes[a.node_id], self.nodes[b.node_id]
        baseline = float(np.linalg.norm(node_a.enu - node_b.enu))
        c = speed_of_sound(0.5 * (node_a.temp_c + node_b.temp_c))
        lag = baseline / c + cfg.clock_error_s
        if Modality.OPTICAL_IR in (a.modality, b.modality):
            # One side is optical (instantaneous), so the acoustic side can
            # lag by its own full propagation time on top of the baseline.
            lag += cfg.max_flash_acoustic_range_m / c
        return lag

    def _compatible(self, a: ContactReport, b: ContactReport) -> bool:
        """Temporal gate AND geometric plausibility. Both must pass."""
        cfg = self.config
        dt = abs(a.t_event_ns - b.t_event_ns) * NS
        if dt > self._max_lag_s(a, b):
            return False

        # A drone and a gunshot are not the same event even if simultaneous.
        if (
            a.threat_class != b.threat_class
            and ThreatClass.UNKNOWN not in (a.threat_class, b.threat_class)
            and ThreatClass.NUISANCE not in (a.threat_class, b.threat_class)
        ):
            return False

        if a.node_id == b.node_id:
            if {a.modality, b.modality} == {Modality.SHOCKWAVE, Modality.ACOUSTIC}:
                # The crack and the blast are EXPECTED to arrive from
                # different bearings -- that split is the Mach-angle signal
                # the ballistic solver reads speed off of (see
                # parallax/ballistics.py), not a disagreement to gate on. The
                # timing window above already does the gating for this pair;
                # requiring near-equal bearings here would reject every
                # genuine supersonic shot.
                return True

            # Same node, same OR different modality: still require bearing
            # agreement. Two genuinely distinct events at one node (a rapid
            # double-tap, or two shooters near the same node moments apart)
            # both pass the timing gate above; without a bearing check they
            # would silently merge into one track and one contact would be
            # dropped from the count. The re-detect case this gate is meant
            # to allow (one blast, two detector triggers on its own onset and
            # tail) is bearing-consistent by construction, so this costs
            # nothing there.
            sigma = math.hypot(a.azimuth_sigma_deg, b.azimuth_sigma_deg)
            return abs(wrap_deg(a.azimuth_deg - b.azimuth_deg)) <= cfg.bearing_gate_sigma * max(sigma, 1.0)

        # Different nodes: the rays must cross somewhere physically sensible.
        return self._rays_plausibly_cross(a, b)

    def _rays_plausibly_cross(self, a: ContactReport, b: ContactReport) -> bool:
        node_a, node_b = self.nodes[a.node_id], self.nodes[b.node_id]
        try:
            point, _ = triangulate(
                np.vstack([node_a.enu, node_b.enu]),
                np.array([a.azimuth_deg, b.azimuth_deg]),
                np.array([a.azimuth_sigma_deg, b.azimuth_sigma_deg]),
            )
        except np.linalg.LinAlgError:
            # Near-parallel bearings have no crossing point, but that is a
            # statement about geometry, not about whether this is the same
            # event. Two closely-spaced nodes bearing consistently on a distant
            # shot SHOULD associate -- they simply cannot produce a fix. Fall
            # back to bearing agreement so the track forms and then honestly
            # reports itself as bearing-only.
            sigma = math.hypot(a.azimuth_sigma_deg, b.azimuth_sigma_deg)
            return abs(wrap_deg(a.azimuth_deg - b.azimuth_deg)) <= (
                self.config.bearing_gate_sigma * max(sigma, 1.0)
            )

        for node, report in ((node_a, a), (node_b, b)):
            delta = point - node.enu
            distance = float(np.linalg.norm(delta))
            if distance > self.config.mesh_relevance_m:
                return False
            # Reject back-bearings: the crossing must lie in FRONT of the ray.
            bearing_to_point = math.degrees(math.atan2(delta[0], delta[1])) % 360.0
            if abs(wrap_deg(bearing_to_point - report.azimuth_deg)) > 90.0:
                return False
        return True

    def _associate(self, reports: list[ContactReport]) -> list[list[ContactReport]]:
        """Single-linkage clustering under the pairwise compatibility relation."""
        n = len(reports)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        for i in range(n):
            for j in range(i + 1, n):
                if self._compatible(reports[i], reports[j]):
                    union(i, j)

        clusters: dict[int, list[ContactReport]] = {}
        for i, report in enumerate(reports):
            clusters.setdefault(find(i), []).append(report)
        return list(clusters.values())

    # -- 3 + 4. fix and confidence ----------------------------------------
    def _build_track(self, cluster: list[ContactReport]) -> FusedTrack:
        cfg = self.config
        cluster = sorted(cluster, key=lambda r: r.t_event_ns)
        modalities = tuple(sorted({r.modality.name for r in cluster}))
        notes: list[str] = []

        track = FusedTrack(
            track_id=self._next_track_id,
            t_event_ns=cluster[0].t_event_ns,
            threat_class=self._vote_class(cluster),
            confidence=0.0,
            contributing_reports=list(cluster),
            modalities=modalities,
        )
        self._next_track_id += 1

        # -- three independent range sources, gathered before any are chosen --
        # method (a): flash/acoustic dt, single node
        flash_ranged = self._range_from_flash_acoustic(cluster, notes)
        # method (b): ballistic crack-thump, single node (needs SHOCKWAVE +
        # ACOUSTIC from the same node -- see parallax/ballistics.py)
        ballistic_ranged = self._range_from_ballistic_crack_thump(cluster, notes)
        # method (c): triangulation from >=2 bearings
        fixed = self._triangulate_cluster(cluster, notes)

        estimates: list[tuple[str, float, float]] = []
        if flash_ranged is not None:
            estimates.append(("flash_acoustic_dt", flash_ranged[0], flash_ranged[1]))
        if ballistic_ranged is not None:
            estimates.append(("ballistic_crack_thump", ballistic_ranged[0], ballistic_ranged[1]))

        # The crack bearing points at a spot on the bullet's FLIGHT PATH, not
        # at the shooter -- it must never be picked as the reported bearing.
        bearing_candidates = [r for r in cluster if r.modality != Modality.SHOCKWAVE]
        if bearing_candidates:
            # Primary key: modality-weighted classifier confidence. Two nodes
            # of the same modality routinely tie on this exactly (same sensor
            # type, similar confidence) -- e.g. two plain ACOUSTIC reports at
            # 0.85 each. Without a tiebreak, Python's max() silently keeps
            # whichever tied report happened to sort first, which can be the
            # FARTHER, less informative node: the reported "range" is measured
            # from the primary node, so a bad tiebreak makes an accurate
            # triangulated position look like a wildly wrong range even though
            # the position itself is fine. Break ties toward the tighter
            # (more informative) bearing.
            shockwave_nodes = {r.node_id for r in cluster if r.modality == Modality.SHOCKWAVE}
            primary = max(bearing_candidates, key=lambda r: (
                cfg.modality_weights.get(r.modality, 0.5) * r.class_confidence,
                -r.azimuth_sigma_deg,
                1 if r.node_id in shockwave_nodes else 0,  # ballistic-backed wins final ties
            ))
        else:
            # Every report in this cluster is a bare crack with no paired
            # blast (a physically odd case -- the blast that made it should
            # also register). Handle it rather than crash, and say so plainly.
            primary = cluster[0]
            notes.append(
                "no blast/optical bearing in this cluster - reporting a crack "
                "bearing, which is NOT the shooter's true direction"
            )
        track.primary_node_id = primary.node_id
        track.bearing_deg = primary.azimuth_deg
        track.bearing_sigma_deg = primary.azimuth_sigma_deg

        if fixed is not None:
            point, cov = fixed
            track.position_enu = tuple(point)
            track.position_latlon = self.frame.to_geodetic(point[0], point[1])
            track.cep50_m = cep50_from_cov(cov)
            track.ellipse = error_ellipse(cov, n_sigma=1.0)
            node = self.nodes[primary.node_id]
            tri_range = float(np.linalg.norm(point - node.enu))
            tri_sigma = max(track.cep50_m, 1.0)
            estimates.append(("triangulation", tri_range, tri_sigma))

            combined = self._combine_range_estimates(estimates, notes)
            track.range_m, track.range_sigma_m, track.range_method = combined
        elif estimates:
            combined = self._combine_range_estimates(estimates, notes)
            range_m, range_sigma_m, method = combined
            track.range_m, track.range_sigma_m = range_m, range_sigma_m
            track.range_method = method

            node = self.nodes[primary.node_id]
            direction = np.array([
                math.sin(math.radians(primary.azimuth_deg)),
                math.cos(math.radians(primary.azimuth_deg)),
            ])
            point = node.enu + range_m * direction
            track.position_enu = tuple(point)
            track.position_latlon = self.frame.to_geodetic(point[0], point[1])
            # Along-track error is the range sigma; cross-track is the bearing
            # arc. Orientation must follow whichever term actually won the
            # max() -- cross-track normally dominates at range (a few degrees
            # of bearing sigma swamps a few metres of timing/ballistic sigma),
            # so the ellipse's long axis is usually PERPENDICULAR to the
            # bearing, not along it. Hardcoding azimuth_deg as the orientation
            # would draw the uncertainty rotated 90 degrees from its true shape.
            cross = range_m * math.tan(math.radians(primary.azimuth_sigma_deg))
            along_track_deg = primary.azimuth_deg
            cross_track_deg = (primary.azimuth_deg + 90.0) % 360.0
            if cross >= range_sigma_m:
                track.ellipse = (cross, range_sigma_m, cross_track_deg)
            else:
                track.ellipse = (range_sigma_m, cross, along_track_deg)
            track.cep50_m = 1.1774 * math.sqrt(cross * range_sigma_m)
        else:
            track.range_method = "none"
            notes.append("BEARING ONLY - single node, no optical/ballistic pair, no crossing fix")

        track.confidence = self._score(cluster, track)
        track.notes = notes
        return track

    def _combine_range_estimates(
        self, estimates: list[tuple[str, float, float]], notes: list[str]
    ) -> tuple[float, float, str]:
        """Cross-validate independent range sources; fuse if they agree, flag if not.

        This is the point of carrying three possible range methods instead of
        picking one: don't silently choose a winner. If every pair of
        estimates agrees within ``range_disagreement_sigma`` combined sigma,
        fuse them by inverse-variance weighting -- the source with the
        tighter uncertainty earns more say, the same principle the bearing
        triangulation already uses. If any pair disagrees, do NOT average an
        outlier into the answer: keep the single tightest (lowest-sigma)
        estimate and record exactly which sources disagreed, so the
        discrepancy is visible rather than smoothed away.
        """
        assert estimates, "_combine_range_estimates called with no estimates"
        if len(estimates) == 1:
            name, r, s = estimates[0]
            return r, s, name

        summary = ", ".join(f"{n}={r:.0f}m(+/-{s:.0f})" for n, r, s in estimates)
        agree = all(
            abs(estimates[i][1] - estimates[j][1])
            <= self.config.range_disagreement_sigma
            * math.hypot(estimates[i][2], estimates[j][2])
            for i in range(len(estimates))
            for j in range(i + 1, len(estimates))
        )

        if agree:
            weights = [1.0 / max(s, 1e-6) ** 2 for _, _, s in estimates]
            total_w = sum(weights)
            r_fused = sum(w * r for w, (_, r, _) in zip(weights, estimates)) / total_w
            s_fused = math.sqrt(1.0 / total_w)
            notes.append(f"range sources agree: {summary} -> fused {r_fused:.0f} +/- {s_fused:.0f} m")
            return r_fused, s_fused, "+".join(n for n, _, _ in estimates)

        best = min(estimates, key=lambda e: e[2])
        notes.append(
            f"RANGE SOURCES DISAGREE: {summary} -> using tightest ({best[0]}), "
            "treat position as suspect"
        )
        return best[1], best[2], best[0]

    def _range_from_ballistic_crack_thump(self, cluster, notes) -> tuple[float, float] | None:
        """Crack-thump range from any node that reported BOTH a SHOCKWAVE
        (crack) and an ACOUSTIC (blast) arrival. See parallax/ballistics.py
        for the physics; this just packages a node's pair of reports into
        the observables the solver needs and keeps the tightest result.
        """
        by_node: dict[int, dict] = {}
        for report in cluster:
            by_node.setdefault(report.node_id, {})[report.modality] = report

        best = None
        for node_id, by_modality in by_node.items():
            shock = by_modality.get(Modality.SHOCKWAVE)
            blast = by_modality.get(Modality.ACOUSTIC)
            if shock is None or blast is None:
                continue

            dt = (blast.t_event_ns - shock.t_event_ns) * NS
            if dt <= 0:
                continue  # crack must arrive before the blast; non-physical otherwise

            obs = BallisticObservables(
                blast_bearing_deg=blast.azimuth_deg,
                bearing_split_deg=abs(wrap_deg(blast.azimuth_deg - shock.azimuth_deg)),
                dt_s=dt,
                nwave_duration_s=shock.nwave_duration_s,
                blast_bearing_sigma_deg=blast.azimuth_sigma_deg,
                bearing_split_sigma_deg=math.hypot(blast.azimuth_sigma_deg, shock.azimuth_sigma_deg),
                dt_sigma_s=self.config.onset_jitter_s * math.sqrt(2),
            )
            temp = self.nodes[node_id].temp_c
            sol = solve_crack_thump(
                obs, bullet_length_m=self.config.bullet_length_m,
                c=speed_of_sound(temp),
            )
            if sol.range_m is None:
                continue

            notes.append(
                f"node {node_id}: ballistic crack-thump -> {sol.range_m:.0f} m "
                f"(Mach {sol.mach:.2f}, miss {sol.miss_distance_m:.0f} m, "
                f"{sol.distance_accuracy_pct:.0f}% accuracy)"
            )
            sigma = sol.range_sigma_m if sol.range_sigma_m is not None else max(0.1 * sol.range_m, 5.0)
            if best is None or sigma < best[1]:
                best = (sol.range_m, sigma)
        return best

    def _range_from_flash_acoustic(self, cluster, notes) -> tuple[float, float] | None:
        by_node: dict[int, dict] = {}
        for report in cluster:
            by_node.setdefault(report.node_id, {})[report.modality] = report

        best = None
        for node_id, by_modality in by_node.items():
            optical = by_modality.get(Modality.OPTICAL_IR)
            acoustic = by_modality.get(Modality.ACOUSTIC)
            if optical is None or acoustic is None:
                continue
            dt = (acoustic.t_event_ns - optical.t_event_ns) * NS
            if dt <= 0:
                notes.append(f"node {node_id}: non-physical dt {dt*1e3:.1f} ms, rejected")
                continue

            temp = self.nodes[node_id].temp_c
            c = speed_of_sound(temp)
            rng = c * dt

            # Error budget, both terms, honestly propagated.
            sigma_time = c * math.hypot(self.config.onset_jitter_s, 1e-4)
            dc_dt = 0.5 * 331.3 / math.sqrt(1 + temp / 273.15) / 273.15
            sigma_temp = dt * dc_dt * self.config.temp_uncertainty_c
            sigma = math.hypot(sigma_time, sigma_temp)

            notes.append(
                f"node {node_id}: flash->acoustic dt {dt*1e3:.0f} ms @ c={c:.1f} m/s "
                f"-> {rng:.0f} m (sigma {sigma:.1f} m: {sigma_time:.1f} timing / "
                f"{sigma_temp:.1f} thermal)"
            )
            if best is None or sigma < best[1]:
                best = (rng, sigma)
        return best

    def _triangulate_cluster(self, cluster, notes):
        cfg = self.config
        bearings = [
            r for r in cluster
            if r.modality in (Modality.OPTICAL_IR, Modality.ACOUSTIC)
        ]
        # One bearing per node per modality; prefer optical (tighter).
        picked: dict[int, ContactReport] = {}
        for report in bearings:
            existing = picked.get(report.node_id)
            if existing is None or report.azimuth_sigma_deg < existing.azimuth_sigma_deg:
                picked[report.node_id] = report
        chosen = list(picked.values())
        if len(chosen) < 2:
            return None

        origins = np.vstack([self.nodes[r.node_id].enu for r in chosen])
        azimuths = np.array([r.azimuth_deg for r in chosen])
        sigmas = np.array([
            r.azimuth_sigma_deg * (2.0 if r.flags & FLAG_MULTIPATH_SUSPECT else 1.0)
            for r in chosen
        ])

        # Crossing angle governs whether a fix exists at all.
        spread = max(
            abs(wrap_deg(a - b)) for i, a in enumerate(azimuths) for b in azimuths[i + 1:]
        ) if len(azimuths) > 1 else 0.0
        if spread < cfg.min_crossing_angle_deg:
            notes.append(
                f"crossing angle {spread:.1f} deg < {cfg.min_crossing_angle_deg:.0f} deg "
                "- geometry too shallow for a fix"
            )
            return None

        try:
            point, cov = triangulate(origins, azimuths, sigmas)
        except np.linalg.LinAlgError as exc:
            notes.append(str(exc))
            return None

        # (iii) robust outlier rejection, only when a majority exists.
        if len(chosen) >= 3:
            residuals = [
                abs(wrap_deg(
                    bearing_between(self.nodes[r.node_id].enu, point) - r.azimuth_deg
                ))
                for r in chosen
            ]
            worst = int(np.argmax(residuals))
            if residuals[worst] > cfg.bearing_gate_sigma * max(sigmas[worst], 1.0):
                keep = [i for i in range(len(chosen)) if i != worst]
                notes.append(
                    f"rejected node {chosen[worst].node_id} bearing "
                    f"(residual {residuals[worst]:.1f} deg) - probable reflection"
                )
                try:
                    point, cov = triangulate(origins[keep], azimuths[keep], sigmas[keep])
                except np.linalg.LinAlgError:
                    return None

        cep = cep50_from_cov(cov)
        if cep > cfg.max_crossing_cep_m:
            notes.append(
                f"triangulated CEP50 {cep:.0f} m exceeds {cfg.max_crossing_cep_m:.0f} m "
                "- reporting bearing only"
            )
            return None
        return point, cov

    def _vote_class(self, cluster) -> ThreatClass:
        scores: dict[ThreatClass, float] = {}
        for report in cluster:
            weight = self.config.modality_weights.get(report.modality, 0.5)
            scores[report.threat_class] = (
                scores.get(report.threat_class, 0.0) + weight * report.class_confidence
            )
        return max(scores.items(), key=lambda kv: kv[1])[0]

    def _score(self, cluster, track: FusedTrack) -> float:
        """Confidence in [0, 1]. Every term is named and bounded.

        Deliberately NOT a learned score: with no labelled multi-node fusion
        corpus, a learned combiner would be fitted to the simulator and would
        mean nothing in the field. An explicit weighted product is honest
        about being a heuristic and is defensible line by line.
        """
        cfg = self.config

        # (1) Best single-report classifier confidence, modality-weighted.
        detection = max(
            cfg.modality_weights.get(r.modality, 0.5) * r.class_confidence
            for r in cluster
        )

        # (2) Independent modalities corroborating. Two physically different
        #     sensors agreeing is far stronger evidence than two of the same.
        n_modalities = len({r.modality for r in cluster})
        corroboration = 1.0 - 0.45 * (0.5 ** (n_modalities - 1))

        # (3) Independent nodes agreeing.
        n_nodes = len({r.node_id for r in cluster})
        spatial = 1.0 - 0.35 * (0.6 ** (n_nodes - 1))

        # (4) Geometry quality: a fix with a tight CEP earns more than a ray.
        if track.cep50_m is not None:
            geometry = float(np.clip(1.0 - track.cep50_m / cfg.max_crossing_cep_m, 0.15, 1.0))
        elif track.range_method.startswith("flash_acoustic"):
            geometry = 0.8
        else:
            geometry = 0.45

        # (5) Penalty for self-declared multipath.
        multipath = 0.75 if any(r.flags & FLAG_MULTIPATH_SUSPECT for r in cluster) else 1.0

        product = detection * corroboration * spatial * geometry * multipath
        # np.clip(nan, 0, 1) returns nan, not a bounded value -- a malformed
        # upstream class_confidence (NaN or out-of-[0,1]) would otherwise
        # propagate into track.confidence and silently fail every >= alert
        # comparison downstream (NaN comparisons are always False) instead of
        # being caught here, where the malformed input actually originates.
        if not math.isfinite(product):
            return 0.0
        return float(np.clip(product, 0.0, 1.0))
