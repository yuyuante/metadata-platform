from emip.cli import _build_parser
from emip.profiling import Profiler


def test_profile_option_is_optional() -> None:
    parser = _build_parser()

    assert parser.parse_args(["scan", "samples"]).profile is False
    assert parser.parse_args(["scan", "samples", "--profile"]).profile is True


def test_performance_report_contains_stage_and_hotspot_sections() -> None:
    profiler = Profiler()
    profiler.record("XML parsing", 2.0, 3)
    profiler.count("MetadataObject", 3)
    profiler.count("Relation", 2)

    report = profiler.render()

    assert "Performance Summary" in report
    assert "XML parsing" in report
    assert "Objects/sec:" in report
    assert "Relations/sec:" in report
    assert "Top 5 Slowest Stages" in report


def test_profile_start_stop_and_json_report(tmp_path) -> None:
    profiler = Profiler()
    profiler.start("XML parsing")
    profiler.stop("XML parsing", objects=2)
    profiler.repository_event("metadata_insert", 3)
    profiler.repository_event("skipped", 4)
    output = tmp_path / "performance-report.txt"

    profiler.write(output)

    report = output.with_suffix(".json").read_text(encoding="utf-8")
    assert '"schema_version": 1' in report
    assert '"metadata_insert_count": 3' in report
    assert '"skipped_count": 4' in report
