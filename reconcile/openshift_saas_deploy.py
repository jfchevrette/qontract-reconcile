import sys
import semver
import logging

import reconcile.queries as queries
import reconcile.openshift_base as ob
import reconcile.jenkins_plugins as jenkins_base

from reconcile.slack_base import init_slack
from utils.gitlab_api import GitLabApi
from utils.saasherder import SaasHerder
from utils.defer import defer


QONTRACT_INTEGRATION = 'openshift-saas-deploy'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


@defer
def run(dry_run, thread_pool_size=10, io_dir='throughput/',
        saas_file_name=None, env_name=None, defer=None):
    saas_files = queries.get_saas_files(saas_file_name, env_name)
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(1)

    instance = queries.get_gitlab_instance()
    desired_jenkins_instances = [s['instance']['name'] for s in saas_files]
    jenkins_map = jenkins_base.get_jenkins_map(
        desired_instances=desired_jenkins_instances)
    settings = queries.get_app_interface_settings()
    try:
        gl = GitLabApi(instance, settings=settings)
    except Exception:
        # allow execution without access to gitlab
        # as long as there are no access attempts.
        gl = None

    saasherder = SaasHerder(
        saas_files,
        thread_pool_size=thread_pool_size,
        gitlab=gl,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        settings=settings,
        jenkins_map=jenkins_map)
    if len(saasherder.namespaces) == 0:
        logging.warning('no targets found')
        sys.exit(0)

    ri, oc_map = ob.fetch_current_state(
        namespaces=saasherder.namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        init_api_resources=True)
    defer(lambda: oc_map.cleanup())
    saasherder.populate_desired_state(ri)
    # if saas_file_name is defined, the integration
    # is being called from multiple running instances
    actions = ob.realize_data(
        dry_run, oc_map, ri,
        caller=saas_file_name,
        wait_for_namespace=True,
        no_dry_run_skip_compare=(not saasherder.compare),
        take_over=saasherder.take_over
    )

    if not dry_run:
        if saasherder.publish_job_logs:
            try:
                ob.follow_logs(oc_map, actions, io_dir)
            except Exception as e:
                logging.error(str(e))
                ri.register_error()
        try:
            ob.validate_data(oc_map, actions)
        except Exception as e:
            logging.error(str(e))
            ri.register_error()

    if ri.has_error_registered():
        sys.exit(1)

    # send human readable notifications to slack
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    # - output is 'events'
    # - no errors were registered
    if not dry_run and len(saasherder.saas_files) == 1:
        saas_file = saasherder.saas_files[0]
        slack_info = saas_file.get('slack')
        if slack_info and actions and slack_info.get('output') == 'events':
            slack = init_slack(slack_info, QONTRACT_INTEGRATION,
                               init_usergroups=False)
            for action in actions:
                message = \
                    f"[{action['cluster']}] " + \
                    f"{action['kind']} {action['name']} {action['action']}"
                slack.chat_post_message(message)
