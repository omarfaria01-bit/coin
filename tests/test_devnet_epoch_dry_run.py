"""tests.tools.devnet_epoch_dry_run: test CLI dry-run guard rails (#140)."""

from __future__ import annotations

from tools.devnet_epoch_dry_run import main


def test_dry_run_refuses_non_devnet_url(capsys) -> None:
    code = main(
        [
            "--mint",
            "So11111111111111111111111111111111111111112",
            "--rpc",
            "https://api.mainnet-beta.solana.com",
            "--t0",
            "1000",
            "--t1",
            "86400",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "Refusing non-devnet cluster URL" in err
