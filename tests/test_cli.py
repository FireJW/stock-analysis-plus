from stock_analysis_plus.cli import main


def test_list_command(capsys):
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "month-end-shortlist" in output
    assert "macro-health-overlay" in output
    assert "longbridge" in output
