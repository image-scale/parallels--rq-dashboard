# Web blueprint
import re
from urllib.parse import urlparse

import arrow
import redis
from flask import Blueprint, current_app, jsonify, make_response, render_template_string, request
from redis_sentinel_url import connect as sentinel_connect
from rq import Queue, Worker
from rq.job import Job
from rq.registry import (
    BaseRegistry,
    DeferredJobRegistry,
    FailedJobRegistry,
    FinishedJobRegistry,
    ScheduledJobRegistry,
    StartedJobRegistry,
    CanceledJobRegistry,
)

blueprint = Blueprint('rq_dashboard', __name__)

# Map registry names to classes
REGISTRY_MAP = {
    'queued': None,  # Special case - uses Queue directly
    'failed': FailedJobRegistry,
    'deferred': DeferredJobRegistry,
    'scheduled': ScheduledJobRegistry,
    'started': StartedJobRegistry,
    'finished': FinishedJobRegistry,
    'canceled': CanceledJobRegistry,
}


def escape_format_instance_list(urls):
    """Escape and format Redis instance URLs by masking credentials."""
    result = []
    for url in urls:
        parsed = urlparse(url)
        # Reconstruct URL with masked credentials
        if parsed.username or parsed.password:
            netloc = f"***:***@{parsed.hostname}"
        else:
            netloc = parsed.hostname
        if parsed.port:
            netloc += f":{parsed.port}"
        masked = f"{parsed.scheme}://{netloc}"
        if parsed.path:
            masked += parsed.path
        result.append(masked)
    return result


def setup_rq_connection(app):
    """Set up RQ connection for Flask app."""
    redis_url = app.config.get('RQ_DASHBOARD_REDIS_URL', ['redis://127.0.0.1:6379'])
    if isinstance(redis_url, str):
        redis_url = [redis_url]

    sentinels = app.config.get('RQ_DASHBOARD_REDIS_SENTINELS')
    master_name = app.config.get('RQ_DASHBOARD_REDIS_MASTER_NAME')

    connections = []
    for url in redis_url:
        if sentinels and master_name:
            conn = sentinel_connect(url, sentinels=sentinels, master_name=master_name)
        else:
            conn = redis.Redis.from_url(url)
        connections.append(conn)

    app.redis_connections = connections
    app.redis_conn = connections[0] if connections else None


def get_redis_conn(instance_number=0):
    """Get Redis connection by instance number."""
    connections = getattr(current_app, 'redis_connections', [])
    if connections and instance_number < len(connections):
        return connections[instance_number]
    return current_app.redis_conn


def serialize_job(job):
    """Serialize job info to dict."""
    return {
        'id': job.id,
        'description': job.description or '',
        'origin': job.origin or '',
        'status': job.get_status() if hasattr(job, 'get_status') else '',
        'created_at': job.created_at.isoformat() if job.created_at else '',
        'enqueued_at': job.enqueued_at.isoformat() if job.enqueued_at else '',
        'started_at': job.started_at.isoformat() if job.started_at else '',
        'ended_at': job.ended_at.isoformat() if job.ended_at else '',
        'exc_info': job.exc_info or '',
        'result': str(job.result) if job.result else '',
    }


def serialize_worker(worker):
    """Serialize worker info to dict."""
    result = {
        'name': worker.name,
        'queues': [q.name for q in worker.queues],
        'state': worker.get_state(),
        'current_job': worker.get_current_job_id() or '',
        'birth_date': worker.birth_date.isoformat() if worker.birth_date else '',
        'last_heartbeat': worker.last_heartbeat.isoformat() if hasattr(worker, 'last_heartbeat') and worker.last_heartbeat else '',
        'successful_job_count': getattr(worker, 'successful_job_count', 0),
        'failed_job_count': getattr(worker, 'failed_job_count', 0),
        'total_working_time': getattr(worker, 'total_working_time', 0),
    }
    # Add python_version and version fields
    result['python_version'] = getattr(worker, 'python_version', '') or ''
    result['version'] = getattr(worker, 'version', '') or ''
    return result


def get_jobs_from_registry(queue, registry_name, start, end, sort_order='asc'):
    """Get jobs from a registry with pagination."""
    conn = queue.connection

    if registry_name == 'queued':
        job_ids = queue.get_job_ids()
    else:
        registry_class = REGISTRY_MAP.get(registry_name)
        if registry_class:
            registry = registry_class(queue.name, connection=conn)
            job_ids = registry.get_job_ids()
        else:
            job_ids = []

    # Sort by created_at
    jobs = []
    for job_id in job_ids:
        try:
            job = Job.fetch(job_id, connection=conn)
            jobs.append(job)
        except:
            pass

    # Sort jobs by created_at
    jobs.sort(key=lambda j: j.created_at or arrow.utcnow().datetime, reverse=(sort_order == 'dsc'))

    # Paginate
    total = len(jobs)
    jobs = jobs[start:end]

    return jobs, total


def serialize_queue(queue, conn):
    """Serialize queue info to dict."""
    result = {
        'name': queue.name,
        'count': queue.count,
        'queued_count': queue.count,
    }

    # Add registry counts
    for registry_name, registry_class in REGISTRY_MAP.items():
        if registry_name == 'queued':
            continue
        if registry_class:
            registry = registry_class(queue.name, connection=conn)
            result[f'{registry_name}_count'] = registry.get_job_count(cleanup=False)

    return result


# Dashboard home page
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>RQ Dashboard</title>
</head>
<body>
    <h1>RQ Dashboard</h1>
    <p>Monitor your RQ queues, jobs, and workers.</p>
