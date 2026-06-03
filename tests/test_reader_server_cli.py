from __future__ import annotations

from click.testing import CliRunner

from paper_search.cli import main


def test_serve_reader_site_command_is_registered():
    runner = CliRunner()
    result = runner.invoke(main, ["serve-reader-site", "--help"])

    assert result.exit_code == 0
    assert "--site-dir" in result.output
    assert "--host" in result.output
    assert "--port" in result.output
