"""Captured settings preserve print evidence without inventing restorable presets."""

from pathlib import Path

import pytest

from printstash_core.gcode.settings import (
    MAX_VALUE_LENGTH,
    WINDOW_BYTES,
    CapturedSettings,
    capture_settings,
    parse_settings,
)


class TestParseSettings:
    @pytest.mark.parametrize(
        "key,group,value",
        [
            ("nozzle_diameter", "printer", "0.4,0.6"),
            ("filament_flow_ratio", "filament", "0.98;1.02"),
            ("print_settings_id", "process", "0.20mm Strong"),
            ("enable_pressure_advance", "filament", "0"),
        ],
    )
    def test_preserves_observed_values(self, key, group, value):
        captured = parse_settings(f"; {key} = {value}\n")

        assert getattr(captured, group) == {key: value}

    def test_retains_quoted_multifilament_names(self):
        captured = parse_settings('; filament_settings_id = "PLA; matte";"PETG"\n')

        assert captured.filament == {"filament_settings_id": '"PLA; matte";"PETG"'}

    @pytest.mark.parametrize(
        "line",
        [
            "; printhost_apikey = private",
            "; machine_start_gcode = RUN_SECRET_SCRIPT",
            "; post_process = secret command",
            "; unrecognized_setting = arbitrary",
            "G1 X1 ; layer_height = 0.2",
            "; layer_height = ",
            "; filament_settings_id = bad\x00value",
            "; filament_settings_id = " + "x" * (MAX_VALUE_LENGTH + 1),
        ],
    )
    def test_ignores_unusable_entries(self, line):
        assert parse_settings(line) == CapturedSettings()

    def test_keeps_the_last_occurrence(self):
        assert parse_settings("; layer_height = 0.2\n; layer_height = 0.3").process == {
            "layer_height": "0.3"
        }


class TestCaptureSettings:
    @pytest.mark.parametrize(
        "filename,group,key,value",
        [
            (
                "real_orca_ender3_benchy.gcode",
                "filament",
                "filament_flow_ratio",
                "0.98",
            ),
            ("bambu_studio_sample.gcode", "filament", "filament_type", "PLA;PLA"),
            ("bgcode/prusaslicer.bgcode", "process", "layer_height", "0.2"),
        ],
    )
    def test_reads_supported_slicer_exports(self, filename, group, key, value):
        path = Path(__file__).resolve().parents[4] / "tests/fixtures" / filename

        captured = capture_settings(path)

        assert getattr(captured, group)[key] == value

    def test_reads_the_footer_of_a_large_print(self, tmp_path):
        path = tmp_path / "large.gcode"
        path.write_bytes(
            b"; nozzle_diameter = 0.4\n"
            + b"G1 X1\n" * WINDOW_BYTES
            + b"; layer_height = 0.2\n"
        )

        captured = capture_settings(path)

        assert captured.process == {"layer_height": "0.2"}

    def test_discards_a_cut_header_value(self, tmp_path):
        path = tmp_path / "cut.gcode"
        prefix = b"; filament_settings_id = "
        path.write_bytes(
            b"\n" * (WINDOW_BYTES - len(prefix) - 3)
            + prefix
            + b"Long Name\n"
            + b"G1 X1\n" * WINDOW_BYTES
        )

        assert capture_settings(path).filament == {}

    def test_preserves_a_value_crossing_adjacent_windows(self, tmp_path):
        path = tmp_path / "adjacent.gcode"
        path.write_bytes(b"\n" * (WINDOW_BYTES - 10) + b"; layer_height = 0.2\n")

        assert capture_settings(path).process == {"layer_height": "0.2"}

    def test_reports_an_unreadable_source(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            capture_settings(tmp_path / "absent.gcode")
