import logging
import os
import sys

from .bot import TranslatorBot
from .config import ConfigError, load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(os.environ)
    except ConfigError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    TranslatorBot(config).run(config.token, log_handler=None)


if __name__ == "__main__":
    main()
