import logging

import reconcile.gql as gql
from reconcile.config import get_config
import json
from jinja2 import Template

CLUSTER_QUERY = """
{
  cluster {
    name
    description
    labels
    serverUrl
    managedRoles {
      namespace
      role
    }
  }
}
"""

APP_QUERY = """
{
  app {
    title
    labels
    serviceOwner {
      name
      email
    }
    dependencies {
      name
      statefulness
      opsModel
      statusPage
      SLA
      dependencyFailureImpact
    }
    quayRepos {
      org {
        name
        description
        managedTeams
        labels
      }
      items {
        name
        description
        public
      }
    }
  }
}
"""

SUMMARY = Template("""
<!DOCTYPE html>
<html lang="en">
<head>
    <title>App-SRE Summary dashboard</title>
    <style>
    body {
      background-color: lightGray;
      font-size: 12px;
    }

    .content {
      max-width: 700px;
      margin: auto;
    }

    h1 {
      color: maroon;
      margin-left: 40px;
    }
    table, th, td {
      border: 1px solid black;
      border-collapse: collapse;
      border-spacing: 0px;
    }
    
    </style>
</head>
<body>
  <div class="content">
    <h1>App-SRE Summary dashboard</h1>
    <table class="apps">
      <thead>
        <tr>
          <th>App</th>
          <th>Owner</th>
          <th>Dependencies</th>
        </tr>
      </thead>
      <tbody>
      {% for app in apps %}
        <tr>
          <td>
            <b>{{app.title|default('MissingTitle')}}</b>
            <br/>
            {% for label in app.labels %}
            <i>{{label}}={{app.labels[label]}}{{", " if not loop.last}}</i>
            {% endfor %}
          </td>
          <td>
            {{app.serviceOwner.name}}<br/><a href="mailto:{{app.serviceOwner.email}}">{{app.serviceOwner.email}}</a>
          </td>
          <td>
            <ul>
            {% for dep in app.dependencies %}
              <li><b>Name:</b> {{dep.name}}</li>
              <li><b>Statefulness:</b> {{dep.statefulness}}</li>
              <li><b>OpsModel:</b> {{dep.opsModel}}</li>
              <li><b>StatusPage:</b> {{dep.statusPage}}</li>
              <li><b>SLA:</b> {{dep.SLA}}</li>
              <li><b>DependencyFailureImpact:</b> {{dep.dependencyFailureImpact}}</li>
            {% endfor %}
            </ul>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</body>
</html>
""")


def run(dry_run=False):
    gqlapi = gql.get_api()
    apps = gqlapi.query(APP_QUERY)
    clusters = gqlapi.query(CLUSTER_QUERY)

    if not dry_run:
      pass

    out = SUMMARY.render(apps=apps['app'])
    print(out)
