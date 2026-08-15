"""The contact report: the only thing that ever crosses the mesh.

A node never transmits audio. It transmits a fixed 42-byte binary record
describing one detection. The bandwidth argument, quantified:

    raw audio  : 48 kHz x 6 ch x 24 bit         = 6.912 Mbit/s per node
    contact rpt: 42 bytes                       = 336 bit per event

One second of raw audio costs ~20,600x more link budget than one contact
report. That ratio, not any claim about clever compression, is why edge
classification is non-negotiable in a radio-constrained mesh.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, asdict, field
from enum import IntEnum

# struct format for the on-wire record. '<' = little endian, no padding.
#   node_id u16 | seq u16 | t_event_ns u64 | modality u8 | threat u8
#   class_conf u8 | az_centideg u16 | az_sigma_decideg u8
#   el_centideg i16 | el_sigma_decideg u8 | range_m u16 | range_sigma_m u16
#   peak_spl_db u8 | snr_db u8 | lat_e7 i32 | lon_e7 i32 | alt_m i16
#   heading_deg u16 | flags u8 | crc16 u16
_WIRE_FMT = "<HHQBBBHBhBHHBBiihHBH"
WIRE_SIZE = struct.calcsize(_WIRE_FMT)  # 42 bytes


class Modality(IntEnum):
    ACOUSTIC = 0
    OPTICAL_IR = 1
    RF_PASSIVE = 2
    SEISMIC = 3


class ThreatClass(IntEnum):
    UNKNOWN = 0
    GUNSHOT = 1
    VEHICLE = 2
    DRONE = 3
    PERSONNEL = 4
    NUISANCE = 5  # firecracker, door slam, hammer, thunder


# Bit flags. Bit 0 is reserved (formerly FLAG_RANGE_IS_MEASURED): range is
# never carried on an individual ContactReport in this design -- it only
# emerges at the fusion/track level from flash/acoustic dt or triangulation
# (see FusedTrack.range_method) -- so a per-report "is this range measured"
# flag had nothing to describe and has been removed rather than left dead.
FLAG_ELEVATION_VALID = 1 << 1  # array is non-planar, elevation is observable
FLAG_GPS_LOCKED = 1 << 2  # PPS discipline is good, timestamp is sub-microsecond
FLAG_SATURATED = 1 << 3  # ADC clipped; bearing is suspect
FLAG_MULTIPATH_SUSPECT = 1 << 4  # multiple correlation peaks of similar height


@dataclass
class ContactReport:
    """One detection, from one node, on one modality."""

    node_id: int
    seq: int
    t_event_ns: int  # UTC nanoseconds of the *event onset* at the node
    modality: Modality
    threat_class: ThreatClass
    class_confidence: float  # 0..1
    azimuth_deg: float  # compass, 0 = North
    azimuth_sigma_deg: float
    elevation_deg: float = 0.0
    elevation_sigma_deg: float = 0.0
    range_m: float = 0.0  # 0 = not observable from this node alone
    range_sigma_m: float = 0.0
    peak_spl_db: float = 0.0
    snr_db: float = 0.0
    node_lat: float = 0.0
    node_lon: float = 0.0
    node_alt_m: float = 0.0
    node_heading_deg: float = 0.0
    flags: int = 0

    def to_bytes(self) -> bytes:
        """Serialise to the 42-byte wire record (with CRC-16/CCITT)."""
        body = struct.pack(
            _WIRE_FMT[:-1],
            self.node_id & 0xFFFF,
            self.seq & 0xFFFF,
            int(self.t_event_ns),
            int(self.modality),
            int(self.threat_class),
            int(round(_clamp(self.class_confidence, 0, 1) * 255)),
            int(round(self.azimuth_deg % 360.0 * 100)) % 36000,
            int(round(_clamp(self.azimuth_sigma_deg, 0, 25.5) * 10)),
            int(round(_clamp(self.elevation_deg, -90, 90) * 100)),
            int(round(_clamp(self.elevation_sigma_deg, 0, 25.5) * 10)),
            int(round(_clamp(self.range_m, 0, 65535))),
            int(round(_clamp(self.range_sigma_m, 0, 65535))),
            int(round(_clamp(self.peak_spl_db, 0, 255))),
            int(round(_clamp(self.snr_db, 0, 255))),
            int(round(self.node_lat * 1e7)),
            int(round(self.node_lon * 1e7)),
            int(round(_clamp(self.node_alt_m, -32768, 32767))),
            int(round(self.node_heading_deg % 360.0 * 100)) % 36000,
            self.flags & 0xFF,
        )
        return body + struct.pack("<H", crc16_ccitt(body))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["modality"] = self.modality.name
        d["threat_class"] = self.threat_class.name
        d["wire_bytes"] = WIRE_SIZE
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class FusedTrack:
    """The fusion layer's output: one physical event, however many reports."""

    track_id: int
    t_event_ns: int
    threat_class: ThreatClass
    confidence: float
    contributing_reports: list = field(default_factory=list)
    # Position, when a fix exists.
    position_enu: tuple | None = None
    position_latlon: tuple | None = None
    cep50_m: float | None = None
    ellipse: tuple | None = None  # (semi_major_m, semi_minor_m, orientation_deg)
    # Bearing-only fallback, from the highest-confidence contributing node.
    primary_node_id: int | None = None
    bearing_deg: float | None = None
    bearing_sigma_deg: float | None = None
    range_m: float | None = None
    range_sigma_m: float | None = None
    range_method: str = "none"  # flash_acoustic_dt | triangulation | none
    modalities: tuple = ()
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "t_event_ns": self.t_event_ns,
            "threat_class": self.threat_class.name,
            "confidence": round(self.confidence, 3),
            "modalities": list(self.modalities),
            "n_reports": len(self.contributing_reports),
            "contributing_nodes": sorted(
                {r.node_id for r in self.contributing_reports}
            ),
            "position_enu": _round_opt(self.position_enu, 1),
            "position_latlon": _round_opt(self.position_latlon, 6),
            "cep50_m": _round_opt(self.cep50_m, 1),
            "ellipse": _round_opt(self.ellipse, 1),
            "primary_node_id": self.primary_node_id,
            "bearing_deg": _round_opt(self.bearing_deg, 2),
            "bearing_sigma_deg": _round_opt(self.bearing_sigma_deg, 2),
            "range_m": _round_opt(self.range_m, 1),
            "range_sigma_m": _round_opt(self.range_sigma_m, 1),
            "range_method": self.range_method,
            "notes": self.notes,
        }


def crc16_ccitt(data: bytes, seed: int = 0xFFFF) -> int:
    crc = seed
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_opt(value, digits):
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        return [round(float(v), digits) for v in value]
    return round(float(value), digits)
