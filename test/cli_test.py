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

import os
import subprocess
import unittest

# assumption: we reside exactly one directory below our sources
SRC_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        os.pardir
    )
)
CLI_PY = os.path.join(SRC_DIR, 'cli.py')

class CliTest(unittest.TestCase):
    def test_smoke(self):
        # perform a very weak smoke-test:
        # test if a trivial sub-command can be run
        result = subprocess.run(
            [CLI_PY, 'util', 'info', '--msg', 'foobar'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        self.assertEqual(result.stdout.strip(), 'INFO: foobar')
        self.assertEqual(result.stderr.strip(), '')
        self.assertEqual(result.returncode, 0)


