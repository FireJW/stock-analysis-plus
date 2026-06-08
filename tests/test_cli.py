from stock_analysis_plus.cli import main


def test_list_command(capsys):
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "month-end-shortlist" in output
    assert "macro-health-overlay" in output
    assert "longbridge" in output


def test_list_marks_month_end_shortlist_partial_when_compiled_artifacts_are_omitted(capsys):
    assert main(["list"]) == 0
    output = capsys.readouterr().out

    month_end_line = next(line for line in output.splitlines() if line.startswith("month-end-shortlist"))

    assert "partial" in month_end_line


def test_readme_does_not_advertise_omitted_compiled_entrypoint():
    readme = (main.__globals__["ROOT"] / "README.md").read_text(encoding="utf-8")

    assert "month_end_shortlist.py --help" not in readme
