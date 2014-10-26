# Copyright (c) 2014 Scopely, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import os

__version__ = open(os.path.join(os.path.dirname(__file__), '_version')).read()

import time
import datetime
import logging

import pytz
import elasticsearch
import skew

escape_chars = ['+', '-', '&&', '||', '!', '(', ')', '{', '}', '[', ']',
                '^', '"', '~', '*', '?', ':', '\\']

LOG = logging.getLogger(__name__)


class Query(object):

    def __init__(self, host, port=9200):
        self._es = elasticsearch.Elasticsearch(
            hosts=[{'host': host, 'port': port}])

    def search(self, query_string=None, body=None):
        results = self._es.search(
            q=query_string, body=body, analyze_wildcard=True)
        return results['hits']['hits']


class Skewer(object):

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.ts = int(time.time())
        self.es = elasticsearch.Elasticsearch(
            hosts=[{'host': host, 'port': port}])

    def _index_name(self):
        return 'skewer'

    def create_template(self):
        template_path = os.path.join(
            os.path.dirname(__file__),
            'skewer-es-template.json'
        )
        with open(template_path, 'r') as fh:
            template_body = fh.read()
        self.es.indices.put_template(
            name="skewer",
            body=template_body
        )

    def clear_index(self):
        LOG.debug('Deleting existing indices')
        self.es.indices.delete('skewer')

    def index_aws(self, arn_pattern='arn:aws:*:*:*:*/*'):
        now = datetime.datetime.utcnow().isoformat()
        now = pytz.utc.localize(now)
        self.create_template()
        all_services = set()
        all_regions = set()
        all_accounts = set()

        index_name = self._index_name()

        LOG.debug('using ARN: %s', arn_pattern)

        i = 0
        arn = skew.scan(arn_pattern)

        for resource in arn:
            _, _, service, region, acct_id, _ = str(resource).split(':', 5)
            resource.data['service'] = service
            resource.data['region'] = region
            resource.data['account_id'] = acct_id
            resource.data['arn'] = resource.arn
            resource.data['timestamp'] = now
            
            all_services.add(service)
            all_regions.add(region)
            all_accounts.add(acct_id)
            id = '%s-%s' % (resource.arn, now)
            self.es.index(index_name, doc_type=resource.resourcetype,
                          id=id, body=resource.data)
            i += 1
        LOG.debug('indexed %d resources', i)

        # Write updated metadata to ES
        metadata = {
            'services': list(all_services),
            'regions': list(all_regions),
            'accounts': list(all_accounts)}
        self.es.index('skewer-meta', doc_type='skewermeta',
                      id='skewermeta', body=metadata)
