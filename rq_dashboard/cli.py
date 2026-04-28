# CLI module
import sys
from functools import wraps

import click
from flask import Flask

from . import default_settings
from .web import blueprint, setup_rq_connection


def add_basic_auth(app, username, password):
    """Add HTTP Basic Authentication to the app."""
    @app.before_request
    def check_auth():
        from flask import request, Response
        if username:
            auth = request.authorization
            if not auth or auth.username != username or auth.password != password:
                return Response(
                    'Access denied',
                    401,
                    {'WWW-Authenticate': 'Basic realm="Login Required"'}
                )


def make_flask_app(config, username, password, url_prefix):
    """Create Flask app with rq-dashboard blueprint."""
    app = Flask(__name__)

    # Load default settings
    app.config.from_object(default_settings)

    # Load config if provided
    if config:
        app.config.from_object(config)

    # Setup RQ connection
    setup_rq_connection(app)

    # Add basic auth if configured
    if username:
        add_basic_auth(app, username, password)

    # Register blueprint
    app.register_blueprint(blueprint, url_prefix=url_prefix)

    return app


@click.command()
@click.option('-b', '--bind', default='127.0.0.1', help='IP or hostname on which to bind HTTP server')
@click.option('-p', '--port', default=9181, type=int, help='Port on which to bind HTTP server')
@click.option('--url-prefix', default='', help='URL prefix e.g. for use behind a reverse proxy')
@click.option('--username', default=None, help='HTTP Basic Auth username (not used if not set)')
@click.option('--password', default=None, help='HTTP Basic Auth password')
@click.option('-c', '--config', default=None, help='Configuration file (Python module on search path)')
@click.option('-u', '--redis-url', default=['redis://127.0.0.1:6379'], multiple=True, help='Redis URL. Can be specified multiple times.')
@click.option('--poll-interval', '--interval', default=2500, type=int, help='Refresh interval in ms')
@click.option('--extra-path', default=None, help='Append specified directories to sys.path')
@click.option('--disable-delete', is_flag=True, help='Disable delete jobs, clean up registries')
@click.option('--debug/--normal', default=False, help='Enter DEBUG mode')
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose logging')
@click.option('-j', '--json', 'use_json', is_flag=True, help='Enable JSONSerializer')
def main(bind, port, url_prefix, username, password, config, redis_url, poll_interval, extra_path, disable_delete, debug, verbose, use_json):
    """Run the RQ Dashboard Flask server.

    All configuration can be set on the command line or through environment
    variables of the form RQ_DASHBOARD_*. For example RQ_DASHBOARD_USERNAME.

    A subset of the configuration (the configuration parameters used by the
    underlying flask blueprint) can also be provided in a Python module
    referenced using --config, or with a .cfg file referenced by the
    RQ_DASHBOARD_SETTINGS environment variable.
    """
    if extra_path:
        sys.path.insert(0, extra_path)

    app = make_flask_app(config, username, password, url_prefix)

    # Override settings from command line
    app.config['RQ_DASHBOARD_REDIS_URL'] = list(redis_url)
    app.config['RQ_DASHBOARD_POLL_INTERVAL'] = poll_interval
    if disable_delete:
        app.config['RQ_DASHBOARD_DELETE_JOBS'] = False

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    app.run(host=bind, port=port, debug=debug)


if __name__ == '__main__':
    main()
