"""Private headless entry point. No interactive Hermes command is installed."""
import sys


def validate_args(args):
    args = list(args)
    if args[:1] in (["--profile"], ["-p"]):
        if len(args) < 3:
            raise ValueError("A profile and backend command are required")
        args = args[2:]
    if not args or args[0] not in ("serve", "--version"):
        raise ValueError("This package only provides the Hermes Desktop backend")


if __name__ == "__main__":
    try:
        validate_args(sys.argv[1:])
    except ValueError as error:
        sys.exit(str(error))
    from hermes_cli.main import main
    main()
