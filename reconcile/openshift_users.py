import logging
from multiprocessing.dummy import Pool as ThreadPool
from functools import partial

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources
import reconcile.openshift_groups as openshift_groups

CLUSTERS_QUERY = """
{
  clusters: clusters_v1 {
    name
    serverUrl
    jumpHost {
      hostname
      knownHosts
      user
      port
      identity {
        path
        field
        format
      }
    }
    unManaged
    managedGroups
    automationToken {
      path
      field
      format
    }
  }
}
"""

ROLES_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      github_username
    }
    permissions {
      ...on PermissionOpenshiftRolebinding_v1 {
        service
        cluster
      }
    }
  }
}
"""


def get_cluster_users(cluster, oc_map):
    oc = oc_map[cluster]
    users = [u['metadata']['name'] for u in oc.get_users()
             if len(u['identities']) == 1
             and u['identities'][0].startswith('github')]

    return [{"cluster": cluster, "user": user} for user in users or []]


def create_oc_map(clusters):
    oc_map = {}
    for cluster_info in clusters:
        cluster = cluster_info['name']
        if cluster_info['unManaged']:
            continue
        oc = openshift_resources.obtain_oc_client(oc_map, cluster_info)
        oc_map[cluster] = oc
    return oc_map


def fetch_current_state(thread_pool_size):
    gqlapi = gql.get_api()
    clusters = gqlapi.query(CLUSTERS_QUERY)['clusters']
    oc_map = create_oc_map(clusters)

    pool = ThreadPool(thread_pool_size)
    cluster_names = [k for k, v in oc_map.items() if v]
    get_cluster_users_partial = \
        partial(get_cluster_users, oc_map=oc_map)
    results = pool.map(get_cluster_users_partial, cluster_names)
    current_state = [item for sublist in results for item in sublist]
    return oc_map, current_state


def fetch_desired_state():
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    desired_state = []

    for r in roles:
        for p in r['permissions']:
            if 'service' not in p:
                continue
            if p['service'] != 'openshift-rolebinding':
                continue

            for u in r['users']:
                if u['github_username'] is None:
                    continue

                desired_state.append({
                    "cluster": p['cluster'],
                    "user": u['github_username']
                })

    groups_desired_state = openshift_groups.fetch_desired_state()
    flat_groups_desired_state = \
        [{'cluster': s['cluster'], 'user': s['user']}
         for s in groups_desired_state]
    desired_state.extend(flat_groups_desired_state)
    return desired_state


def calculate_diff(current_state, desired_state):
    diff = []
    users_to_del = \
        subtract_states(current_state, desired_state,
                        "del_user")
    diff.extend(users_to_del)

    return diff


def subtract_states(from_state, subtract_state, action):
    result = []

    for f_user in from_state:
        found = False
        for s_user in subtract_state:
            if f_user != s_user:
                continue
            found = True
            break
        if not found:
            result.append({
                "action": action,
                "cluster": f_user['cluster'],
                "user": f_user['user']
            })

    return result


def act(diff, oc_map):
    cluster = diff['cluster']
    user = diff['user']
    action = diff['action']

    if action == "del_user":
        oc_map[cluster].delete_user(user)
    else:
        raise Exception("invalid action: {}".format(action))


def run(dry_run=False, thread_pool_size=10):
    oc_map, current_state = fetch_current_state(thread_pool_size)
    desired_state = fetch_desired_state()

    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(diff.values())

        if not dry_run:
            act(diff, oc_map)