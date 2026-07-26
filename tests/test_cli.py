from speleoconvert.cli import main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "speleoconvert" in capsys.readouterr().out


def test_no_args_is_usage_error(capsys):
    assert main([]) == 2
