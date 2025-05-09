# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run configuration phase for cos-agent charm."""
import logging

from dataclasses import dataclass
from typing import List

import zaza.charm_lifecycle.utils as lifecycle_utils
import zaza.controller
import zaza.model

from juju.client._definitions import ApplicationOfferAdminDetails
from zaza import sync_wrapper


GRAFANA_OFFER_ALIAS = "cos-grafana"
PROMETHEUS_OFFER_ALIAS = "cos-prometheus"


@dataclass
class CosOffer:
    """Collection of information about cross-model relation offer.

    :param interface: Interface which at least one endpoint in the offer must
                      implement.
    :param role: Role of the interface. Either 'provider' or 'requirer'
    :param alias: Alias under which is the offer consumed
    """

    interface: str
    role: str
    alias: str


COS_OFFERS = [
    CosOffer("prometheus_remote_write", "provider", PROMETHEUS_OFFER_ALIAS),
    CosOffer("grafana_dashboard", "requirer", GRAFANA_OFFER_ALIAS),
]


async def async_list_offers(model: str) -> List[ApplicationOfferAdminDetails]:
    """Return a list of cross-model realtions offered by the model.

    :param model: Name of the model that's searched for the offers

    :returns: List of offers
    """
    controller = zaza.controller.Controller()
    await controller.connect()
    offer_data = await controller.list_offers(model)
    await controller.disconnect()
    return offer_data.get("results", [])


async def async_consume_cos_offers(consumer_model_name: str) -> List[CosOffer]:
    """Consume cross-model relations offers provided by COS model.

    Any offer that contains endpoint with correct interface and a role
    (defined by COS_OFFERS) will be consumed.

    :param consumer_model_name: Name of the model that should consume offers

    :returns: List of CosOffer that were consumed
    """
    consumed_offers = []
    consumer = await zaza.model.get_model(consumer_model_name)

    for model_name in await zaza.controller.async_list_models():
        for offer in await async_list_offers(model_name):
            for endpoint in offer.endpoints:
                for cos_ep in COS_OFFERS:
                    if (
                        endpoint.interface == cos_ep.interface and
                        endpoint.role == cos_ep.role
                    ):
                        logging.info(
                            f"Consuming offer: {offer.offer_url}"
                            f" under alias {cos_ep.alias}"
                        )
                        await consumer.consume(offer.offer_url, cos_ep.alias)
                        consumed_offers.append(cos_ep)

    return consumed_offers


consume_cos_offers = sync_wrapper(async_consume_cos_offers)


async def async_relate_grafana_agent(
    model_name: str, cos_offers: List[CosOffer]
) -> None:
    """Relate application grafana-agent to the offered COS applications.

    :param model_name: Name of the model in which grafana-agent resides.
    :param cos_offers: List of cross-model relation offers to which
                       grafana-agent should be related.

    :returns: None
    """
    model = await zaza.model.get_model(model_name)
    for cos_ep in cos_offers:
        logging.info(f"Relating grafana-agent to offer {cos_ep.alias}")
        await model.integrate("grafana-agent", cos_ep.alias)


relate_grafana_agent = sync_wrapper(async_relate_grafana_agent)


def try_relate_to_cos():
    """Attempt to relate grafana-agent with COS applications."""
    logging.info(
        "Attempting to relate grafana-agent to COS via cross-model relations"
    )
    model = zaza.model.get_juju_model()
    cos_offers = consume_cos_offers(model)
    if cos_offers:
        relate_grafana_agent(model, cos_offers)
        zaza.model.wait_for_agent_status()
        test_config = lifecycle_utils.get_charm_config(fatal=False)
        test_config['target_deploy_status']['grafana-agent'][
            'workload-status'
        ] = 'active'
        zaza.model.wait_for_application_states(
            states=test_config.get("target_deploy_status", {}), timeout=7200
        )
    else:
        logging.warn(
            "No COS cross-model relation offers found. grafana-agent"
            " will remain blocked"
        )
