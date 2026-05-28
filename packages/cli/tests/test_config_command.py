from comfygit_cli.cli import create_parser


def test_config_accepts_huggingface_token_flag():
    parser = create_parser()

    args = parser.parse_args(["config", "--huggingface-token", "hf_test"])

    assert args.command == "config"
    assert args.huggingface_token == "hf_test"
