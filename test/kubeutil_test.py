# Copyright (c) 2018 SAP SE or an SAP affiliate company. All rights reserved. This file is licensed under the Apache Software License, v. 2 except as noted otherwise in the LICENSE file
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import MagicMock
import types
import sys

from test._test_utils import capture_out
import kubeutil
from util import Failure

class CtxTest(unittest.TestCase):
    def setUp(self):
        self.examinee = kubeutil.Ctx()
        self.fixture_ctx = types.SimpleNamespace()
        self.fixture_args = types.SimpleNamespace()
        self.fixture_ctx.args = self.fixture_args
        kubeutil.global_ctx = lambda: self.fixture_ctx
        self.kubernetes_config_mock = MagicMock()
        kubeutil.config = self.kubernetes_config_mock

    def test_get_kubecfg_cli_arg_should_have_precedence(self):
        # kubeconfig specified via CLI should have precedence over env var
        kubeutil.os.environ = {'KUBECONFIG': 'should_be_ignored'}
        self.fixture_args.kubeconfig = sys.executable

        self.examinee.get_kubecfg()
        self.kubernetes_config_mock.load_kube_config.assert_called_with(sys.executable)

    def test_get_kubecfg_env_should_be_honoured(self):
        kubeutil.os.environ = {'KUBECONFIG': sys.executable}

        self.examinee.get_kubecfg()

        self.kubernetes_config_mock.load_kube_config.assert_called_with(sys.executable)

    def test_get_kubecfg_should_fail_on_absent_file(self):
        self.fixture_args.kubeconfig = 'no such file'

        # silence output (we do not care about it, though)
        with capture_out() as (stdout, stderr):
            with self.assertRaises(Failure):
                self.examinee.get_kubecfg()


