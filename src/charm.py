#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the application."""

import logging

import ops
import requests
from charms.tls_certificates_interface.v3.tls_certificates import (
    CertificateCreationRequestEvent,
    TLSCertificatesProvidesV3,
)

logger = logging.getLogger(__name__)


class GocertCharm(ops.CharmBase):
    """Charmed Gocert."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container("gocert")
        self.tls = TLSCertificatesProvidesV3(self, relationship_name="certificates")

        self.port = 2111

        framework.observe(self.on["gocert"].pebble_ready, self._install)
        framework.observe(self.on["gocert"].pebble_custom_notice, self._on_gocert_notify)
        framework.observe(self.tls.on.certificate_creation_request, self._on_new_certificate)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

    def _install(self, event: ops.PebbleReadyEvent):
        try:
            self.container.pull("/etc/config/config.yaml")
        except ops.pebble.PathError:
            config_file = open("src/configs/config.yaml").read()
            cert_file = open("src/configs/cert.pem").read()
            key_file = open("src/configs/key.pem").read()
            self.container.make_dir(path="/etc/config", make_parents=True)
            self.container.push(path="/etc/config/config.yaml", source=config_file)
            self.container.push(path="/etc/config/cert.pem", source=cert_file)
            self.container.push(path="/etc/config/key.pem", source=key_file)
            self.container.add_layer("gocert", self._pebble_layer, combine=True)
            self.container.replan()

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        event.add_status(ops.ActiveStatus())

    def _on_new_certificate(self, event: CertificateCreationRequestEvent):
        csr = event.certificate_signing_request
        requests.post(
            url=f"https://localhost:{self.port}/api/v1/certificate_requests",
            data=csr,
            headers={"Content-Type": "text/plain"},
            verify=False,
        )

    def _on_gocert_notify(self, event: ops.PebbleCustomNoticeEvent):
        r = requests.get(
            url=f"https://localhost:{self.port}/api/v1/certificate_requests", verify=False
        )
        response_data = r.json()
        for relation in self.model.relations["certificates"]:
            unfulfilled_csrs = self.tls.get_outstanding_certificate_requests(
                relation_id=relation.id
            )
            for row in response_data:
                csr = row.get("CSR")
                cert = row.get("Certificate")
                for relation_csr in unfulfilled_csrs:
                    if csr == relation_csr.csr:
                        self.tls.set_relation_certificate(
                            certificate_signing_request=csr,
                            certificate=cert,
                            ca="",
                            chain=[cert],
                            relation_id=relation.id,
                        )

    @property
    def _pebble_layer(self) -> ops.pebble.LayerDict:
        """Return a dictionary representing a Pebble layer."""
        return {
            "summary": "gocert layer",
            "description": "pebble config layer for gocert",
            "services": {
                "gocert": {
                    "override": "replace",
                    "summary": "gocert",
                    "command": "gocert -config /etc/config/config.yaml",
                    "startup": "enabled",
                }
            },
        }


if __name__ == "__main__":  # pragma: nocover
    ops.main(GocertCharm)  # type: ignore
