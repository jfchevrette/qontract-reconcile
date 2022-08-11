import logging
import sys
from typing import Any, Iterable, List, Optional, Tuple
from unittest.mock import MagicMock

from reconcile import queries
from reconcile.gql_queries.terraform_resources_cloudflare import (
    cloudflare_accounts,
    cloudflare_records,
    cloudflare_workers,
    cloudflare_zones,
)
from reconcile.gql_queries.terraform_resources_cloudflare.cloudflare_accounts import (
    AWSAccountV1,
    CloudflareAccountsQueryData,
    CloudflareAccountV1,
)
from reconcile.gql_queries.terraform_resources_cloudflare.cloudflare_records import (
    CloudflareRecordsQueryData,
    CloudflareRecordV1,
)
from reconcile.gql_queries.terraform_resources_cloudflare.cloudflare_workers import (
    CloudflareWorkersQueryData,
    CloudflareWorkerV1,
)
from reconcile.gql_queries.terraform_resources_cloudflare.cloudflare_zones import (
    CloudflareZonesQueryData,
    CloudflareZoneV1,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.github_api import GithubApi
from reconcile.utils.gql import GqlApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform.config_client import TerraformConfigClientCollection
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript.cloudflare_client import (
    CloudflareAccountConfig,
    TerraformS3BackendConfig,
    TerrascriptCloudflareClient,
    create_cloudflare_terrascript,
)
from reconcile.utils.terrascript_aws_client import safe_resource_id

QONTRACT_INTEGRATION = "terraform_resources_cloudflare"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtfcf"


def get_accounts(gqlapi: GqlApi) -> List[CloudflareAccountV1]:
    res = gqlapi.query(cloudflare_accounts.query_string())
    if res is None:
        logging.error("GraphQL query for cloudflare accounts returned an error")
        sys.exit(ExitCodes.ERROR)
    data = CloudflareAccountsQueryData(**res)
    if data.accounts is None:
        logging.error("No Cloudflare accounts data found")
        sys.exit(ExitCodes.ERROR)
    return data.accounts


def get_records(gqlapi: GqlApi) -> List[CloudflareRecordV1]:
    res = gqlapi.query(cloudflare_records.query_string())
    if res is None:
        logging.error("GraphQL query for cloudflare records returned an error")
        sys.exit(ExitCodes.ERROR)
    data = CloudflareRecordsQueryData(**res)
    if data.records is None:
        logging.error("No Cloudflare records data found")
        sys.exit(ExitCodes.ERROR)
    return data.records


def get_workers(gqlapi: GqlApi) -> List[CloudflareWorkerV1]:
    res = gqlapi.query(cloudflare_workers.query_string())
    if res is None:
        logging.error("GraphQL query for cloudflare workers returned an error")
        sys.exit(ExitCodes.ERROR)
    data = CloudflareWorkersQueryData(**res)
    if data.workers is None:
        logging.error("No Cloudflare workers data found")
        sys.exit(ExitCodes.ERROR)
    return data.workers


def get_zones(gqlapi: GqlApi) -> List[CloudflareZoneV1]:
    res = gqlapi.query(cloudflare_zones.query_string())
    if res is None:
        logging.error("GraphQL query for cloudflare zones returned an error")
        sys.exit(ExitCodes.ERROR)
    data = CloudflareZonesQueryData(**res)
    if data.zones is None:
        logging.error("No Cloudflare zones data found")
        sys.exit(ExitCodes.ERROR)
    return data.zones


def create_backend_config(
    settings: dict[str, Any],
    aws_acct: AWSAccountV1,
    cf_acct: CloudflareAccountV1,
) -> TerraformS3BackendConfig:
    secret_reader = SecretReader(settings=settings)
    aws_acct_creds = secret_reader.read_all({"path": aws_acct.automation_token.path})

    # default from AWS account file
    tf_state = aws_acct.terraform_state
    if tf_state is None:
        raise ValueError(
            f"AWS account {aws_acct.name} cannot be used for Cloudflare "
            f"account {cf_acct.name} because it does define a terraform state "
        )

    bucket_key = f"{QONTRACT_INTEGRATION}-{cf_acct.name}.tfstate"
    bucket_name = tf_state.bucket
    bucket_region = tf_state.region

    backend_config = TerraformS3BackendConfig(
        aws_acct_creds["aws_access_key_id"],
        aws_acct_creds["aws_secret_access_key"],
        bucket_name,
        bucket_key,
        bucket_region,
    )

    return backend_config


def create_cloudflare_account_config(
    settings: dict[str, Any], cf_acct: CloudflareAccountV1
) -> CloudflareAccountConfig:
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    cf_acct_creds = secret_reader.read_all({"path": cf_acct.api_credentials.path})
    return CloudflareAccountConfig(
        cf_acct.name,
        cf_acct_creds["email"],
        cf_acct_creds["api_token"],
        cf_acct_creds["account_id"],
    )


def build_clients(
    accounts: Iterable[CloudflareAccountV1],
) -> List[Tuple[str, TerrascriptCloudflareClient]]:
    settings = queries.get_app_interface_settings()

    clients = []
    for acct in accounts:
        cf_acct_config = create_cloudflare_account_config(settings, acct)

        aws_acct = acct.terraform_state_account
        aws_backend_config = create_backend_config(settings, aws_acct, acct)

        ts_config = create_cloudflare_terrascript(
            cf_acct_config,
            aws_backend_config,
            acct.provider_version,
        )

        ts_client = TerrascriptCloudflareClient(ts_config)
        clients.append((acct.name, ts_client))
    return clients


def build_records(records: Iterable[CloudflareRecordV1]) -> List[ExternalResourceSpec]:
    specs = []
    for r in records:
        spec = ExternalResourceSpec(
            "cloudflare_record",
            {"name": r.zone.account.name, "automationToken": {}},
            {
                "provider": "cloudflare_record",
                "identifier": safe_resource_id(r.name),
                "zone_id": safe_resource_id(r.zone.name),
                "name": r.name,
                "value": r.value,
                "type": r.q_type,
                "ttl": r.ttl,
                "proxied": r.proxied,
            },
            {},
        )
        specs.append(spec)
    return specs


def build_workers(workers: Iterable[CloudflareWorkerV1]) -> List[ExternalResourceSpec]:
    specs = []
    for w in workers:
        gh_repo = w.script.content_from_github.repo
        gh_path = w.script.content_from_github.path
        gh_ref = w.script.content_from_github.ref
        gh = GithubApi(
            queries.get_github_instance(),
            gh_repo,
            queries.get_app_interface_settings(),
        )
        content = gh.get_file(gh_path, gh_ref)
        if content is None:
            raise ValueError(
                f"Could not retrieve Github file content at {gh_repo} "
                f"for file path {gh_path} at ref {gh_ref}"
            )
        worker_script_content = content.decode(encoding="utf-8")
        spec = ExternalResourceSpec(
            "cloudflare_worker",
            {"name": w.zone.account.name, "automationToken": {}},
            {
                "provider": "cloudflare_worker",
                "identifier": safe_resource_id(w.name),
                "zone_id": safe_resource_id(w.zone.name),
                "pattern": w.pattern,
                "script_name": w.script.name,
                "script_content": worker_script_content,
            },
            {},
        )
        specs.append(spec)
    return specs


def build_zones(zones: Iterable[CloudflareZoneV1]) -> List[ExternalResourceSpec]:
    specs = []
    for z in zones:
        spec = ExternalResourceSpec(
            "cloudflare_zone",
            {"name": z.account.name, "automationToken": {}},
            {
                "provider": "cloudflare_zone",
                "identifier": safe_resource_id(z.name),
                "zone": z.name,
                "plan": z.plan,
                "type": z.q_type,
                "settings": z.settings,
            },
            {},
        )
        specs.append(spec)
    return specs


@defer
def run(
    dry_run: bool,
    print_to_file: Optional[str],
    enable_deletion: bool,
    thread_pool_size: int,
    defer=None,
) -> None:
    gqlapi = gql.get_api()

    accounts = get_accounts(gqlapi)
    zones = get_zones(gqlapi)
    records = get_records(gqlapi)
    workers = get_workers(gqlapi)

    # Build Cloudflare clients
    cf_clients = TerraformConfigClientCollection()
    for client in build_clients(accounts):
        cf_clients.register_client(*client)

    # Register Cloudflare zone resources
    zone_specs = build_zones(zones)
    cf_clients.add_specs(zone_specs)

    # Register Cloudflare record resources
    record_specs = build_records(records)
    cf_clients.add_specs(record_specs)

    # Register Cloudflare worker resources
    worker_specs = build_workers(workers)
    cf_clients.add_specs(worker_specs)

    cf_clients.populate_resources()

    working_dirs = cf_clients.dump(print_to_file=print_to_file)

    if print_to_file:
        sys.exit(ExitCodes.SUCCESS)

    tf = TerraformClient(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        [{"name": name for name in cf_clients.dump()}],
        working_dirs,
        thread_pool_size,
        MagicMock(),  # We don't need to pass a real AWS Client here
    )
    if tf is None:
        sys.exit(1)

    defer(tf.cleanup)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    if err:
        sys.exit(1)
    if disabled_deletions_detected:
        sys.exit(1)

    if dry_run:
        return

    err = tf.apply()
    if err:
        sys.exit(1)
