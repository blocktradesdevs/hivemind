"""Conf handles reading run-time config and app-level settings."""

import re
import logging
import configargparse

from hive.steem.client import SteemClient
from hive.db.adapter import Db
from hive.utils.normalize import strtobool, int_log_level
from hive.utils.stats import DbStats

def _sanitized_conf(parser):
    """Formats parser config, redacting database url password."""
    out = parser.format_values()
    return re.sub(r'(?<=:)\w+(?=@)', '<redacted>', out)

class Conf():
    """ Manages sync/server configuration via args, ENVs, and hive.conf. """

    @classmethod
    def init_argparse(cls, strict=True, **kwargs):
        """Read hive config (CLI arg > ENV var > config)"""

        #pylint: disable=line-too-long
        parser = configargparse.get_arg_parser(
            default_config_files=['./hive.conf'],
            **kwargs)
        add = parser.add

        # runmodes: sync, server, status
        add('mode', nargs='*', default=['sync'])

        # common
        add('--database-url', env_var='DATABASE_URL', required=False, help='database connection url', default='')
        add('--steemd-url', env_var='STEEMD_URL', required=False, help='steemd/jussi endpoint', default='{"default" : "https://api.steemit.com"}')
        add('--muted-accounts-url', env_var='MUTED_ACCOUNTS_URL', required=False, help='url to flat list of muted accounts', default='')

        # server
        add('--http-server-port', type=int, env_var='HTTP_SERVER_PORT', default=8080)

        # sync
        add('--max-workers', type=int, env_var='MAX_WORKERS', help='max workers for batch requests', default=4)
        add('--max-batch', type=int, env_var='MAX_BATCH', help='max chunk size for batch requests', default=50)
        add('--trail-blocks', type=int, env_var='TRAIL_BLOCKS', help='number of blocks to trail head by', default=2)
        add('--sync-to-s3', type=strtobool, env_var='SYNC_TO_S3', help='alternative healthcheck for background sync service', default=False)

        # test/debug
        add('--log-level', env_var='LOG_LEVEL', default='INFO')
        add('--test-disable-sync', type=strtobool, env_var='TEST_DISABLE_SYNC', help='(debug) skip sync and sweep; jump to block streaming', default=False)
        add('--test-max-block', type=int, env_var='TEST_MAX_BLOCK', help='(debug) only sync to given block, for running sync test', default=None)

        # needed for e.g. tests - other args may be present
        args = (parser.parse_args() if strict
                else parser.parse_known_args()[0])
        conf = Conf(args=vars(args))

        # configure logger and print config
        root = logging.getLogger()
        root.setLevel(conf.log_level())
        root.info("loaded configuration:\n%s",
                  _sanitized_conf(parser))

        if conf.mode() == 'server':
            DbStats.SLOW_QUERY_MS = 750

        return conf

    @classmethod
    def init_test(cls):
        """Initialize hive config for testing."""
        return cls.init_argparse(strict=False)

    def __init__(self, args, env=None):
        self._args = args
        self._env = env
        self._db = None
        self._steem = None

    def args(self):
        """Get the raw Namespace object as generated by configargparse"""
        return self._args

    def steem(self):
        """Get a SteemClient instance, lazily initialized"""
        if not self._steem:
            from json import loads
            self._steem = SteemClient(
                url=loads(self.get('steemd_url')),
                max_batch=self.get('max_batch'),
                max_workers=self.get('max_workers'))
        return self._steem

    def db(self):
        """Get a configured instance of Db."""
        if not self._db:
            url = self.get('database_url')
            assert url, ('--database-url (or DATABASE_URL env) not specified; '
                         'e.g. postgresql://user:pass@localhost:5432/hive')
            self._db = Db(url)
        return self._db

    def get(self, param):
        """Reads a single property, e.g. `database_url`."""
        assert self._args, "run init_argparse()"
        return self._args[param]

    def mode(self):
        """Get the CLI runmode.

        - `server`: API server
        - `sync`: db sync process
        - `status`: status info dump
        """
        return '/'.join(self.get('mode'))

    def log_level(self):
        """Get `logger`s internal int level from config string."""
        return int_log_level(self.get('log_level'))
