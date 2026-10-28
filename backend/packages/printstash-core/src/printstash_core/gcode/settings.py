"""Bounded, read-only evidence of slicer settings written into a print file.

Values retain the slicer's serialization, including per-filament lists. This is
not a native preset: inherited defaults, unused presets and project structure
cannot be reconstructed from these comments. Only named settings are exposed;
scripts, custom G-code, credentials and arbitrary comments are excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .bgcode import is_bgcode, read_metadata_text

WINDOW_BYTES = 256 * 1024
MAX_VALUE_LENGTH = 4096

PRINTER_KEYS = frozenset(
    """
printer_settings_id printer_model printer_variant nozzle_diameter printer_technology
gcode_flavor printable_area printable_height bed_shape max_print_height
machine_max_acceleration_x machine_max_acceleration_y machine_max_acceleration_z
machine_max_acceleration_e machine_max_acceleration_extruding
machine_max_speed_x machine_max_speed_y machine_max_speed_z machine_max_speed_e
machine_max_jerk_x machine_max_jerk_y machine_max_jerk_z machine_max_jerk_e
retraction_length retraction_speed deretraction_speed retract_lift retract_before_travel
retract_when_changing_layer use_relative_e_distances use_firmware_retraction
""".split()
)
FILAMENT_KEYS = frozenset(
    """
filament_settings_id filament_type filament_vendor filament_brand filament_colour
filament_diameter filament_density filament_cost filament_flow_ratio extrusion_multiplier
filament_max_volumetric_speed enable_pressure_advance pressure_advance
nozzle_temperature nozzle_temperature_initial_layer temperature first_layer_temperature
bed_temperature bed_temperature_initial_layer first_layer_bed_temperature
hot_plate_temp hot_plate_temp_initial_layer textured_plate_temp textured_plate_temp_initial_layer
cool_plate_temp cool_plate_temp_initial_layer eng_plate_temp eng_plate_temp_initial_layer
chamber_temperature fan_min_speed fan_max_speed min_fan_speed max_fan_speed
slow_down_layer_time slow_down_min_speed close_fan_the_first_x_layers full_fan_speed_layer
overhang_fan_speed additional_cooling_fan_speed filament_retraction_length
filament_retraction_speed filament_deretraction_speed filament_retract_lift
""".split()
)
PROCESS_KEYS = frozenset(
    """
print_settings_id layer_height initial_layer_print_height first_layer_height
wall_loops perimeters top_shell_layers bottom_shell_layers top_solid_layers bottom_solid_layers
sparse_infill_density fill_density sparse_infill_pattern fill_pattern
outer_wall_speed inner_wall_speed sparse_infill_speed internal_solid_infill_speed
top_surface_speed initial_layer_speed initial_layer_infill_speed travel_speed
normal_acceleration outer_wall_acceleration inner_wall_acceleration travel_acceleration
enable_support support_material support_type support_style support_threshold_angle
support_top_z_distance support_bottom_z_distance support_object_xy_distance
support_interface_top_layers support_interface_bottom_layers
brim_type brim_width skirt_loops skirts skirt_distance seam_position
ironing_type wall_generator line_width outer_wall_line_width inner_wall_line_width
sparse_infill_line_width top_surface_line_width print_sequence spiral_mode
""".split()
)
_ENTRY = re.compile(r"^[ \t]*;[ \t]*([a-z][a-z0-9_]*)[ \t]*=[ \t]*(.*)$")


@dataclass(frozen=True)
class CapturedSettings:
    printer: dict[str, str] = field(default_factory=dict)
    filament: dict[str, str] = field(default_factory=dict)
    process: dict[str, str] = field(default_factory=dict)


def parse_settings(text: str) -> CapturedSettings:
    """Read supported comment keys without interpreting or executing values."""
    result = CapturedSettings()
    for line in text.splitlines():
        match = _ENTRY.fullmatch(line)
        if match is None:
            continue
        key, value = match.groups()
        value = value.strip()
        if (
            not value
            or len(value) > MAX_VALUE_LENGTH
            or any(ord(c) < 32 for c in value)
        ):
            continue
        if key in PRINTER_KEYS:
            result.printer[key] = value
        elif key in FILAMENT_KEYS:
            result.filament[key] = value
        elif key in PROCESS_KEYS:
            result.process[key] = value
    return result


def capture_settings(path: Path) -> CapturedSettings:
    """Read bounded header/footer windows, or bounded binary-container metadata.

    Discard cut lines at either window edge: a partial value must not look like an
    observed setting. Missing fields remain absent, never synthesized as defaults.
    """
    if is_bgcode(path):
        metadata = read_metadata_text(path)
        return CapturedSettings() if metadata is None else parse_settings(metadata)
    with path.open("rb") as stream:
        head = stream.read(WINDOW_BYTES)
        if len(head) < WINDOW_BYTES:
            return parse_settings(head.decode("utf-8", errors="replace"))
        head = head.rsplit(b"\n", 1)[0]
        stream.seek(0, 2)
        size = stream.tell()
        if size <= WINDOW_BYTES * 2:
            stream.seek(0)
            return parse_settings(
                stream.read(WINDOW_BYTES * 2).decode("utf-8", errors="replace")
            )
        stream.seek(size - WINDOW_BYTES)
        tail = stream.read(WINDOW_BYTES).split(b"\n", 1)
    footer = tail[1] if len(tail) == 2 else b""
    return parse_settings((head + b"\n" + footer).decode("utf-8", errors="replace"))
