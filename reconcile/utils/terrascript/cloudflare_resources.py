from typing import Union

from terrascript import Resource, Output
from terrascript.resource import (
    cloudflare_record,
    cloudflare_worker_route,
    cloudflare_worker_script,
    cloudflare_zone,
    cloudflare_zone_settings_override,
)

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.external_resources import ResourceValueResolver
from reconcile.utils.terrascript.resources import TerrascriptResource


class UnsupportedCloudflareResourceError(Exception):
    pass


def create_cloudflare_terrascript_resource(
    spec: ExternalResourceSpec,
) -> list[Union[Resource, Output]]:
    """
    Create the required Cloudflare Terrascript resources as defined by the external
    resources spec.
    """
    resource_type = spec.provision_provider

    if resource_type == "cloudflare_zone":
        return CloudflareZoneTerrascriptResource(spec).populate()
    elif resource_type == "cloudflare_record":
        return CloudflareRecordTerrascriptResource(spec).populate()
    elif resource_type == "cloudflare_worker":
        return CloudflareWorkerTerrascriptResource(spec).populate()
    else:
        raise UnsupportedCloudflareResourceError(
            f"The resource type {resource_type} is not supported"
        )


class CloudflareRecordTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_record."""

    def populate(self) -> list[Union[Resource, Output]]:

        values = ResourceValueResolver(self._spec).resolve()
        zone_id = values.pop("zone_id")
        record_values = values
        record_values["zone_id"] = f"${{cloudflare_zone.{zone_id}.id}}"
        record_values["depends_on"] = [f"cloudflare_zone.{zone_id}"]
        record = cloudflare_record(self._spec.identifier, **record_values)

        return [record]


class CloudflareWorkerTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_worker."""

    def populate(self) -> list[Union[Resource, Output]]:

        values = ResourceValueResolver(self._spec).resolve()
        zone_id = values.pop("zone_id")

        worker_script_name = values.pop("script_name")
        worker_script_content = values.pop("script_content")
        worker_script_values = {
            "name": worker_script_name,
            "content": worker_script_content,
        }
        worker_script = cloudflare_worker_script(
            self._spec.identifier, **worker_script_values
        )

        worker_values = values
        worker_values["script_name"] = worker_script_name
        worker_values["zone_id"] = f"${{cloudflare_zone.{zone_id}.id}}"
        worker_values["depends_on"] = [f"cloudflare_zone.{zone_id}"]
        worker = cloudflare_worker_route(self._spec.identifier, **worker_values)

        return [worker, worker_script]


class CloudflareZoneTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_zone and related resources."""

    def populate(self) -> list[Union[Resource, Output]]:

        values = ResourceValueResolver(self._spec).resolve()

        zone_settings = values.pop("settings", {})

        zone_values = values
        zone = cloudflare_zone(self._spec.identifier, **zone_values)

        settings_override_values = {
            "zone_id": f"${{{zone.id}}}",
            "settings": zone_settings,
            "depends_on": self._get_dependencies([zone]),
        }

        zone_settings_override = cloudflare_zone_settings_override(
            self._spec.identifier, **settings_override_values
        )

        return [zone, zone_settings_override]