</body>
</html>
'''

JOB_VIEW_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>RQ Dashboard - Jobs</title>
</head>
<body>
    <h1>Jobs</h1>
</body>
</html>
'''

SINGLE_JOB_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>RQ Dashboard - Job {{ job_id }}</title>
</head>
<body>
    <h1>Job: {{ job_id }}</h1>
</body>
</html>
'''

WORKERS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>RQ Dashboard - Workers</title>
</head>
<body>
    <h1>Workers</h1>
</body>
</html>
'''


@blueprint.route('/')
def index():
    """Dashboard home page."""
    return render_template_string(DASHBOARD_TEMPLATE)


@blueprint.route('/<int:instance_number>/data/queues.json')
def queues_json(instance_number):
    """Return list of queues as JSON."""
    conn = get_redis_conn(instance_number)
    queues = Queue.all(connection=conn)

    data = {
        'queues': [serialize_queue(q, conn) for q in queues]
    }

    response = make_response(jsonify(data))
    response.headers['Cache-Control'] = 'no-store'
    return response


@blueprint.route('/<int:instance_number>/data/workers.json')
def workers_json(instance_number):
    """Return list of workers as JSON."""
    conn = get_redis_conn(instance_number)
    workers = Worker.all(connection=conn)

    data = {
        'workers': [serialize_worker(w) for w in workers]
    }

    return jsonify(data)


@blueprint.route('/<int:instance_number>/view/jobs')
def jobs_view(instance_number):
    """Jobs overview page."""
    return render_template_string(JOB_VIEW_TEMPLATE)


@blueprint.route('/<int:instance_number>/view/jobs/<queue_name>/<registry_name>/<int:page_size>/<sort_order>/<int:page>')
def jobs_view_registry(instance_number, queue_name, registry_name, page_size, sort_order, page):
    """Jobs list for a specific registry."""
    return render_template_string(JOB_VIEW_TEMPLATE)


@blueprint.route('/<int:instance_number>/data/jobs/<queue_name>/<registry_name>/<int:page_size>/<sort_order>/<int:page>.json')
def jobs_json(instance_number, queue_name, registry_name, page_size, sort_order, page):
    """Return jobs from a specific queue and registry as JSON."""
    conn = get_redis_conn(instance_number)
    queue = Queue(queue_name, connection=conn)

    start = (page - 1) * page_size
    end = start + page_size

    jobs, total = get_jobs_from_registry(queue, registry_name, start, end, sort_order)

    data = {
        'jobs': [serialize_job(j) for j in jobs],
        'total': total,
        'page': page,
        'page_size': page_size,
    }

    return jsonify(data)


@blueprint.route('/<int:instance_number>/view/job/<job_id>')
def job_view(instance_number, job_id):
    """Single job detail page."""
    return render_template_string(SINGLE_JOB_TEMPLATE, job_id=job_id)


@blueprint.route('/<int:instance_number>/data/job/<job_id>.json')
def job_json(instance_number, job_id):
    """Return single job info as JSON."""
    conn = get_redis_conn(instance_number)

    try:
        job = Job.fetch(job_id, connection=conn)
        data = serialize_job(job)
    except:
        data = {'error': 'Job not found'}

    return jsonify(data)


@blueprint.route('/job/<job_id>/delete', methods=['POST'])
def job_delete(job_id):
    """Delete a job."""
    conn = current_app.redis_conn

    try:
        job = Job.fetch(job_id, connection=conn)
        job.delete()
        return jsonify({'status': 'OK'})
    except:
        return jsonify({'status': 'OK'})


@blueprint.route('/job/<job_id>/requeue', methods=['POST'])
def job_requeue(job_id):
    """Requeue a failed job."""
    conn = current_app.redis_conn

    try:
        job = Job.fetch(job_id, connection=conn)
        job.requeue()
        return jsonify({'status': 'OK'})
    except:
        return jsonify({'status': 'OK'})


@blueprint.route('/queue/<queue_name>/compact', methods=['POST'])
def queue_compact(queue_name):
    """Compact a queue."""
    conn = current_app.redis_conn
    queue = Queue(queue_name, connection=conn)
    queue.compact()
    return jsonify({'status': 'OK'})


@blueprint.route('/queue/<queue_name>/<registry_name>/empty', methods=['POST'])
def queue_empty(queue_name, registry_name):
    """Empty a registry."""
    conn = current_app.redis_conn

    if registry_name == 'queued':
        queue = Queue(queue_name, connection=conn)
        queue.empty()
    else:
        registry_class = REGISTRY_MAP.get(registry_name)
        if registry_class:
            queue = Queue(queue_name, connection=conn)
            registry = registry_class(queue.name, connection=conn)
            for job_id in registry.get_job_ids():
                try:
                    job = Job.fetch(job_id, connection=conn)
                    job.delete()
                except:
                    pass

    return jsonify({'status': 'OK'})


@blueprint.route('/requeue/<queue_name>', methods=['GET', 'POST'])
def requeue_all(queue_name):
    """Requeue all failed jobs in a queue."""
    conn = current_app.redis_conn
    queue = Queue(queue_name, connection=conn)

    failed_registry = FailedJobRegistry(queue.name, connection=conn)
    for job_id in failed_registry.get_job_ids():
        try:
            job = Job.fetch(job_id, connection=conn)
            job.requeue()
        except:
            pass

    return jsonify({'status': 'OK'})


@blueprint.route('/<int:instance_number>/view/workers')
def workers_view(instance_number):
    """Workers overview page."""
    return render_template_string(WORKERS_TEMPLATE)
