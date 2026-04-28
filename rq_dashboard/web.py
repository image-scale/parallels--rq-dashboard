# Web blueprint - stubs
from flask import Blueprint

blueprint = Blueprint('rq_dashboard', __name__)


def setup_rq_connection(app):
    """Set up RQ connection for Flask app."""
    raise NotImplementedError


def escape_format_instance_list(urls):
    """Escape and format Redis instance URLs."""
    raise NotImplementedError
